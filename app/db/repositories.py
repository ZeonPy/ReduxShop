"""Репозитории: весь SQL живёт здесь, сервисы и хендлеры его не видят."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.constants import OrderStatus, TicketSender, TicketStatus
from app.db.connection import Connection
from app.models import (
    Category,
    Order,
    Product,
    Stats,
    Ticket,
    TicketMessage,
    User,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class MetaRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def get(self, key: str, default: str | None = None) -> str | None:
        value = await self._conn.scalar("SELECT value FROM meta WHERE key = ?", (key,))
        return default if value is None else str(value)

    async def set(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )

    async def delete(self, key: str) -> None:
        await self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))


class SettingsRepository:
    """Настройки, изменённые администратором в панели."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def all(self) -> dict[str, str]:
        rows = await self._conn.fetchall("SELECT key, value FROM settings")
        return {str(row["key"]): str(row["value"]) for row in rows}

    async def get(self, key: str) -> str | None:
        value = await self._conn.scalar(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return None if value is None else str(value)

    async def set(self, key: str, value: str) -> None:
        await self._conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                          updated_at = excluded.updated_at
            """,
            (key, value, utc_now()),
        )

    async def delete(self, key: str) -> None:
        await self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))


class UserRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn
    async def upsert(self, user_id: int, username: str | None, full_name: str) -> None:
        await self._conn.execute(
            """
            INSERT INTO users (id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                          full_name = excluded.full_name
            """,
            (user_id, username, full_name, utc_now()),
        )

    async def get(self, user_id: int) -> User | None:
        row = await self._conn.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return User.from_row(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[User]:
        rows = await self._conn.fetchall(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) AS orders_count
            FROM users u
            ORDER BY u.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [User.from_row(row) for row in rows]

    async def orders_count(self, user_id: int) -> int:
        return int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,)
            )
            or 0
        )


class CategoryRepository:
    _CARD = """
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
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def list_page(self, limit: int, offset: int) -> list[Category]:
        rows = await self._conn.fetchall(
            f"{self._CARD} ORDER BY c.id LIMIT ? OFFSET ?",
            (limit, max(offset, 0)),
        )
        return [Category.from_row(row) for row in rows]

    async def list_all(self) -> list[Category]:
        rows = await self._conn.fetchall(f"{self._CARD} ORDER BY c.id")
        return [Category.from_row(row) for row in rows]

    async def count(self) -> int:
        return int(await self._conn.scalar("SELECT COUNT(*) FROM categories") or 0)

    async def create(self, title: str, provider_id: int | None = None) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO categories (title, provider_id) VALUES (?, ?)",
            (title, provider_id),
        )
        return int(cursor.lastrowid)

    async def set_provider_id(self, category_id: int, provider_id: int) -> int:
        cursor = await self._conn.execute(
            "UPDATE categories SET provider_id = ? WHERE id = ? AND "
            "(provider_id IS NULL OR provider_id != ?)",
            (provider_id, category_id, provider_id),
        )
        return cursor.rowcount or 0

    async def reset_demo(self) -> None:
        """Удаляет старую демо-категорию вместе с её товарами и стоком.

        Нужно только при первом запуске новой версии: в базе могла остаться
        одна тестовая категория «Виртуальные номера».
        """
        async with self._conn.transaction():
            await self._conn.execute("DELETE FROM stock WHERE order_id IS NULL")
            await self._conn.execute("DELETE FROM products")
            await self._conn.execute("DELETE FROM categories")

    async def get(self, category_id: int) -> Category | None:
        row = await self._conn.fetchone(f"{self._CARD} WHERE c.id = ?", (category_id,))
        return Category.from_row(row) if row else None

    async def products(
        self, category_id: int, active_only: bool = True
    ) -> list[Product]:
        where = "AND p.active = 1" if active_only else ""
        rows = await self._conn.fetchall(
            f"""
            SELECT p.*, c.title AS category, c.provider_id AS provider_id,
                   (SELECT COUNT(*) FROM stock s
                     WHERE s.product_id = p.id AND s.order_id IS NULL) AS stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.category_id = ? {where}
            ORDER BY p.id
            """,
            (category_id,),
        )
        return [Product.from_row(row) for row in rows]


class ProductRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def list(
        self,
        active_only: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Product]:
        where = "WHERE p.active = 1" if active_only else ""
        limit_sql = "LIMIT ? OFFSET ?" if limit is not None else ""
        params: tuple[Any, ...] = (limit, max(offset, 0)) if limit is not None else ()
        rows = await self._conn.fetchall(
            f"""
            SELECT p.*, c.title AS category, c.provider_id AS provider_id,
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
        return [Product.from_row(row) for row in rows]

    async def count(self, active_only: bool = True) -> int:
        where = "WHERE active = 1" if active_only else ""
        return int(
            await self._conn.scalar(f"SELECT COUNT(*) FROM products {where}") or 0
        )

    async def get(self, product_id: int) -> Product | None:
        row = await self._conn.fetchone(
            """
            SELECT p.*, c.title AS category, c.provider_id AS provider_id,
                   (SELECT COUNT(*) FROM stock s
                     WHERE s.product_id = p.id AND s.order_id IS NULL) AS stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.id = ?
            """,
            (product_id,),
        )
        return Product.from_row(row) if row else None

    async def create(
        self,
        title: str,
        price: int,
        description: str,
        category_id: int | None = None,
        cost: int = 0,
    ) -> int:
        if category_id is None:
            category_id = await self._conn.scalar(
                "SELECT id FROM categories ORDER BY id LIMIT 1"
            )
        if category_id is None:
            cursor = await self._conn.execute(
                "INSERT INTO categories (title) VALUES (?)", ("Виртуальные номера",)
            )
            category_id = int(cursor.lastrowid)
        cursor = await self._conn.execute(
            """
            INSERT INTO products (category_id, title, description, price, cost)
            VALUES (?, ?, ?, ?, ?)
            """,
            (category_id, title, description, price, cost),
        )
        return int(cursor.lastrowid)

    async def deactivate(self, product_id: int) -> None:
        await self._conn.execute(
            "UPDATE products SET active = 0 WHERE id = ?", (product_id,)
        )
        await self._conn.execute(
            "DELETE FROM stock WHERE product_id = ? AND order_id IS NULL",
            (product_id,),
        )

    async def add_stock(self, product_id: int, items: Iterable[str]) -> int:
        rows = [(product_id, item, utc_now()) for item in items]
        if not rows:
            return 0
        await self._conn.executemany(
            "INSERT INTO stock (product_id, content, created_at) VALUES (?, ?, ?)",
            rows,
        )
        return len(rows)

    async def stock_count(self, product_id: int) -> int:
        return int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM stock WHERE product_id = ? AND order_id IS NULL",
                (product_id,),
            )
            or 0
        )

    async def update_price_by_title(self, title: str, price: int) -> int:
        cursor = await self._conn.execute(
            "UPDATE products SET price = ? WHERE title = ?", (price, title)
        )
        return cursor.rowcount or 0

    async def update_country_product(
        self, product_id: int, price: int, cost: int
    ) -> int:
        cursor = await self._conn.execute(
            """
            UPDATE products SET price = ?, cost = ?
            WHERE id = ? AND (price != ? OR cost != ?)
            """,
            (price, cost, product_id, price, cost),
        )
        return cursor.rowcount or 0

    async def set_price_and_cost(self, product_id: int, price: int, cost: int) -> int:
        return await self.update_country_product(product_id, price, cost)

    async def stock_content(self, order_id: int) -> str | None:
        value = await self._conn.scalar(
            "SELECT content FROM stock WHERE order_id = ?", (order_id,)
        )
        return None if value is None else str(value)


class _Rollback(Exception):
    """Внутренний сигнал: транзакцию нужно откатить."""


class OrderRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    _SELECT = """
        SELECT o.*, p.title AS product_title, u.full_name, u.username
        FROM orders o
        JOIN products p ON p.id = o.product_id
        JOIN users u ON u.id = o.user_id
    """

    async def create(
        self, user_id: int, product_id: int, price: int, cost: int = 0
    ) -> int:
        cursor = await self._conn.execute(
            """
            INSERT INTO orders (user_id, product_id, price, cost, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, product_id, price, cost, utc_now()),
        )
        return int(cursor.lastrowid)

    async def get(self, order_id: int) -> Order | None:
        row = await self._conn.fetchone(f"{self._SELECT} WHERE o.id = ?", (order_id,))
        return Order.from_row(row) if row else None

    async def find_open(self, user_id: int, product_id: int) -> Order | None:
        row = await self._conn.fetchone(
            """
            SELECT * FROM orders
            WHERE user_id = ? AND product_id = ? AND status = 'new'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, product_id),
        )
        return Order.from_row(row) if row else None

    async def list_for_user(self, user_id: int, limit: int = 10) -> list[Order]:
        rows = await self._conn.fetchall(
            f"""
            SELECT o.*, p.title AS product_title
            FROM orders o
            JOIN products p ON p.id = o.product_id
            WHERE o.user_id = ?
            ORDER BY o.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [Order.from_row(row) for row in rows]

    async def list_recent(self, limit: int = 15) -> list[Order]:
        rows = await self._conn.fetchall(
            f"{self._SELECT} ORDER BY o.id DESC LIMIT ?", (limit,)
        )
        return [Order.from_row(row) for row in rows]

    async def count(self) -> int:
        return int(await self._conn.scalar("SELECT COUNT(*) FROM orders") or 0)

    async def mark_paid(self, order_id: int) -> bool:
        cursor = await self._conn.execute(
            """
            UPDATE orders SET status = 'paid', paid_at = ?, updated_at = ?
            WHERE id = ? AND status = 'new'
            """,
            (utc_now(), utc_now(), order_id),
        )
        return (cursor.rowcount or 0) > 0

    async def set_status(self, order_id: int, status: OrderStatus) -> None:
        await self._conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, utc_now(), order_id),
        )

    async def start_processing(self, order_id: int) -> bool:
        """Атомарно переводит оплаченный заказ в «покупаю номер»."""
        cursor = await self._conn.execute(
            """
            UPDATE orders SET status = 'processing', updated_at = ?
            WHERE id = ? AND status = 'paid'
            """,
            (utc_now(), order_id),
        )
        return (cursor.rowcount or 0) > 0

    async def set_provider_activation(
        self,
        order_id: int,
        *,
        provider: str,
        provider_id: str,
        phone: str,
        cost: int,
    ) -> None:
        await self._conn.execute(
            """
            UPDATE orders
            SET status = 'processing', provider = ?, provider_id = ?,
                provider_phone = ?, cost = ?, provider_error = '', updated_at = ?
            WHERE id = ?
            """,
            (provider, provider_id, phone, cost, utc_now(), order_id),
        )

    async def mark_provider_delivered(self, order_id: int, code: str) -> bool:
        cursor = await self._conn.execute(
            """
            UPDATE orders
            SET status = 'delivered', sms_code = ?, delivered_at = ?,
                provider_error = '', updated_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (code, utc_now(), utc_now(), order_id),
        )
        return (cursor.rowcount or 0) > 0

    async def fail_provider(self, order_id: int, error: str) -> bool:
        cursor = await self._conn.execute(
            """
            UPDATE orders
            SET status = 'cancelled', provider_error = ?, updated_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (error[:500], utc_now(), order_id),
        )
        return (cursor.rowcount or 0) > 0

    async def return_to_paid(self, order_id: int, error: str = "") -> bool:
        """Возврат в «оплачен», если номер ещё не был куплен."""
        cursor = await self._conn.execute(
            """
            UPDATE orders
            SET status = 'paid', provider_error = ?, updated_at = ?
            WHERE id = ? AND status = 'processing' AND COALESCE(provider_id, '') = ''
            """,
            (error[:500], utc_now(), order_id),
        )
        return (cursor.rowcount or 0) > 0

    async def set_provider_error(self, order_id: int, error: str) -> None:
        await self._conn.execute(
            "UPDATE orders SET provider_error = ?, updated_at = ? WHERE id = ?",
            (error[:500], utc_now(), order_id),
        )

    async def list_processing(self) -> list[Order]:
        rows = await self._conn.fetchall(
            f"{self._SELECT} WHERE o.status = 'processing' ORDER BY o.id"
        )
        return [Order.from_row(row) for row in rows]

    async def clear_provider(self, order_id: int) -> None:
        await self._conn.execute(
            """
            UPDATE orders
            SET provider = '', provider_id = '', provider_phone = '',
                sms_code = '', updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), order_id),
        )

    async def deliver(
        self, order_id: int, *, allow_cancelled: bool = False
    ) -> tuple[Order, str] | None:
        """Атомарно выдаёт позицию стока. None — если товара нет или гонка.

        `allow_cancelled` нужен для ручной выдачи после сбоя SMSFast: заказ
        отменён, но клиент оплатил, и админ закрывает его из стока. Активация
        провайдера при этом остаётся в истории, поэтому статистика
        доставляемости продолжает видеть неудачную попытку.
        """
        now = utc_now()
        statuses = (
            "'new', 'paid', 'cancelled'" if allow_cancelled else "'new', 'paid'"
        )
        reset = (
            ", provider_phone = '', sms_code = ''"
            if allow_cancelled
            else ", provider_error = ''"
        )
        try:
            async with self._conn.transaction():
                row = await self._conn.fetchone(
                    """
                    SELECT s.id, s.content
                    FROM stock s
                    JOIN orders o ON o.id = ?
                    WHERE s.product_id = o.product_id AND s.order_id IS NULL
                    ORDER BY s.id
                    LIMIT 1
                    """,
                    (order_id,),
                )
                if row is None:
                    raise _Rollback

                cursor = await self._conn.execute(
                    "UPDATE stock SET order_id = ? WHERE id = ? AND order_id IS NULL",
                    (order_id, row["id"]),
                )
                if (cursor.rowcount or 0) != 1:
                    raise _Rollback

                cursor = await self._conn.execute(
                    f"""
                    UPDATE orders
                    SET status = 'delivered', stock_id = ?,
                        paid_at = COALESCE(paid_at, ?), delivered_at = ?,
                        updated_at = ?{reset}
                    WHERE id = ? AND status IN ({statuses})
                    """,
                    (row["id"], now, now, now, order_id),
                )
                if (cursor.rowcount or 0) != 1:
                    raise _Rollback
                content = str(row["content"])
        except _Rollback:
            return None

        order = await self.get(order_id)
        if order is None:
            return None
        return order, content


class TicketRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def find_open(self, user_id: int) -> Ticket | None:
        row = await self._conn.fetchone(
            """
            SELECT * FROM tickets
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        return Ticket.from_row(row) if row else None

    async def create(self, user_id: int) -> int:
        now = utc_now()
        cursor = await self._conn.execute(
            "INSERT INTO tickets (user_id, created_at, updated_at) VALUES (?, ?, ?)",
            (user_id, now, now),
        )
        return int(cursor.lastrowid)

    async def get_or_create_open(self, user_id: int) -> Ticket:
        ticket = await self.find_open(user_id)
        if ticket is not None:
            return ticket
        ticket_id = await self.create(user_id)
        ticket = await self.get(ticket_id)
        if ticket is None:
            raise RuntimeError("Не удалось создать обращение")
        return ticket

    async def get(self, ticket_id: int) -> Ticket | None:
        row = await self._conn.fetchone(
            """
            SELECT t.*, u.full_name, u.username
            FROM tickets t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ?
            """,
            (ticket_id,),
        )
        return Ticket.from_row(row) if row else None

    async def add_message(self, ticket_id: int, sender: TicketSender, text: str) -> None:
        now = utc_now()
        await self._conn.execute(
            """
            INSERT INTO ticket_messages (ticket_id, sender, text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, sender.value, text, now),
        )
        await self._conn.execute(
            "UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id)
        )

    async def messages(self, ticket_id: int, limit: int = 10) -> list[TicketMessage]:
        rows = await self._conn.fetchall(
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
        return [TicketMessage.from_row(row) for row in rows]

    async def list_open(self, limit: int = 15) -> list[Ticket]:
        rows = await self._conn.fetchall(
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
        return [Ticket.from_row(row) for row in rows]

    async def close(self, ticket_id: int) -> bool:
        cursor = await self._conn.execute(
            """
            UPDATE tickets SET status = 'closed', updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (utc_now(), ticket_id),
        )
        return (cursor.rowcount or 0) > 0


class StatsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    async def summary(self) -> Stats:
        users = int(await self._conn.scalar("SELECT COUNT(*) FROM users") or 0)
        orders = int(await self._conn.scalar("SELECT COUNT(*) FROM orders") or 0)
        delivered = int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM orders WHERE status = 'delivered'"
            )
            or 0
        )
        revenue = int(
            await self._conn.scalar(
                "SELECT COALESCE(SUM(price), 0) FROM orders WHERE status = 'delivered'"
            )
            or 0
        )
        cost = int(
            await self._conn.scalar(
                "SELECT COALESCE(SUM(cost), 0) FROM orders WHERE status = 'delivered'"
            )
            or 0
        )
        paid = int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM orders WHERE status = 'paid'"
            )
            or 0
        )
        processing = int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM orders WHERE status = 'processing'"
            )
            or 0
        )
        cancelled = int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'"
            )
            or 0
        )
        open_tickets = int(
            await self._conn.scalar(
                "SELECT COUNT(*) FROM tickets WHERE status = 'open'"
            )
            or 0
        )
        provider_delivered, provider_failed = await self.provider_outcomes()
        provider_total = provider_delivered + provider_failed
        deliverability = (
            round(provider_delivered * 100 / provider_total)
            if provider_total
            else 0
        )
        profit = revenue - cost
        margin = round(profit * 100 / revenue) if revenue else 0
        return Stats(
            users=users,
            orders=orders,
            delivered=delivered,
            revenue=revenue,
            open_tickets=open_tickets,
            paid=paid,
            processing=processing,
            cancelled=cancelled,
            cost=cost,
            profit=profit,
            margin=margin,
            provider_delivered=provider_delivered,
            provider_failed=provider_failed,
            deliverability=deliverability,
        )

    async def provider_outcomes(self) -> tuple[int, int]:
        """Сколько активаций SMSFast завершилось кодом, а сколько сбоем.

        Ручная выдача после сбоя оставляет `provider` и `provider_id`, но без
        `sms_code`: для доставляемости это по-прежнему неудачная активация.
        """
        delivered = int(
            await self._conn.scalar(
                """
                SELECT COUNT(*) FROM orders
                WHERE status = 'delivered'
                  AND COALESCE(provider, '') != ''
                  AND COALESCE(sms_code, '') != ''
                """
            )
            or 0
        )
        failed = int(
            await self._conn.scalar(
                """
                SELECT COUNT(*) FROM orders
                WHERE COALESCE(provider, '') != ''
                  AND (
                    status = 'cancelled'
                    OR (status = 'delivered' AND COALESCE(sms_code, '') = '')
                  )
                """
            )
            or 0
        )
        return delivered, failed
