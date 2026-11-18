"""Наполнение каталога, розничные цены и синхронизация с SMSFast."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.countries import COUNTRIES, Country
from app.db import Database
from app.models import Category, Product
from app.runtime import RuntimeConfig
from app.services.smsfast import ProviderPrice, SmsFastClient
from app.smsfast_countries import normalize_name, provider_country_id

logger = logging.getLogger(__name__)

COUNTRIES_META_KEY = "countries"
PRICING_META_KEY = "pricing_version"
SMSFAST_SYNC_META_KEY = "smsfast_synced_at"
SMSFAST_SERVICE_META_KEY = "smsfast_synced_service"
DEMO_CATEGORY_TITLE = "Виртуальные номера"


def product_title(country: Country) -> str:
    return f"Виртуальный номер · {country.name}"


def product_description(country: Country) -> str:
    return (
        f"Страна: {country.name} ({country.phone}). Одноразовый номер "
        "для приёма SMS. Данные приходят в этот чат после выдачи заказа."
    )


@dataclass(frozen=True, slots=True)
class CatalogState:
    seeded: int
    repriced: int
    products: int


@dataclass(frozen=True, slots=True)
class ProviderSyncResult:
    service: str
    countries: int
    matched: int
    priced: int
    updated: int
    missing_map: int
    missing_price: int
    balance: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    countries: int
    mapped: int
    with_cost: int
    last_sync: str
    service: str
    delivered: int = 0
    failed: int = 0
    deliverability: int = 0


def _country_by_title() -> dict[str, Country]:
    return {product_title(country): country for country in COUNTRIES}


def _country_by_normalized_name() -> dict[str, Country]:
    return {normalize_name(country.name): country for country in COUNTRIES}


def _category_country(title: str, by_name: dict[str, Country]) -> Country | None:
    return by_name.get(normalize_name(title))


class CatalogService:
    """Первый запуск: страны → категории → товары, затем цены и SMSFast."""

    def __init__(self, db: Database, settings: RuntimeConfig) -> None:
        self._db = db
        self._settings = settings

    async def ensure_ready(self) -> CatalogState:
        seeded = await self.seed()
        repriced = await self.apply_retail_prices()
        products = await self._db.products.count()
        return CatalogState(seeded=seeded, repriced=repriced, products=products)

    async def seed(self) -> int:
        """Создаёт 193 страны-категории и товары. Повторный запуск — no-op."""
        if await self._db.meta.get(COUNTRIES_META_KEY):
            return 0

        if await self._is_demo_catalog():
            logger.info("Удаляю демо-каталог перед заливкой стран")
            await self._db.categories.reset_demo()

        created = 0
        if await self._db.categories.count() == 0:
            for country in COUNTRIES:
                category_id = await self._db.categories.create(
                    f"{country.emoji} {country.name}",
                    provider_country_id(country.name),
                )
                await self._db.products.create(
                    product_title(country),
                    self._settings.retail_price(country.wholesale),
                    product_description(country),
                    category_id=category_id,
                    cost=country.wholesale,
                )
                created += 1

        await self._db.meta.set(COUNTRIES_META_KEY, "1")
        if created:
            logger.info("Каталог создан: %s стран", created)
        return created

    async def apply_retail_prices(self, force: bool = False) -> int:
        """Приводит цены стран к `rules.price(cost)`.

        Закупка берётся из `products.cost`, а если её ещё нет — из старого
        справочника simdrop. Это чинит базы, где раньше в цену случайно
        записали закупку. Правило идемпотентно: повторный запуск ничего не
        меняет и возвращает 0.
        """
        rules = self._settings.pricing
        by_title = _country_by_title()
        products = await self._db.products.list(active_only=False)
        categories = {category.id: category for category in await self._db.categories.list_all()}

        updated = 0
        for product in products:
            country = by_title.get(product.title)
            if country is None:
                continue

            provider_id = provider_country_id(country.name)
            category = categories.get(product.category_id)
            if category is not None and provider_id is not None:
                await self._db.categories.set_provider_id(category.id, provider_id)

            cost = product.cost if product.cost > 0 else country.wholesale
            expected = rules.price(cost)
            if force or product.cost != cost or product.price != expected:
                changed = await self._db.products.update_country_product(
                    product.id, expected, cost
                )
                # force=True пересчитывает весь каталог: даже если цена не
                # изменилась, админка должна показать, сколько стран прошло.
                updated += 1 if force else changed

        signature = self._settings.pricing_signature
        await self._db.meta.set(PRICING_META_KEY, signature)
        await self._db.meta.delete("price_multiplier")
        logger.info(
            "Розничные цены проверены: %s обновлений, минимум %s %s (прайс %s)",
            updated,
            rules.min_price,
            self._settings.currency,
            signature,
        )
        return updated

    async def sync_provider(self, client: SmsFastClient) -> ProviderSyncResult:
        """Подтягивает закупку SMSFast и пересчитывает розничные цены.

        `getPrices` отдаёт цены в валюте аккаунта (у SMSFast — рубли).
        Сопоставление идёт по `categories.provider_id`, а для старых баз —
        по названию страны из заголовка категории.
        """
        service = self._settings.smsfast_service
        prices = await client.prices(service)
        balance: float | None = None
        try:
            balance = await client.balance()
        except Exception as exc:  # баланс не должен ломать синхронизацию
            logger.info("Не удалось получить баланс SMSFast: %s", exc)

        categories = await self._db.categories.list_all()
        products = await self._db.products.list(active_only=False)
        product_by_category: dict[int, list[Product]] = {}
        by_title = _country_by_title()
        by_name = _country_by_normalized_name()

        for product in products:
            product_by_category.setdefault(product.category_id, []).append(product)

        matched = 0
        priced = 0
        updated = 0
        missing_map = 0
        missing_price = 0

        for category in categories:
            country = _category_country(category.title, by_name)
            provider_id = category.provider_id
            if provider_id is None and country is not None:
                provider_id = provider_country_id(country.name)
            if provider_id is None:
                missing_map += 1
                continue

            matched += 1
            await self._db.categories.set_provider_id(category.id, provider_id)

            price = prices.get(provider_id)
            if price is None:
                missing_price += 1
                continue

            target = self._country_product(
                category, product_by_category.get(category.id, []), by_title
            )
            if target is None or country is None:
                missing_price += 1
                continue

            priced += 1
            cost = price.cost_rub
            new_price = self._settings.retail_price(cost)
            updated += await self._db.products.update_country_product(
                target.id, new_price, cost
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        await self._db.meta.set(SMSFAST_SYNC_META_KEY, now)
        await self._db.meta.set(SMSFAST_SERVICE_META_KEY, service)

        logger.info(
            "SMSFast синхронизирован: сервис %s, стран %s, цен %s, обновлено %s, "
            "без цены %s, без mapping %s",
            service,
            matched,
            priced,
            updated,
            missing_price,
            missing_map,
        )
        return ProviderSyncResult(
            service=service,
            countries=len(categories),
            matched=matched,
            priced=priced,
            updated=updated,
            missing_map=missing_map,
            missing_price=missing_price,
            balance=balance,
        )

    async def provider_status(self) -> ProviderStatus:
        categories = await self._db.categories.list_all()
        products = await self._db.products.list(active_only=False)
        mapped = sum(1 for category in categories if category.provider_id is not None)
        with_cost = sum(1 for product in products if product.cost > 0)
        last_sync = await self._db.meta.get(SMSFAST_SYNC_META_KEY, "") or "ещё не было"
        service = (
            await self._db.meta.get(SMSFAST_SERVICE_META_KEY, "")
            or self._settings.smsfast_service
        )
        delivered, failed = await self._db.stats.provider_outcomes()
        total = delivered + failed
        return ProviderStatus(
            countries=len(categories),
            mapped=mapped,
            with_cost=with_cost,
            last_sync=last_sync,
            service=service,
            delivered=delivered,
            failed=failed,
            deliverability=round(delivered * 100 / total) if total else 0,
        )

    async def last_provider_prices(self) -> dict[int, ProviderPrice]:
        """Зарезервировано для экрана админки; сейчас цены живут в products."""
        return {}

    @staticmethod
    def _country_product(
        category: Category, products: list[Product], by_title: dict[str, Country]
    ) -> Product | None:
        for product in products:
            if product.title in by_title:
                return product
        if len(products) == 1:
            return products[0]
        return None

    async def _is_demo_catalog(self) -> bool:
        if await self._db.categories.count() != 1:
            return False
        if await self._db.orders.count() != 0:
            return False
        categories = await self._db.categories.list_page(1, 0)
        return bool(categories and categories[0].title == DEMO_CATEGORY_TITLE)
