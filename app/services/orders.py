"""Оформление и выдача заказов."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram.enums import ParseMode

from app.constants import OrderStatus
from app.db import Database
from app.models import Order, Product
from app.services.notifications import Notifier
from app.ui import texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    message: str


class OrderService:
    def __init__(self, db: Database, notifier: Notifier) -> None:
        self._db = db
        self._notifier = notifier

    async def get_or_create(self, user_id: int, product: Product) -> tuple[Order, bool]:
        """Возвращает открытый заказ или создаёт новый.

        Повторное нажатие «Купить» не плодит заказы: пока заказ не оплачен,
        клиент продолжает оплачивать тот же счёт.
        """
        existing = await self._db.orders.find_open(user_id, product.id)
        if existing is not None:
            full = await self._db.orders.get(existing.id)
            return (full or existing), False

        order_id = await self._db.orders.create(user_id, product.id, product.price)
        order = await self._db.orders.get(order_id)
        if order is None:
            raise RuntimeError(f"Заказ {order_id} не найден после создания")
        return order, True

    async def deliver(self, order_id: int) -> DeliveryResult:
        order = await self._db.orders.get(order_id)
        if order is None:
            return DeliveryResult(False, "Заказ не найден.")
        if order.status == OrderStatus.DELIVERED:
            return DeliveryResult(False, "Этот заказ уже выдан.")
        if order.status == OrderStatus.CANCELLED:
            return DeliveryResult(False, "Заказ отменён.")

        delivered = await self._db.orders.deliver(order_id)
        if delivered is None:
            return DeliveryResult(
                False, "Нет свободного товара. Добавь сток: /addstock <ID>."
            )

        new_order, item = delivered
        sent = await self._notifier.to_user(
            new_order.user_id,
            texts.delivery_text(new_order, item),
            key="orders",
            parse_mode=ParseMode.HTML,
        )
        if not sent:
            logger.warning(
                "Заказ %s выдан, но сообщение клиенту %s не доставлено",
                order_id,
                new_order.user_id,
            )
            return DeliveryResult(
                True, "Товар выдан, но клиент не получил сообщение (заблокировал бота?)."
            )
        return DeliveryResult(True, "Товар выдан, клиент получил данные.")
