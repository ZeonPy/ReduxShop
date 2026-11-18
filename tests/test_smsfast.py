"""Тесты клиента SMSFast, парсеров и миграции v4."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.constants import OrderStatus
from app.db import Database
from app.db.connection import Connection
from app.db.schema import SCHEMA_VERSION, _BASE, _INDEXES, _SETTINGS, migrate
from app.runtime import RuntimeConfig
from app.services.bootstrap import CatalogService
from app.services.fulfillment import FulfillmentService
from app.services.orders import OrderService
from app.services.smsfast import (
    Activation,
    ProviderPrice,
    SmsFastAuthError,
    SmsFastClient,
    SmsFastNoNumbersError,
    SmsStatus,
    parse_activation,
    parse_balance,
    parse_prices,
    parse_status,
)
from app.smsfast_countries import provider_country_id, provider_country_name
from tests import make_config, make_settings


class SmsFastParserTest(unittest.TestCase):
    def test_parse_balance(self) -> None:
        self.assertEqual(parse_balance("ACCESS_BALANCE:150.50"), 150.5)
        self.assertEqual(parse_balance("ACCESS_BALANCE:12,5"), 12.5)

    def test_parse_balance_rejects_bad_key(self) -> None:
        with self.assertRaises(SmsFastAuthError):
            parse_balance("BAD_KEY")

    def test_parse_activation(self) -> None:
        activation = parse_activation("ACCESS_NUMBER:12345:79991234567")
        self.assertEqual(activation, Activation("12345", "79991234567"))

    def test_parse_activation_errors(self) -> None:
        from app.services.smsfast import SmsFastError

        with self.assertRaises(SmsFastError):
            parse_activation("NO_NUMBERS")

    def test_parse_status_variants(self) -> None:
        waiting = parse_status("STATUS_WAIT_CODE")
        self.assertEqual(waiting.state, "waiting")
        retry = parse_status("STATUS_WAIT_RETRY:1234")
        self.assertEqual((retry.state, retry.code), ("retry", "1234"))
        ok = parse_status("STATUS_OK:54321")
        self.assertEqual((ok.state, ok.code), ("ok", "54321"))
        cancel = parse_status("STATUS_CANCEL")
        self.assertEqual(cancel.state, "cancel")

    def test_parse_prices_nested_service(self) -> None:
        payload = {
            "2": {"ot": {"cost": 12.5, "count": 4}, "tg": {"cost": 20, "count": 1}},
            "16": {"ot": {"cost": 3, "count": 0}},
        }
        prices = parse_prices(payload, "ot")
        self.assertEqual(prices[2], ProviderPrice(12.5, 4))
        self.assertEqual(prices[2].cost_rub, 13)
        self.assertEqual(prices[16].cost_rub, 3)

    def test_parse_prices_flat_service(self) -> None:
        payload = {"2": {"cost": 9.2, "count": 7}}
        prices = parse_prices(payload, "ot")
        self.assertEqual(prices[2].cost, 9.2)
        self.assertEqual(prices[2].count, 7)

    def test_parse_prices_without_filter_chooses_cheapest(self) -> None:
        payload = {
            "2": {
                "ot": {"cost": 30, "count": 5},
                "tg": {"cost": 10, "count": 3},
            }
        }
        self.assertAlmostEqual(parse_prices(payload)[2].cost, 10)

    def test_parse_prices_wrapped_payload(self) -> None:
        payload = {"data": {"2": {"ot": {"cost": 5, "count": 1}}}}
        self.assertIn(2, parse_prices(payload, "ot"))


class CountryMappingTest(unittest.TestCase):
    def test_common_countries(self) -> None:
        self.assertEqual(provider_country_id("Австрия"), 50)
        self.assertEqual(provider_country_id("Бельгия"), 82)
        self.assertEqual(provider_country_id("США"), 187)
        self.assertEqual(provider_country_id("ЮАР"), 31)
        self.assertEqual(provider_country_id("Казахстан"), 2)
        self.assertEqual(provider_country_id("Великобритания"), 16)
        self.assertEqual(provider_country_id("Турция"), 62)

    def test_unknown_country(self) -> None:
        self.assertIsNone(provider_country_id("Лихтенштейн"))
        self.assertEqual(provider_country_name(187), "США")


class MigrationV4Test(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-v4-")
        self.path = Path(self.tmp.name) / "old.db"

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_v3_database_gets_provider_columns(self) -> None:
        conn = Connection(self.path)
        await conn.connect()
        await conn.executescript(_BASE)
        await conn.executescript(_INDEXES)
        await conn.executescript(_SETTINGS)
        await conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO meta (key, value) VALUES ('schema_version', '3');"
        )
        await conn.close()

        # Старая база должна открыться и получить новые колонки.
        db = Database(self.path)
        await db.connect()
        try:
            self.assertEqual(
                int(await db.meta.get("schema_version") or 0), SCHEMA_VERSION
            )
            orders = {
                row["name"]
                for row in await db.connection.fetchall("PRAGMA table_info(orders)")
            }
            self.assertTrue(
                {"cost", "provider", "provider_id", "provider_phone", "sms_code"}
                <= orders
            )
            products = {
                row["name"]
                for row in await db.connection.fetchall("PRAGMA table_info(products)")
            }
            self.assertIn("cost", products)
            categories = {
                row["name"]
                for row in await db.connection.fetchall(
                    "PRAGMA table_info(categories)"
                )
            }
            self.assertIn("provider_id", categories)
            # Повторная миграция не должна падать.
            await migrate(db.connection)
        finally:
            await db.close()


class SmsFastClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-smsfast-")
        self.config = make_config(Path(self.tmp.name))
        self.settings = make_settings(Path(self.tmp.name))

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_unconfigured_client_refuses_requests(self) -> None:
        self.config.smsfast_api_key = ""
        client = SmsFastClient(self.config)
        self.assertFalse(client.configured)
        with self.assertRaises(SmsFastAuthError):
            await client.balance()
        await client.close()

    def test_key_masking(self) -> None:
        settings = make_settings(
            Path(self.tmp.name), smsfast_api_key="abcdef123456"
        )
        config = RuntimeConfig.from_settings(settings)
        self.assertEqual(config.smsfast_key_masked, "abc…456")


class FakeSmsFast:
    """Минимальный двойник SmsFastClient без сети."""

    def __init__(self, cost: float = 10.0, balance: float = 1000.0) -> None:
        self.cost = cost
        self._balance = balance
        self.service = ""

    async def prices(self, service: str | None = None) -> dict[int, ProviderPrice]:
        self.service = service or ""
        from app.smsfast_countries import SMSFAST_COUNTRIES

        return {
            api_id: ProviderPrice(self.cost, 10)
            for api_id, _name in SMSFAST_COUNTRIES
        }

    async def balance(self) -> float:
        return self._balance


class ProviderSyncTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-sync-")
        self.config = make_config(Path(self.tmp.name))
        self.db = Database(self.config.base.db_path)
        await self.db.connect()
        self.catalog = CatalogService(self.db, self.config)
        await self.catalog.ensure_ready()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_sync_replaces_wholesale_and_retail(self) -> None:
        result = await self.catalog.sync_provider(FakeSmsFast(cost=10))
        self.assertEqual(result.service, "ot")
        # В справочнике SMSFast нет Ниуэ, Самоа и Лихтенштейна.
        self.assertEqual(result.matched, 190)
        self.assertEqual(result.missing_map, 3)
        self.assertEqual(result.priced, 190)
        self.assertGreater(result.updated, 0)
        self.assertEqual(result.balance, 1000.0)

        products = await self.db.products.list(active_only=False)
        mapped = [product for product in products if product.provider_id is not None]
        self.assertEqual(len(mapped), 190)
        for product in mapped:
            self.assertEqual(product.cost, 10)
            self.assertEqual(product.price, self.config.retail_price(10))

        status = await self.catalog.provider_status()
        self.assertEqual(status.mapped, 190)
        self.assertEqual(status.with_cost, len(products))
        self.assertNotEqual(status.last_sync, "ещё не было")

    async def test_apply_after_sync_keeps_provider_cost(self) -> None:
        await self.catalog.sync_provider(FakeSmsFast(cost=57))
        await self.catalog.apply_retail_prices(force=True)
        products = await self.db.products.list(active_only=False)
        mapped = [product for product in products if product.provider_id is not None]
        self.assertTrue(mapped)
        for product in mapped:
            self.assertEqual(product.cost, 57)
            self.assertEqual(product.price, self.config.retail_price(57))


class ProviderOrderTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-provider-order-")
        self.config = make_config(Path(self.tmp.name))
        self.db = Database(self.config.base.db_path)
        await self.db.connect()
        category_id = await self.db.categories.create("🇦🇹 Австрия", provider_id=50)
        self.product_id = await self.db.products.create(
            "Виртуальный номер · Австрия",
            129,
            "Описание",
            category_id=category_id,
            cost=60,
        )
        await self.db.users.upsert(10, "client", "Клиент")
        self.order_id = await self.db.orders.create(
            10, self.product_id, 129, cost=60
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_activation_lifecycle(self) -> None:
        order = await self.db.orders.get(self.order_id)
        self.assertEqual(order.cost, 60)
        self.assertEqual(order.profit, 69)

        self.assertTrue(await self.db.orders.mark_paid(self.order_id))
        self.assertTrue(await self.db.orders.start_processing(self.order_id))
        self.assertFalse(await self.db.orders.start_processing(self.order_id))

        await self.db.orders.set_provider_activation(
            self.order_id,
            provider="smsfast",
            provider_id="act-1",
            phone="+43 123",
            cost=57,
        )
        order = await self.db.orders.get(self.order_id)
        self.assertEqual(order.status, OrderStatus.PROCESSING)
        self.assertEqual(order.provider_phone, "+43 123")
        self.assertEqual(order.cost, 57)
        self.assertEqual(order.profit, 72)

        self.assertTrue(
            await self.db.orders.mark_provider_delivered(self.order_id, "54321")
        )
        order = await self.db.orders.get(self.order_id)
        self.assertEqual(order.status, OrderStatus.DELIVERED)
        self.assertEqual(order.sms_code, "54321")
        self.assertIsNotNone(order.delivered_at)
        self.assertFalse(
            await self.db.orders.mark_provider_delivered(self.order_id, "999")
        )

    async def test_return_to_paid_before_number_purchase(self) -> None:
        await self.db.orders.mark_paid(self.order_id)
        await self.db.orders.start_processing(self.order_id)
        self.assertTrue(
            await self.db.orders.return_to_paid(self.order_id, "нет номеров")
        )
        order = await self.db.orders.get(self.order_id)
        self.assertEqual(order.status, OrderStatus.PAID)
        self.assertEqual(order.provider_error, "нет номеров")

    async def test_deliverability_counts_provider_orders(self) -> None:
        await self.db.orders.mark_paid(self.order_id)
        await self.db.orders.start_processing(self.order_id)
        await self.db.orders.set_provider_activation(
            self.order_id,
            provider="smsfast",
            provider_id="act-1",
            phone="+43 123",
            cost=57,
        )
        await self.db.orders.mark_provider_delivered(self.order_id, "1111")

        stats = await self.db.stats.summary()
        self.assertEqual(stats.provider_delivered, 1)
        self.assertEqual(stats.provider_failed, 0)
        self.assertEqual(stats.deliverability, 100)

        failed_id = await self.db.orders.create(
            10, self.product_id, 129, cost=60
        )
        await self.db.orders.mark_paid(failed_id)
        await self.db.orders.start_processing(failed_id)
        await self.db.orders.set_provider_activation(
            failed_id,
            provider="smsfast",
            provider_id="act-2",
            phone="+43 456",
            cost=57,
        )
        await self.db.orders.fail_provider(failed_id, "таймаут")

        stats = await self.db.stats.summary()
        self.assertEqual(stats.provider_delivered, 1)
        self.assertEqual(stats.provider_failed, 1)
        self.assertEqual(stats.deliverability, 50)

    async def test_manual_delivery_after_provider_failure(self) -> None:
        await self.db.orders.mark_paid(self.order_id)
        await self.db.orders.start_processing(self.order_id)
        await self.db.orders.set_provider_activation(
            self.order_id,
            provider="smsfast",
            provider_id="act-3",
            phone="+43 999",
            cost=57,
        )
        await self.db.orders.fail_provider(self.order_id, "таймаут")
        await self.db.products.add_stock(self.product_id, ["резервный номер"])

        orders = OrderService(self.db, FakeNotifier())
        blocked = await orders.deliver(self.order_id)
        self.assertFalse(blocked.ok)
        self.assertIn("отменён", blocked.message)

        result = await orders.deliver_manual(self.order_id)
        self.assertTrue(result.ok)
        fresh = await self.db.orders.get(self.order_id)
        self.assertEqual(fresh.status, OrderStatus.DELIVERED)
        self.assertEqual(fresh.provider, "smsfast")
        self.assertEqual(fresh.provider_phone, "")
        self.assertEqual(
            await self.db.products.stock_content(self.order_id), "резервный номер"
        )

        stats = await self.db.stats.summary()
        self.assertEqual(stats.provider_delivered, 0)
        self.assertEqual(stats.provider_failed, 1)
        self.assertEqual(stats.deliverability, 0)


class FakeNotifier:
    def __init__(self) -> None:
        self.user: list[tuple[int, str, dict]] = []
        self.admin: list[tuple[str, dict]] = []

    async def to_user(
        self, user_id: int, text: str, **kwargs
    ) -> bool:
        self.user.append((user_id, text, kwargs))
        return True

    async def to_admins(self, text: str, **kwargs) -> int:
        self.admin.append((text, kwargs))
        return 1


class FakeActivationClient:
    def __init__(self, code: str = "54321") -> None:
        self.code = code
        self.status_calls: list[tuple[str, int]] = []
        self.bought: list[tuple[str, int]] = []

    async def get_number(self, service: str, country: int):
        self.bought.append((service, country))
        return Activation("act-1", "+43 660 1234567")

    async def get_status(self, activation_id: str) -> SmsStatus:
        return SmsStatus("ok", self.code)

    async def set_status(self, activation_id: str, status: int) -> str:
        self.status_calls.append((activation_id, status))
        return "ACCESS_READY"


class FakeNoNumbersClient(FakeActivationClient):
    async def get_number(self, service: str, country: int):
        raise SmsFastNoNumbersError("SMSFast: нет номеров")


class FulfillmentTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-fulfillment-")
        self.config = make_config(
            Path(self.tmp.name), smsfast_api_key="test-key-123456"
        )
        self.config.smsfast_poll_interval = 2
        self.config.smsfast_timeout = 60
        self.db = Database(self.config.base.db_path)
        await self.db.connect()
        category_id = await self.db.categories.create("🇦🇹 Австрия", provider_id=50)
        self.product_id = await self.db.products.create(
            "Виртуальный номер · Австрия",
            149,
            "Описание",
            category_id=category_id,
            cost=60,
        )
        await self.db.users.upsert(10, "client", "Клиент")
        self.notifier = FakeNotifier()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def _order(self) -> int:
        order_id = await self.db.orders.create(
            10, self.product_id, 149, cost=60
        )
        return order_id

    async def _service(self, client) -> FulfillmentService:
        return FulfillmentService(
            self.db, self.notifier, self.config, client
        )

    async def test_number_is_bought_only_after_payment(self) -> None:
        order_id = await self._order()
        order = await self.db.orders.get(order_id)
        service = await self._service(FakeActivationClient())
        start = await service.begin(order)
        self.assertFalse(start.started)
        self.assertIn("оплату", start.message)
        self.assertEqual(
            (await self.db.orders.get(order_id)).status, OrderStatus.NEW
        )

    async def test_code_is_delivered_and_activation_closed(self) -> None:
        order_id = await self._order()
        await self.db.orders.mark_paid(order_id)
        client = FakeActivationClient()
        service = await self._service(client)
        order = await self.db.orders.get(order_id)

        start = await service.begin(order)
        self.assertTrue(start.started)
        self.assertEqual(client.bought, [("ot", 50)])
        await asyncio.wait_for(
            asyncio.gather(*list(service._tasks)), timeout=15
        )

        fresh = await self.db.orders.get(order_id)
        self.assertEqual(fresh.status, OrderStatus.DELIVERED)
        self.assertEqual(fresh.sms_code, "54321")
        self.assertEqual(fresh.provider, "smsfast")
        self.assertEqual(fresh.provider_phone, "+43 660 1234567")
        self.assertEqual(client.status_calls, [("act-1", 3)])
        self.assertTrue(
            any("54321" in text for _, text, _ in self.notifier.user)
        )
        self.assertTrue(
            any("SMS получен" in text for text, _ in self.notifier.admin)
        )

    async def test_no_numbers_falls_back_to_manual_stock(self) -> None:
        order_id = await self._order()
        await self.db.orders.mark_paid(order_id)
        await self.db.products.add_stock(self.product_id, ["номер-вручную"])
        service = await self._service(FakeNoNumbersClient())
        orders = OrderService(self.db, self.notifier, service)

        result = await orders.deliver(order_id)
        self.assertTrue(result.ok)
        self.assertFalse(result.pending)
        fresh = await self.db.orders.get(order_id)
        self.assertEqual(fresh.status, OrderStatus.DELIVERED)
        self.assertEqual(
            await self.db.products.stock_content(order_id), "номер-вручную"
        )


if __name__ == "__main__":
    unittest.main()