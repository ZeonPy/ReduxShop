"""Типизированные модели данных.

Репозитории возвращают эти объекты вместо `sqlite3.Row`, чтобы хендлеры
и сервисы не зависели от имён колонок SQL и не падали на опечатках.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TypeVar

from app.constants import OrderStatus, TicketStatus

T = TypeVar("T")


def row_value(row: Mapping[str, Any], key: str, default: T | None = None) -> T | None:
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError):
        return default


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str | None
    full_name: str
    created_at: str
    orders_count: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "User":
        return cls(
            id=int(row["id"]),
            username=row_value(row, "username"),
            full_name=row_value(row, "full_name") or "",
            created_at=row_value(row, "created_at") or "",
            orders_count=int(row_value(row, "orders_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    title: str
    products: int = 0
    min_price: int | None = None
    stock: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Category":
        min_price = row_value(row, "min_price")
        return cls(
            id=int(row["id"]),
            title=str(row["title"]),
            products=int(row_value(row, "products") or 0),
            min_price=int(min_price) if min_price is not None else None,
            stock=int(row_value(row, "stock") or 0),
        )


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    category_id: int
    title: str
    description: str
    price: int
    active: bool
    category: str = ""
    stock: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Product":
        return cls(
            id=int(row["id"]),
            category_id=int(row["category_id"]),
            title=str(row["title"]),
            description=row_value(row, "description") or "",
            price=int(row["price"]),
            active=bool(row["active"]),
            category=row_value(row, "category") or "",
            stock=int(row_value(row, "stock") or 0),
        )


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    user_id: int
    product_id: int
    price: int
    status: OrderStatus
    created_at: str
    paid_at: str | None = None
    delivered_at: str | None = None
    stock_id: int | None = None
    product_title: str = ""
    full_name: str = ""
    username: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Order":
        raw_status = str(row["status"])
        try:
            status = OrderStatus(raw_status)
        except ValueError:
            status = OrderStatus.NEW
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            product_id=int(row["product_id"]),
            price=int(row["price"]),
            status=status,
            created_at=row_value(row, "created_at") or "",
            paid_at=row_value(row, "paid_at"),
            delivered_at=row_value(row, "delivered_at"),
            stock_id=row_value(row, "stock_id"),
            product_title=row_value(row, "product_title") or "",
            full_name=row_value(row, "full_name") or "",
            username=row_value(row, "username"),
        )


@dataclass(frozen=True, slots=True)
class Ticket:
    id: int
    user_id: int
    status: TicketStatus
    created_at: str
    updated_at: str
    full_name: str = ""
    username: str | None = None
    last_text: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Ticket":
        raw_status = str(row["status"])
        try:
            status = TicketStatus(raw_status)
        except ValueError:
            status = TicketStatus.OPEN
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            status=status,
            created_at=row_value(row, "created_at") or "",
            updated_at=row_value(row, "updated_at") or "",
            full_name=row_value(row, "full_name") or "",
            username=row_value(row, "username"),
            last_text=row_value(row, "last_text"),
        )


@dataclass(frozen=True, slots=True)
class TicketMessage:
    id: int
    ticket_id: int
    sender: str
    text: str
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "TicketMessage":
        return cls(
            id=int(row["id"]),
            ticket_id=int(row["ticket_id"]),
            sender=str(row["sender"]),
            text=str(row["text"]),
            created_at=row_value(row, "created_at") or "",
        )


@dataclass(frozen=True, slots=True)
class StockItem:
    id: int
    product_id: int
    content: str
    order_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "StockItem":
        return cls(
            id=int(row["id"]),
            product_id=int(row["product_id"]),
            content=str(row["content"]),
            order_id=row_value(row, "order_id"),
            created_at=row_value(row, "created_at") or "",
        )


@dataclass(frozen=True, slots=True)
class Stats:
    users: int
    orders: int
    delivered: int
    revenue: int
    open_tickets: int
