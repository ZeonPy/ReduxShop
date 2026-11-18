"""Схема БД и миграции.

Версия схемы хранится в `meta.schema_version`. Миграции идемпотентны,
поэтому старую базу можно обновлять простым рестартом бота.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.connection import Connection

SCHEMA_VERSION = 4

_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_BASE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    order_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    price INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    paid_at TEXT,
    delivered_at TEXT,
    stock_id INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_stock_product ON stock(product_id, order_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, status);
CREATE INDEX IF NOT EXISTS idx_ticket_messages ON ticket_messages(ticket_id);
"""

_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "base tables", _BASE),
    Migration(2, "indexes", _INDEXES),
    Migration(3, "runtime settings", _SETTINGS),
)


_V4_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "categories": (("provider_id", "INTEGER"),),
    "products": (("cost", "INTEGER NOT NULL DEFAULT 0"),),
    "orders": (
        ("cost", "INTEGER NOT NULL DEFAULT 0"),
        ("provider", "TEXT NOT NULL DEFAULT ''"),
        ("provider_id", "TEXT NOT NULL DEFAULT ''"),
        ("provider_phone", "TEXT NOT NULL DEFAULT ''"),
        ("sms_code", "TEXT NOT NULL DEFAULT ''"),
        ("provider_error", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT"),
    ),
}

_V4_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_categories_provider ON categories(provider_id);
CREATE INDEX IF NOT EXISTS idx_orders_provider ON orders(provider_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
"""


async def _table_columns(conn: Connection, table: str) -> set[str]:
    rows = await conn.fetchall(f"PRAGMA table_info({table})")
    return {str(row["name"]) for row in rows}


async def _add_columns(
    conn: Connection, table: str, columns: tuple[tuple[str, str], ...]
) -> None:
    existing = await _table_columns(conn, table)
    for name, definition in columns:
        if name in existing:
            continue
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


async def _migrate_v4(conn: Connection) -> None:
    """Добавляет поля SMSFast. SQLite не умеет ADD COLUMN IF NOT EXISTS."""
    for table, columns in _V4_COLUMNS.items():
        await _add_columns(conn, table, columns)
    await conn.executescript(_V4_INDEXES)


async def migrate(conn: Connection) -> None:
    await conn.executescript(_META)
    current = int(await conn.scalar("SELECT value FROM meta WHERE key = 'schema_version'") or 0)
    if current >= SCHEMA_VERSION:
        return

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        await conn.executescript(migration.sql)

    if current < 4:
        await _migrate_v4(conn)

    await conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
