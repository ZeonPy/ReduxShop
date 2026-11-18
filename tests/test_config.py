from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.pricing import PricingRules
from app.services.bootstrap import CatalogService
from app.services.config import BANNER_PREFIX, ConfigError, ConfigService
from app.ui.banners import BANNERS
from tests import make_settings


class ConfigServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-config-")
        self.base = make_settings(Path(self.tmp.name))
        self.db = Database(self.base.db_path)
        await self.db.connect()
        self.service = ConfigService(self.base, self.db)
        self.config = await self.service.load()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    def test_defaults_from_env(self) -> None:
        self.assertEqual(self.config.shop_name, "ReduxShop")
        self.assertEqual(self.config.currency, "₽")
        self.assertEqual(self.config.pricing, PricingRules())
        self.assertTrue(self.config.banners_enabled)
        self.assertEqual(self.config.banner_file_ids, {})

    async def test_update_shop_name_and_link(self) -> None:
        self.assertFalse(
            await self.service.update(self.config, "shop_name", "  Новый магазин  ")
        )
        self.assertEqual(self.config.shop_name, "Новый магазин")
        await self.service.update(
            self.config, "shop_link", "https://t.me/newshop"
        )
        self.assertEqual(self.config.shop_link, "https://t.me/newshop")

        reloaded = await self.service.load()
        self.assertEqual(reloaded.shop_name, "Новый магазин")
        self.assertEqual(reloaded.shop_link, "https://t.me/newshop")

    async def test_invalid_values_are_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            await self.service.update(self.config, "shop_name", "x")
        with self.assertRaises(ConfigError):
            await self.service.update(self.config, "shop_link", "t.me/x")
        with self.assertRaises(ConfigError):
            await self.service.update(self.config, "min_price", "десять")
        with self.assertRaises(ConfigError):
            await self.service.update(self.config, "cheap_multiplier", "0")
        self.assertIsNone(await self.db.settings.get("shop_name"))

    async def test_pricing_change_returns_flag(self) -> None:
        changed = await self.service.update(self.config, "min_price", "500")
        self.assertTrue(changed)
        self.assertEqual(self.config.pricing.min_price, 500)
        changed = await self.service.update(self.config, "cheap_limit", "80")
        self.assertTrue(changed)
        self.assertEqual(self.config.pricing.cheap_limit, 80)

    async def test_banners_and_persistence(self) -> None:
        screen = next(iter(BANNERS))
        await self.service.set_banners_enabled(self.config, False)
        await self.service.set_banner(self.config, screen, "file-id-123")
        reloaded = await self.service.load()
        self.assertFalse(reloaded.banners_enabled)
        self.assertEqual(reloaded.banner_file_ids[screen], "file-id-123")
        self.assertEqual(
            await self.db.settings.get(f"{BANNER_PREFIX}{screen}"), "file-id-123"
        )

        await self.service.reset_banner(self.config, screen)
        self.assertNotIn(screen, self.config.banner_file_ids)
        self.assertIsNone(
            await self.db.settings.get(f"{BANNER_PREFIX}{screen}")
        )

    async def test_reprice_with_custom_rules(self) -> None:
        await self.service.update(self.config, "min_price", "500")
        await self.service.update(self.config, "cheap_multiplier", "4")
        catalog = CatalogService(self.db, self.config)
        await catalog.ensure_ready()
        updated = await catalog.apply_retail_prices(force=True)
        self.assertEqual(updated, 193)
        prices = await self.db.connection.fetchall(
            "SELECT price FROM products ORDER BY id"
        )
        self.assertTrue(prices)
        self.assertTrue(all(row["price"] >= 500 for row in prices))


if __name__ == "__main__":
    unittest.main()
