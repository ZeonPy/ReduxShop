from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.pricing import MIN_PRICE
from app.services.bootstrap import CatalogService, product_title
from app.countries import COUNTRIES
from tests import make_config


class BootstrapTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-seed-")
        self.config = make_config(Path(self.tmp.name))
        self.db = Database(self.config.db_path)
        await self.db.connect()
        self.catalog = CatalogService(self.db, self.config)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_seed_creates_193_countries_and_is_idempotent(self) -> None:
        state = await self.catalog.ensure_ready()
        self.assertEqual(state.seeded, 193)
        self.assertEqual(state.products, 193)
        self.assertEqual(await self.db.categories.count(), 193)
        self.assertEqual(await self.db.products.count(), 193)

        second = await self.catalog.ensure_ready()
        self.assertEqual(second.seeded, 0)
        self.assertEqual(second.repriced, 0)
        self.assertEqual(await self.db.categories.count(), 193)

    async def test_all_catalog_prices_respect_minimum(self) -> None:
        await self.catalog.ensure_ready()
        rows = await self.db.connection.fetchall(
            "SELECT title, price FROM products"
        )
        self.assertEqual(len(rows), 193)
        for row in rows:
            self.assertGreaterEqual(row["price"], MIN_PRICE, row["title"])

    async def test_manual_product_keeps_its_price(self) -> None:
        await self.catalog.ensure_ready()
        category_id = await self.db.categories.create("🌍 Ручная категория")
        product_id = await self.db.products.create(
            "Ручной товар", 777, "", category_id
        )
        await self.catalog.apply_retail_prices(force=True)
        product = await self.db.products.get(product_id)
        self.assertEqual(product.price, 777)

    async def test_known_country_product_titles_exist(self) -> None:
        await self.catalog.ensure_ready()
        for country in COUNTRIES[:5]:
            row = await self.db.connection.fetchone(
                "SELECT id FROM products WHERE title = ?",
                (product_title(country),),
            )
            self.assertIsNotNone(row, country.name)


if __name__ == "__main__":
    unittest.main()
