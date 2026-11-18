"""Константы предметной области и пагинации."""

from __future__ import annotations

from enum import Enum

CATALOG_PAGE_SIZE = 12
ADMIN_PRODUCTS_PAGE_SIZE = 12
ADMIN_CATEGORIES_PAGE_SIZE = 20
ADMIN_LISTS_LIMIT = 15
USER_ORDERS_LIMIT = 10
TICKET_HISTORY_LIMIT = 10
TICKET_MESSAGE_PREVIEW = 300


class OrderStatus(str, Enum):
    NEW = "new"
    PAID = "paid"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class TicketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TicketSender(str, Enum):
    USER = "user"
    ADMIN = "admin"


STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.NEW: "🟡 ожидает оплаты",
    OrderStatus.PAID: "🟢 оплачен",
    OrderStatus.PROCESSING: "🔵 номер куплен, ждём SMS",
    OrderStatus.DELIVERED: "✅ выдан",
    OrderStatus.CANCELLED: "❌ отменён",
}

STATUS_EMOJI: dict[OrderStatus, str] = {
    OrderStatus.NEW: "🟡",
    OrderStatus.PAID: "🟢",
    OrderStatus.PROCESSING: "🔵",
    OrderStatus.DELIVERED: "✅",
    OrderStatus.CANCELLED: "❌",
}
