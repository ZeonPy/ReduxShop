"""Оформление и выдача заказов."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram.enums import ParseMode

from app.constants import OrderStatus
from app.db import Database
from app.models import Order, Product
from app.services.fulfillment import FulfillmentService
from app.services.notifications import Notifier
from app.ui import texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    message: str
    pending: bool = False


class OrderService:
    def __init__(
        self,
        db: Database,
        notifier: Notifier,
        fulfillment: FulfillmentService | None = None,
    ) -> None:
        self._db = db
        self._notifier = notifier
        self._fulfillment = fulfillment

    async def get_or_create(self, user_id: int, product: Product) -> tuple[Order, bool]:
        """Возвращает открытый заказ или создаёт новый.

        Повторное нажатие «Купить» не плодит заказы: пока заказ не оплачен,
        клиент продолжает оплачивать тот же счёт.
        """
        existing = await self._db.orders.find_open(user_id, product.id)
        if existing is not None:
            full = await self._db.orders.get(existing.id)
            return (full or existing), False

        order_id = await self._db.orders.create(
            user_id, product.id, product.price, cost=product.cost
        )
        order = await self._db.orders.get(order_id)
        if order is None:
            raise RuntimeError(f"Заказ {order_id} не найден после создания")
        return order, True

    async def can_fulfill(self, order: Order) -> bool:
        if self._fulfillment is not None and await self._fulfillment.provider_available(
            order
        ):
            return True
        return await self._db.products.stock_count(order.product_id) > 0

    async def deliver(self, order_id: int) -> DeliveryResult:
        order = await self._db.orders.get(order_id)
        if order is None:
            return DeliveryResult(False, "Заказ не найден.")
        if order.status == OrderStatus.DELIVERED:
            return DeliveryResult(False, "Этот заказ уже выдан.")
        if order.status == OrderStatus.CANCELLED:
            return DeliveryResult(False, "Заказ отменён.")
        if order.status == OrderStatus.PROCESSING:
            return DeliveryResult(
                True, "Номер уже куплен, жду SMS. Код придёт автоматически.", pending=True
            )

        provider_note = ""
        if self._fulfillment is not None and await self._fulfillment.provider_available(
            order
        ):
            if order.status != OrderStatus.PAID:
                return DeliveryResult(
                    False,
                    "Сначала подтверди оплату: кнопка «Отметить оплату». "
                    "Номер покупается только после оплаты.",
                )
            start = await self._fulfillment.begin(order)
            if start.started:
                return DeliveryResult(True, start.message, pending=True)
            if not start.fallback:
                return DeliveryResult(False, start.message)
            provider_note = f"{start.message} "

        return await self._deliver_stock(order_id, provider_note)

    async def deliver_manual(self, order_id: int) -> DeliveryResult:
        """Ручная выдача отменённого заказа после сбоя SMSFast.

        Заказ уже оплачен, но активация не дала SMS. Админ может закрыть его
        позицией из стока: клиент получает товар, а неудачная активация
        остаётся в статистике доставляемости.
        """
        order = await self._db.orders.get(order_id)
        if order is None:
            return DeliveryResult(False, "Заказ не найден.")
        if order.status == OrderStatus.DELIVERED:
            return DeliveryResult(False, "Этот заказ уже выдан.")
        if order.status != OrderStatus.CANCELLED:
            return DeliveryResult(
                False, "Ручная выдача доступна только для отменённых заказов."
            )
        if not order.provider_id:
            return DeliveryResult(
                False,
                "Заказ отменён вручную. Выдача из стока доступна только "
                "после сбоя SMSFast.",
            )
        return await self._deliver_stock(order_id, allow_cancelled=True)

    async def _deliver_stock(
        self, order_id: int, note: str = "", *, allow_cancelled: bool = False
    ) -> DeliveryResult:
        delivered = await self._db.orders.deliver(
            order_id, allow_cancelled=allow_cancelled
        )
        if delivered is None:
            return DeliveryResult(
                False,
                note + "Нет свободного товара. Добавь сток: /addstock <ID>.",
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
                True,
                note + "Товар выдан, но клиент не получил сообщение (заблокировал бота?).",
            )
        return DeliveryResult(True, note + "Товар выдан, клиент получил данные.")
