"""Обёртка над aiosqlite: соединение, транзакции и базовые запросы."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import aiosqlite

logger = logging.getLogger(__name__)


class Connection:
    """Тонкая обёртка, которая не даёт забыть commit и умеет транзакции."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._tx_depth = 0
        self._tx_owner: asyncio.Task | None = None
        self._tx_lock = asyncio.Lock()

    @property
    def raw(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных ещё не подключена")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.commit()
        logger.info("База данных подключена: %s", self.path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        cursor = await self.raw.execute(sql, tuple(params))
        if self._tx_depth == 0:
            await self.raw.commit()
        return cursor

    async def executemany(
        self, sql: str, params: Iterable[Iterable[Any]]
    ) -> aiosqlite.Cursor:
        cursor = await self.raw.executemany(sql, [tuple(row) for row in params])
        if self._tx_depth == 0:
            await self.raw.commit()
        return cursor

    async def executescript(self, sql: str) -> None:
        await self.raw.executescript(sql)
        if self._tx_depth == 0:
            await self.raw.commit()

    async def fetchone(
        self, sql: str, params: Iterable[Any] = ()
    ) -> aiosqlite.Row | None:
        async with self.raw.execute(sql, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def fetchall(
        self, sql: str, params: Iterable[Any] = ()
    ) -> list[aiosqlite.Row]:
        async with self.raw.execute(sql, tuple(params)) as cursor:
            return list(await cursor.fetchall())

    async def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        return None if row is None else row[0]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Транзакция с немедленной блокировкой записи.

        Вложенные вызовы из той же задачи присоединяются к внешней
        транзакции. Параллельные задачи ждут на блокировке, поэтому два
        заказа не могут получить одну и ту же позицию стока.
        """
        task = asyncio.current_task()
        if self._tx_depth and self._tx_owner is task:
            yield
            return

        async with self._tx_lock:
            await self.raw.execute("BEGIN IMMEDIATE")
            self._tx_depth = 1
            self._tx_owner = task
            try:
                yield
            except BaseException:
                await self.raw.rollback()
                raise
            else:
                await self.raw.commit()
            finally:
                self._tx_depth = 0
                self._tx_owner = None
