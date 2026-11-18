"""Разбор callback_data.

Формат callback'ов не менялся с прошлой версии, чтобы старые кнопки
в истории чата продолжали работать после обновления бота.
"""

from __future__ import annotations

ORDER_PAYLOAD_PREFIX = "order:"


def tail_int(data: str | None) -> int | None:
    """Возвращает число из конца callback_data (`cat:12` → 12)."""
    if not data:
        return None
    tail = data.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def page_int(data: str | None) -> int | None:
    """Номер страницы из callback вида `catalog:2` или `adm:products:2`."""
    value = tail_int(data)
    return max(value, 0) if value is not None else None


def order_payload(order_id: int) -> str:
    return f"{ORDER_PAYLOAD_PREFIX}{order_id}"


def parse_order_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith(ORDER_PAYLOAD_PREFIX):
        return None
    tail = payload.split(":", 1)[1]
    return int(tail) if tail.isdigit() else None
