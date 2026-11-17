"""SQLite-хранилище ReduxShop-бота: клиенты, товары, сток, заказы, поддержка."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from countries_data import COUNTRIES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_stock_product ON stock(product_id, order_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, status);
CREATE INDEX IF NOT EXISTS idx_ticket_messages ON ticket_messages(ticket_id);
"""

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        await self._seed()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def _seed(self) -> None:
        """Создаёт страны-категории и товары по данным simdrop (один раз)."""
        countries_seeded = await self.scalar("SELECT value FROM meta WHERE key = 'countries'")
        if countries_seeded:
            return

        categories = int(await self.scalar("SELECT COUNT(*) FROM categories") or 0)
        orders = int(await self.scalar("SELECT COUNT(*) FROM orders") or 0)
        only_demo = False
        if categories == 1 and orders == 0:
            title = await self.scalar("SELECT title FROM categories ORDER BY id LIMIT 1")
            only_demo = title == "Виртуальные номера"

        if only_demo:
            await self.execute("DELETE FROM stock WHERE order_id IS NULL")
            await self.execute("DELETE FROM products")
            await self.execute("DELETE FROM categories")

        if int(await self.scalar("SELECT COUNT(*) FROM categories") or 0) == 0:
            for emoji, name, phone, price, _count in COUNTRIES:
                cursor = await self.execute(
                    "INSERT INTO categories (title) VALUES (?)", (f"{emoji} {name}",)
                )
                category_id = int(cursor.lastrowid)
                await self.execute(
                    """
                    INSERT INTO products (category_id, title, description, price)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        category_id,
                        f"Виртуальный номер · {name}",
                        f"Страна: {name} ({phone}). Одноразовый номер для приёма SMS. "
                        "Данные приходят в этот чат после выдачи заказа.",
                        price,
                    ),
                )

        await self.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('countries', '1')"
        )

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        assert self.conn is not None
        cursor = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple = ()):
        assert self.conn is not None
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        assert self.conn is not None
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def scalar(self, sql: str, params: tuple = ()):
        row = await self.fetchone(sql, params)
        return None if row is None else row[0]

    # ---------- Клиенты ----------

    async def upsert_user(self, user_id: int, username: Optional[str], full_name: str) -> None:
        await self.execute(
            """
            INSERT INTO users (id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                          full_name = excluded.full_name
            """,
            (user_id, username, full_name, utc_now()),
        )

    async def get_user(self, user_id: int):
        return await self.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    async def list_users(self, limit: int = 20):
        return await self.fetchall(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) AS orders_count
            FROM users u
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    # ---------- Категории (страны) ----------

    async def list_categories(self, size: int = 12, page: int = 0):
        return await self.fetchall(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM products p
                     WHERE p.category_id = c.id AND p.active = 1) AS products,
                   (SELECT MIN(p.price) FROM products p
                     WHERE p.category_id = c.id AND p.active = 1) AS min_price,
                   (SELECT COUNT(*) FROM stock s
                      JOIN products p ON p.id = s.product_id
                     WHERE p.category_id = c.id AND p.active = 1
                       AND s.order_id IS NULL) AS stock
            FROM categories c
            ORDER BY c.id
            LIMIT ? OFFSET ?
            """,
            (size, max(page, 0) * size),
        )

    async def count_categories(self) -> int:
        return int(await self.scalar("SELECT COUNT(*) FROM categories") or 0)

    async def get_category(self, category_id: int):
        return await self.fetchone(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM products p
                     WHERE p.category_id = c.id AND p.active = 1) AS products,
                   (SELECT MIN(p.price) FROM products p
                     WHERE p.category_id = c.id AND p.active = 1) AS min_price,
                   (SELECT COUNT(*) FROM stock s
                      JOIN products p ON p.id = s.product_id
                     WHERE p.category_id = c.id AND p.active = 1
                       AND s.order_id IS NULL) AS stock
            FROM categories c
            WHERE c.id = ?
            """,
            (category_id,),
        )

    async def list_category_products(self, category_id: int, active_only: bool = True):
        where = "AND p.active = 1" if active_only else ""
        return await self.fetchall(
            f"""
            SELECT p.*, c.title AS category,
                   (SELECT COUNT(*) FROM stock s
                     WHERE s.product_id = p.id AND s.order_id IS NULL) AS stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.category_id = ? {where}
            ORDER BY p.id
            """,
            (category_id,),
        )

    # ---------- Товары и сток ----------

    async def list_products(
        self,
        active_only: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ):
        where = "WHERE p.active = 1" if active_only else ""
        limit_sql = "LIMIT ? OFFSET ?" if limit is not None else ""
        params: tuple = (limit, max(offset, 0)) if limit is not None else ()
        return await self.fetchall(
            f"""
            SELECT p.*, c.title AS category,
                   (SELECT COUNT(*) FROM stock s
                     WHERE s.product_id = p.id AND s.order_id IS NULL) AS stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            {where}
            ORDER BY p.id
            {limit_sql}
            """,
            params,
        )

    async def count_products(self, active_only: bool = True) -> int:
        where = "WHERE active = 1" if active_only else ""
        return int(await self.scalar(f"SELECT COUNT(*) FROM products {where}") or 0)

    async def get_product(self, product_id: int):
        return await self.fetchone(
            """
            SELECT p.*, c.title AS category,
                   (SELECT COUNT(*) FROM stock s
                     WHERE s.product_id = p.id AND s.order_id IS NULL) AS stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.id = ?
            """,
            (product_id,),
        )

    async def add_product(
        self, title: str, price: int, description: str, category_id: int | None = None
    ) -> int:
        if category_id is None:
            category_id = await self.scalar("SELECT id FROM categories ORDER BY id LIMIT 1")
        if category_id is None:
            cursor = await self.execute(
                "INSERT INTO categories (title) VALUES (?)", ("Виртуальные номера",)
            )
            category_id = cursor.lastrowid
        cursor = await self.execute(
            "INSERT INTO products (category_id, title, description, price) VALUES (?, ?, ?, ?)",
            (category_id, title, description, price),
        )
        return int(cursor.lastrowid)

    async def deactivate_product(self, product_id: int) -> None:
        await self.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
        await self.execute(
            "DELETE FROM stock WHERE product_id = ? AND order_id IS NULL", (product_id,)
        )

    async def add_stock(self, product_id: int, items: list[str]) -> int:
        assert self.conn is not None
        now = utc_now()
        await self.conn.executemany(
            "INSERT INTO stock (product_id, content, created_at) VALUES (?, ?, ?)",
            [(product_id, item, now) for item in items],
        )
        await self.conn.commit()
        return len(items)

    async def stock_count(self, product_id: int) -> int:
        return int(
            await self.scalar(
                "SELECT COUNT(*) FROM stock WHERE product_id = ? AND order_id IS NULL",
                (product_id,),
            )
            or 0
        )

    # ---------- Заказы ----------

    async def create_order(self, user_id: int, product_id: int, price: int) -> int:
        cursor = await self.execute(
            "INSERT INTO orders (user_id, product_id, price, created_at) VALUES (?, ?, ?, ?)",
            (user_id, product_id, price, utc_now()),
        )
        return int(cursor.lastrowid)

    async def get_order(self, order_id: int):
        return await self.fetchone(
            """
            SELECT o.*, p.title AS product_title, u.full_name, u.username
            FROM orders o
            JOIN products p ON p.id = o.product_id
            JOIN users u ON u.id = o.user_id
            WHERE o.id = ?
            """,
            (order_id,),
        )

    async def get_open_order(self, user_id: int, product_id: int):
        return await self.fetchone(
            """
            SELECT * FROM orders
            WHERE user_id = ? AND product_id = ? AND status = 'new'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, product_id),
        )

    async def list_user_orders(self, user_id: int, limit: int = 10):
        return await self.fetchall(
            """
            SELECT o.*, p.title AS product_title
            FROM orders o
            JOIN products p ON p.id = o.product_id
            WHERE o.user_id = ?
            ORDER BY o.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

    async def list_orders(self, limit: int = 15):
        return await self.fetchall(
            """
            SELECT o.*, p.title AS product_title, u.full_name, u.username
            FROM orders o
            JOIN products p ON p.id = o.product_id
            JOIN users u ON u.id = o.user_id
            ORDER BY o.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def mark_paid(self, order_id: int) -> None:
        await self.execute(
            "UPDATE orders SET status = 'paid', paid_at = ? WHERE id = ? AND status = 'new'",
            (utc_now(), order_id),
        )

    async def set_order_status(self, order_id: int, status: str) -> None:
        await self.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))

    async def deliver_order(self, order_id: int):
        """Выдаёт первый свободный товар. Возвращает (заказ, позиция) или (None, None)."""
        order = await self.get_order(order_id)
        if order is None or order["status"] in ("delivered", "cancelled"):
            return None, None

        item = await self.fetchone(
            """
            SELECT * FROM stock
            WHERE product_id = ? AND order_id IS NULL
            ORDER BY id LIMIT 1
            """,
            (order["product_id"],),
        )
        if item is None:
            return None, None

        now = utc_now()
        await self.execute("UPDATE stock SET order_id = ? WHERE id = ?", (order_id, item["id"]))
        await self.execute(
            """
            UPDATE orders
            SET status = 'delivered', stock_id = ?,
                paid_at = COALESCE(paid_at, ?), delivered_at = ?
            WHERE id = ?
            """,
            (item["id"], now, now, order_id),
        )
        return await self.get_order(order_id), item

    # ---------- Поддержка ----------

    async def get_open_ticket(self, user_id: int):
        return await self.fetchone(
            "SELECT * FROM tickets WHERE user_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )

    async def create_ticket(self, user_id: int) -> int:
        now = utc_now()
        cursor = await self.execute(
            "INSERT INTO tickets (user_id, created_at, updated_at) VALUES (?, ?, ?)",
            (user_id, now, now),
        )
        return int(cursor.lastrowid)

    async def get_or_create_open_ticket(self, user_id: int):
        ticket = await self.get_open_ticket(user_id)
        if ticket:
            return ticket
        ticket_id = await self.create_ticket(user_id)
        return await self.get_ticket(ticket_id)

    async def get_ticket(self, ticket_id: int):
        return await self.fetchone(
            """
            SELECT t.*, u.full_name, u.username
            FROM tickets t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ?
            """,
            (ticket_id,),
        )

    async def add_ticket_message(self, ticket_id: int, sender: str, text: str) -> None:
        now = utc_now()
        await self.execute(
            "INSERT INTO ticket_messages (ticket_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, sender, text, now),
        )
        await self.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id))

    async def list_ticket_messages(self, ticket_id: int, limit: int = 10):
        return await self.fetchall(
            """
            SELECT * FROM (
                SELECT * FROM ticket_messages
                WHERE ticket_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id
            """,
            (ticket_id, limit),
        )

    async def list_open_tickets(self, limit: int = 15):
        return await self.fetchall(
            """
            SELECT t.*, u.full_name, u.username,
                   (SELECT m.text FROM ticket_messages m
                     WHERE m.ticket_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_text
            FROM tickets t
            JOIN users u ON u.id = t.user_id
            WHERE t.status = 'open'
            ORDER BY t.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    async def close_ticket(self, ticket_id: int) -> None:
        await self.execute(
            "UPDATE tickets SET status = 'closed', updated_at = ? WHERE id = ?",
            (utc_now(), ticket_id),
        )

    # ---------- Статистика ----------

    async def stats(self) -> dict:
        return {
            "users": int(await self.scalar("SELECT COUNT(*) FROM users") or 0),
            "orders": int(await self.scalar("SELECT COUNT(*) FROM orders") or 0),
            "delivered": int(
                await self.scalar("SELECT COUNT(*) FROM orders WHERE status = 'delivered'") or 0
            ),
            "revenue": int(
                await self.scalar(
                    "SELECT COALESCE(SUM(price), 0) FROM orders WHERE status = 'delivered'"
                )
                or 0
            ),
            "open_tickets": int(
                await self.scalar("SELECT COUNT(*) FROM tickets WHERE status = 'open'") or 0
            ),
        }
