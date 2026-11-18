"""Telegram Payments: счёт на оплату, если задан provider token."""

from __future__ import annotations

import logging

from aiogram.types import LabeledPrice

from app.runtime import RuntimeConfig
from app.models import Order
from app.ui.callbacks import order_payload

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, bot, settings: RuntimeConfig) -> None:
        self._bot = bot
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.auto_payment_enabled

    async def send_invoice(self, chat_id: int, order: Order) -> bool:
        """Отправляет счёт. False — если не получилось, тогда ручная оплата."""
        if not self.enabled:
            return False
        if order.price <= 0:
            logger.error("Некорректная цена заказа %s: %s", order.id, order.price)
            return False

        title = (order.product_title or "Товар")[:32]
        description = (
            f"Заказ #{order.id} в {self._settings.shop_name}. "
            "Данные товара придут в этот чат автоматически после оплаты."
        )[:255]
        try:
            await self._bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=description,
                payload=order_payload(order.id),
                provider_token=self._settings.payment_provider_token,
                currency=self._settings.payment_currency,
                prices=[LabeledPrice(label=title, amount=order.price * 100)],
                protect_content=True,
            )
            return True
        except Exception as exc:
            logger.error("Не удалось отправить счёт по заказу %s: %s", order.id, exc)
            return False
