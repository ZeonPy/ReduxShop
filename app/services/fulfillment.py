"""Автовыдача через SMSFast: покупка номера, ожидание SMS и закрытие активации."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.constants import OrderStatus
from app.db import Database
from app.models import Order, Product
from app.runtime import RuntimeConfig
from app.services.notifications import Notifier
from app.services.smsfast import (
    PROVIDER_NAME,
    STATUS_CANCEL,
    STATUS_OK,
    STATUS_RETRY,
    SmsFastAuthError,
    SmsFastBalanceError,
    SmsFastClient,
    SmsFastError,
    SmsFastNoNumbersError,
)
from app.smsfast_countries import provider_country_id
from app.ui import keyboards, texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderStart:
    started: bool
    message: str
    fallback: bool = False


class FulfillmentService:
    """Живёт всё время работы бота и держит фоновые задачи ожидания SMS."""

    def __init__(
        self,
        db: Database,
        notifier: Notifier,
        settings: RuntimeConfig,
        client: SmsFastClient,
    ) -> None:
        self._db = db
        self._notifier = notifier
        self._settings = settings
        self._client = client
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def client(self) -> SmsFastClient:
        return self._client

    async def resolve_country(self, product: Product) -> int | None:
        if product.provider_id is not None:
            return product.provider_id
        name = product.title.split("·", 1)[-1].strip()
        return provider_country_id(name) or provider_country_id(product.category)

    async def provider_available(self, order: Order) -> bool:
        if not self._settings.smsfast_ready:
            return False
        product = await self._db.products.get(order.product_id)
        if product is None:
            return False
        return await self.resolve_country(product) is not None

    async def begin(self, order: Order) -> ProviderStart:
        """Покупает номер. Вызывать только после подтверждения оплаты."""
        if not self._settings.smsfast_ready:
            return ProviderStart(False, "SMSFast не настроен.", fallback=True)
        if order.status != OrderStatus.PAID:
            return ProviderStart(
                False,
                "Сначала отметь оплату — номер покупается только после неё.",
            )

        product = await self._db.products.get(order.product_id)
        if product is None:
            return ProviderStart(False, "Товар не найден.", fallback=True)
        country_id = await self.resolve_country(product)
        if country_id is None:
            return ProviderStart(
                False,
                "Для этой страны нет ID в SMSFast. Нажми «Синхронизировать».",
                fallback=True,
            )

        if not await self._db.orders.start_processing(order.id):
            current = await self._db.orders.get(order.id)
            if current is not None and current.status == OrderStatus.PROCESSING:
                return ProviderStart(True, "Номер уже покупается, ждём SMS.")
            return ProviderStart(False, "Заказ уже выдан или отменён.")

        try:
            activation = await self._client.get_number(
                self._settings.smsfast_service, country_id
            )
        except SmsFastNoNumbersError as exc:
            await self._db.orders.return_to_paid(order.id, str(exc))
            return ProviderStart(False, str(exc), fallback=True)
        except SmsFastBalanceError as exc:
            await self._db.orders.return_to_paid(order.id, str(exc))
            return ProviderStart(False, str(exc), fallback=True)
        except SmsFastAuthError as exc:
            await self._db.orders.return_to_paid(order.id, str(exc))
            return ProviderStart(False, str(exc), fallback=True)
        except SmsFastError as exc:
            await self._db.orders.return_to_paid(order.id, str(exc))
            return ProviderStart(False, str(exc), fallback=True)
        except Exception as exc:  # сеть/неожиданный ответ
            logger.exception("SMSFast: сбой покупки номера по заказу %s", order.id)
            await self._db.orders.return_to_paid(
                order.id, "Не удалось купить номер: временная ошибка."
            )
            return ProviderStart(False, f"Ошибка SMSFast: {exc}", fallback=True)

        cost = product.cost or 0
        await self._db.orders.set_provider_activation(
            order.id,
            provider=PROVIDER_NAME,
            provider_id=activation.activation_id,
            phone=activation.phone,
            cost=cost,
        )
        fresh = await self._db.orders.get(order.id) or order

        await self._notifier.to_user(
            fresh.user_id,
            texts.sms_wait_text(fresh, activation.phone),
            key="payment",
            parse_mode="HTML",
        )
        await self._notifier.to_admins(
            f"📡 SMSFast: куплен номер по заказу #{fresh.id}\n"
            f"Клиент: {texts.display_order_user(fresh)}\n"
            f"Страна: {fresh.product_title}\n"
            f"Номер: {activation.phone}\n"
            f"Активация: {activation.activation_id}\n"
            f"Закупка: {texts.money(self._settings, cost)}\n\n"
            "Жду SMS-код, закрою активацию автоматически.",
            key="orders",
        )

        self._spawn_poll(fresh.id, activation.activation_id, activation.phone)
        return ProviderStart(
            True,
            "Оплата подтверждена, номер куплен. Ждём SMS-код.",
        )

    async def resume_pending(self) -> int:
        """После рестарта продолжает ждать SMS по уже купленным номерам."""
        if not self._settings.smsfast_ready:
            return 0
        orders = await self._db.orders.list_processing()
        resumed = 0
        for order in orders:
            if not order.provider_id:
                # Упали между сменой статуса и покупкой номера — возвращаем оплату.
                await self._db.orders.return_to_paid(
                    order.id, "Перезапуск до покупки номера. Попробуй ещё раз."
                )
                continue
            self._spawn_poll(order.id, order.provider_id, order.provider_phone)
            resumed += 1
        if resumed:
            logger.info("SMSFast: восстановлено ожидание SMS по %s заказам", resumed)
        return resumed

    async def cancel(self, order: Order) -> None:
        if order.provider_id:
            try:
                await self._client.set_status(order.provider_id, 8)
            except Exception as exc:
                logger.warning(
                    "SMSFast: не удалось отменить активацию %s: %s",
                    order.provider_id,
                    exc,
                )
        if order.status == OrderStatus.PROCESSING:
            await self._db.orders.fail_provider(order.id, "Отменено администратором")

    def _spawn_poll(self, order_id: int, activation_id: str, phone: str) -> None:
        task = asyncio.create_task(
            self._poll(order_id, activation_id, phone),
            name=f"smsfast-order-{order_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _poll(self, order_id: int, activation_id: str, phone: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(60, self._settings.smsfast_timeout)
        interval = max(2, self._settings.smsfast_poll_interval)
        transient_errors = 0

        try:
            while loop.time() < deadline:
                await asyncio.sleep(interval)
                try:
                    status = await self._client.get_status(activation_id)
                    transient_errors = 0
                except SmsFastError as exc:
                    transient_errors += 1
                    logger.warning(
                        "SMSFast: getStatus %s не удался (%s/5): %s",
                        activation_id,
                        transient_errors,
                        exc,
                    )
                    if transient_errors >= 5:
                        break
                    continue

                if status.state == STATUS_OK and status.code:
                    await self._finish_ok(order_id, activation_id, phone, status.code)
                    return
                if status.state == STATUS_CANCEL:
                    await self._finish_failed(
                        order_id,
                        activation_id,
                        "SMSFast отменил активацию. Оплата будет возвращена.",
                    )
                    return
                if status.state == STATUS_RETRY and status.code:
                    logger.info(
                        "SMSFast: заказ %s получил повторный код, продолжаю ждать",
                        order_id,
                    )

            await self._finish_failed(
                order_id,
                activation_id,
                "Истекло время ожидания SMS. Напиши в поддержку — вернём оплату.",
                cancel_activation=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SMSFast: неожиданный сбой ожидания SMS заказа %s", order_id)
            await self._finish_failed(
                order_id,
                activation_id,
                "Сбой при ожидании SMS. Напиши в поддержку.",
            )

    async def _finish_ok(
        self, order_id: int, activation_id: str, phone: str, code: str
    ) -> None:
        try:
            await self._client.set_status(activation_id, 3)
        except Exception as exc:
            logger.warning(
                "SMSFast: не удалось закрыть активацию %s: %s", activation_id, exc
            )

        updated = await self._db.orders.mark_provider_delivered(order_id, code)
        order = await self._db.orders.get(order_id)
        if order is None:
            return
        if not updated:
            logger.info("SMSFast: заказ %s уже не в processing, код не сохраняю", order_id)
            return

        await self._notifier.to_user(
            order.user_id,
            texts.sms_delivery_text(order, phone, code),
            key="orders",
            parse_mode="HTML",
        )
        await self._notifier.to_admins(
            f"✅ SMSFast: SMS получен по заказу #{order.id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Номер: {phone}\n"
            f"Код: {code}\n"
            f"Закупка: {texts.money(self._settings, order.cost)}\n"
            f"Прибыль: {texts.money(self._settings, order.profit)}",
            key="orders",
        )

    async def _finish_failed(
        self,
        order_id: int,
        activation_id: str,
        reason: str,
        *,
        cancel_activation: bool = False,
    ) -> None:
        if cancel_activation:
            try:
                await self._client.set_status(activation_id, 8)
            except Exception as exc:
                logger.warning(
                    "SMSFast: не удалось отменить активацию %s: %s",
                    activation_id,
                    exc,
                )

        updated = await self._db.orders.fail_provider(order_id, reason)
        order = await self._db.orders.get(order_id)
        if order is None or not updated:
            return

        await self._notifier.to_user(
            order.user_id,
            texts.sms_failed_text(order, reason),
            key="payment",
        )
        await self._notifier.to_admins(
            f"⚠️ SMSFast: не удалось получить SMS по заказу #{order.id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Номер: {order.provider_phone}\n"
            f"Причина: {reason}\n\n"
            "Верни оплату или выдай товар вручную.",
            key="orders",
            reply_markup=keyboards.kb_order_failed(order.id),
        )
