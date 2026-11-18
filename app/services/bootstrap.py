"""Наполнение каталога и обновление розничных цен."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.countries import COUNTRIES, Country
from app.db import Database
from app.runtime import RuntimeConfig

logger = logging.getLogger(__name__)

COUNTRIES_META_KEY = "countries"
PRICING_META_KEY = "pricing_version"
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


class CatalogService:
    """Первый запуск: страны → категории → товары, затем актуализация цен."""

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
                    f"{country.emoji} {country.name}"
                )
                await self._db.products.create(
                    product_title(country),
                    self._settings.retail_price(country.wholesale),
                    product_description(country),
                    category_id=category_id,
                )
                created += 1

        await self._db.meta.set(COUNTRIES_META_KEY, "1")
        if created:
            logger.info("Каталог создан: %s стран", created)
        return created

    async def apply_retail_prices(self, force: bool = False) -> int:
        """Пересчитывает цены стран по текущим правилам.

        Цена считается от закупочной цены simdrop, а не от сохранённой в базе,
        поэтому повторные запуски не накручивают наценку. Товары, добавленные
        админом вручную, не затрагиваются.
        """
        signature = self._settings.pricing_signature
        stored = await self._db.meta.get(PRICING_META_KEY)
        if not force and stored == signature:
            return 0

        rules = self._settings.pricing
        updated = 0
        for country in COUNTRIES:
            updated += await self._db.products.update_price_by_title(
                product_title(country), rules.price(country.wholesale)
            )

        await self._db.meta.set(PRICING_META_KEY, signature)
        await self._db.meta.delete("price_multiplier")
        logger.info(
            "Розничные цены обновлены: %s товаров, минимум %s %s (прайс %s)",
            updated,
            rules.min_price,
            self._settings.currency,
            signature,
        )
        return updated

    async def _is_demo_catalog(self) -> bool:
        if await self._db.categories.count() != 1:
            return False
        if await self._db.orders.count() != 0:
            return False
        categories = await self._db.categories.list_page(1, 0)
        return bool(categories and categories[0].title == DEMO_CATEGORY_TITLE)
