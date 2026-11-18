"""Публичный интерфейс слоя данных."""

from __future__ import annotations

from pathlib import Path

from app.db.connection import Connection
from app.db.repositories import (
    CategoryRepository,
    MetaRepository,
    OrderRepository,
    ProductRepository,
    SettingsRepository,
    StatsRepository,
    TicketRepository,
    UserRepository,
)
from app.db.schema import SCHEMA_VERSION, migrate

__all__ = ["Database", "SCHEMA_VERSION"]


class Database:
    """Фасад над репозиториями: `db.orders`, `db.tickets` и т.д."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = Connection(self.path)
        self.meta = MetaRepository(self.connection)
        self.settings = SettingsRepository(self.connection)
        self.users = UserRepository(self.connection)
        self.categories = CategoryRepository(self.connection)
        self.products = ProductRepository(self.connection)
        self.orders = OrderRepository(self.connection)
        self.tickets = TicketRepository(self.connection)
        self.stats = StatsRepository(self.connection)

    async def connect(self) -> None:
        await self.connection.connect()
        await migrate(self.connection)

    async def close(self) -> None:
        await self.connection.close()
