from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context import AppContext
from app.db import Database
from app.main import build_dispatcher
from app.services.config import ConfigService
from tests import make_config


class DispatcherTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reduxshop-dp-")
        base = make_config(Path(self.tmp.name))
        self.db = Database(base.db_path)
        await self.db.connect()
        self.service = ConfigService(base.base, self.db)
        self.config = await self.service.load()
        self.ctx = AppContext.build(
            self.config, self.db, object(), self.service
        )
        self.dp = build_dispatcher(self.ctx)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_routers_are_connected(self) -> None:
        self.assertGreaterEqual(len(self.dp.sub_routers), 13)
        names = {router.name for router in self.dp.sub_routers}
        for name in (
            "common",
            "catalog",
            "orders",
            "support",
            "admin_panel",
            "admin_orders",
            "admin_tickets",
            "admin_clients",
            "admin_products",
            "admin_settings",
            "admin_banners",
            "fallback",
            "errors",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
