from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.constants import TicketSender
from app.db import Database
from app.db.schema import SCHEMA_VERSION, migrate
from tests import make_settings


class DatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-db-")
        self.settings = make_settings(Path(self.tmp.name))
        self.db = Database(self.settings.db_path)
        await self.db.connect()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def _product(self, price: int = 149, stock: int = 1) -> int:
        category_id = await self.db.categories.create("🌍 Тестовая страна")
        product_id = await self.db.products.create(
            "Виртуальный номер · Тест", price, "Описание", category_id
        )
        if stock:
            await self.db.products.add_stock(
                product_id, [f"номер-{index}" for index in range(stock)]
            )
        return product_id

    async def test_schema_version_and_idempotent_migration(self) -> None:
        value = await self.db.meta.get("schema_version")
        self.assertEqual(int(value or 0), SCHEMA_VERSION)
        await migrate(self.db.connection)
        self.assertEqual(
            int(await self.db.meta.get("schema_version") or 0), SCHEMA_VERSION
        )

    async def test_delivery_marks_stock_and_order(self) -> None:
        await self.db.users.upsert(10, "client", "Клиент")
        product_id = await self._product(stock=1)
        order_id = await self.db.orders.create(10, product_id, 149)

        delivered = await self.db.orders.deliver(order_id)
        self.assertIsNotNone(delivered)
        order, item = delivered  # type: ignore[misc]
        self.assertEqual(item, "номер-0")
        self.assertEqual(order.status.value, "delivered")
        self.assertEqual(await self.db.products.stock_count(product_id), 0)
        self.assertEqual(await self.db.products.stock_content(order_id), "номер-0")
        self.assertIsNone(await self.db.orders.deliver(order_id))

    async def test_delivery_without_stock_returns_none(self) -> None:
        await self.db.users.upsert(11, None, "Клиент")
        product_id = await self._product(stock=0)
        order_id = await self.db.orders.create(11, product_id, 149)
        self.assertIsNone(await self.db.orders.deliver(order_id))
        order = await self.db.orders.get(order_id)
        self.assertEqual(order.status.value, "new")

    async def test_two_orders_never_get_same_stock_item(self) -> None:
        await self.db.users.upsert(12, None, "Клиент")
        product_id = await self._product(stock=1)
        first = await self.db.orders.create(12, product_id, 149)
        second = await self.db.orders.create(12, product_id, 149)

        results = await asyncio.gather(
            self.db.orders.deliver(first), self.db.orders.deliver(second)
        )
        delivered = [result for result in results if result is not None]
        self.assertEqual(len(delivered), 1)

        statuses = {
            (await self.db.orders.get(first)).status,
            (await self.db.orders.get(second)).status,
        }
        self.assertEqual(len(statuses), 2)
        self.assertEqual(await self.db.products.stock_count(product_id), 0)

    async def test_mark_paid_only_from_new(self) -> None:
        await self.db.users.upsert(13, None, "Клиент")
        product_id = await self._product(stock=1)
        order_id = await self.db.orders.create(13, product_id, 149)

        self.assertTrue(await self.db.orders.mark_paid(order_id))
        self.assertFalse(await self.db.orders.mark_paid(order_id))
        order = await self.db.orders.get(order_id)
        self.assertEqual(order.status.value, "paid")
        self.assertIsNotNone(order.paid_at)

    async def test_stats_and_tickets(self) -> None:
        await self.db.users.upsert(14, "u", "Клиент")
        ticket = await self.db.tickets.get_or_create_open(14)
        await self.db.tickets.add_message(ticket.id, TicketSender.USER, "Помогите")
        listing = await self.db.tickets.list_open()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0].last_text, "Помогите")

        stats = await self.db.stats.summary()
        self.assertEqual(stats.users, 1)
        self.assertEqual(stats.open_tickets, 1)

        self.assertTrue(await self.db.tickets.close(ticket.id))
        self.assertFalse(await self.db.tickets.close(ticket.id))


if __name__ == "__main__":
    unittest.main()
