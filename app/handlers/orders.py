"""Заказы клиента и Telegram Payments."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from app.constants import USER_ORDERS_LIMIT
from app.context import AppContext
from app.handlers.utils import chat_id
from app.ui import keyboards, texts
from app.ui.callbacks import parse_order_payload, tail_int

logger = logging.getLogger(__name__)
router = Router(name="orders")


@router.callback_query(F.data == "myorders")
async def cb_my_orders(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    orders = await ctx.db.orders.list_for_user(
        callback.from_user.id, USER_ORDERS_LIMIT
    )
    if not orders:
        await ctx.banners.show(
            callback,
            "orders",
            "📦 У тебя пока нет заказов.\nЗагляни в каталог 👇",
            keyboards.kb_main(ctx.settings.is_admin(callback.from_user.id)),
        )
    else:
        await ctx.banners.show(
            callback,
            "orders",
            "📦 Твои последние заказы\nВыбери заказ, чтобы посмотреть детали:",
            keyboards.kb_my_orders(ctx.settings, orders),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("myord:"))
async def cb_my_order(callback: CallbackQuery, ctx: AppContext) -> None:
    order = await ctx.db.orders.get(tail_int(callback.data) or 0)
    if order is None or order.user_id != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    text = texts.user_order_text(ctx.settings, order)
    if order.status.value == "new":
        if ctx.payments.enabled:
            text += "\n\n💳 Нажми «Оплатить» — счёт придёт отдельным сообщением."
        else:
            text += f"\n\nОплата:\n{texts.payment_details(ctx.settings)}"
    if order.status.value == "delivered" and not order.sms_code:
        content = await ctx.db.products.stock_content(order.id)
        if content:
            text += f"\n\n🔑 Выданный товар:\n{content}"

    await ctx.banners.show(
        callback,
        "orders",
        text,
        keyboards.kb_my_order(order, ctx.payments.enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(callback: CallbackQuery, ctx: AppContext) -> None:
    order_id = tail_int(callback.data) or 0
    order = await ctx.db.orders.get(order_id)
    if order is None or order.user_id != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.status.value == "delivered":
        await callback.answer("Заказ уже выдан.", show_alert=True)
        return
    if order.status.value == "cancelled":
        await callback.answer("Заказ отменён.", show_alert=True)
        return
    if order.status.value == "paid":
        await callback.answer("Оплата уже отмечена, жди выдачи.", show_alert=True)
        return

    # Клиентское «Я оплатил» — только сигнал админу. Статус остаётся «new»,
    # пока оплату не подтвердит админ или Telegram Payments. Иначе номер
    # купился бы по непроверенному нажатию.
    order = await ctx.db.orders.get(order_id) or order
    await ctx.notifier.to_admins(
        f"💰 Клиент нажал «Я оплатил» по заказу #{order_id}\n"
        f"Клиент: {texts.display_order_user(order)}\n"
        f"Товар: {order.product_title}\n"
        f"Сумма: {texts.money(ctx.settings, order.price)}\n\n"
        "Проверь платёж, затем нажми «Отметить оплату» — бот купит номер.",
        reply_markup=keyboards.kb_order_notify(order_id),
        key="payment",
    )
    await callback.answer("Принято, проверяем оплату.")
    await ctx.banners.show(
        callback,
        "payment",
        "✅ Отметил, что ты оплатил. Оператор проверит платёж и выдаст "
        "товар — данные придут сюда.",
    )


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(callback: CallbackQuery, ctx: AppContext) -> None:
    order = await ctx.db.orders.get(tail_int(callback.data) or 0)
    if order is None or order.user_id != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.status.value == "delivered":
        await callback.answer("Заказ уже выдан.", show_alert=True)
        return
    if order.status.value == "cancelled":
        await callback.answer("Заказ отменён.", show_alert=True)
        return
    if order.status.value != "new":
        await callback.answer("Оплата уже получена, жди выдачи.", show_alert=True)
        return
    if not ctx.payments.enabled:
        await callback.answer(
            "Автооплата не подключена. Оплати по реквизитам из заказа.",
            show_alert=True,
        )
        return
    if not await ctx.orders.can_fulfill(order):
        await callback.answer(
            "Товар закончился. Напиши в поддержку — решим вопрос.",
            show_alert=True,
        )
        return

    sent = await ctx.payments.send_invoice(chat_id(callback), order)
    await callback.answer(
        "Счёт на оплату отправлен 👇"
        if sent
        else "Не удалось создать счёт. Напиши в поддержку.",
        show_alert=not sent,
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, ctx: AppContext) -> None:
    order_id = parse_order_payload(query.invoice_payload)
    order = await ctx.db.orders.get(order_id) if order_id is not None else None
    if order is None:
        await query.answer(
            ok=False, error_message="Заказ не найден. Создай новый в каталоге."
        )
        return
    if order.user_id != query.from_user.id:
        await query.answer(
            ok=False, error_message="Этот счёт выставлен другому пользователю."
        )
        return
    if order.status.value == "delivered":
        await query.answer(ok=False, error_message="Заказ уже выдан.")
        return
    if order.status.value == "cancelled":
        await query.answer(ok=False, error_message="Заказ отменён. Создай новый.")
        return
    if not await ctx.orders.can_fulfill(order):
        await query.answer(
            ok=False,
            error_message="Товар закончился. Напиши в поддержку — поможем.",
        )
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, ctx: AppContext) -> None:
    payment = message.successful_payment
    if payment is None:
        return
    order_id = parse_order_payload(payment.invoice_payload)
    if order_id is None:
        logger.warning("Оплата без привязки к заказу: %s", payment.invoice_payload)
        await ctx.banners.show(
            message,
            "payment",
            "✅ Оплата получена, но заказ не найден. Напиши в поддержку — разберёмся.",
        )
        return

    order = await ctx.db.orders.get(order_id)
    if order is None:
        logger.warning("Оплата по несуществующему заказу %s", order_id)
        await ctx.banners.show(
            message,
            "payment",
            "✅ Оплата получена, но заказ не найден. Напиши в поддержку — разберёмся.",
        )
        return
    if order.user_id != message.from_user.id:
        logger.warning(
            "Оплата заказа %s пришла не от владельца: %s",
            order_id,
            message.from_user.id,
        )
        return
    if order.status.value == "delivered":
        await ctx.banners.show(
            message,
            "orders",
            "✅ Оплата по этому заказу уже обработана, товар выдан.",
        )
        return
    if order.status.value == "cancelled":
        await ctx.notifier.to_admins(
            f"⚠️ Оплата по отменённому заказу #{order_id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Сумма: {texts.money(ctx.settings, order.price)}\n\n"
            "Нужно вернуть деньги или выдать товар вручную.",
            reply_markup=keyboards.kb_order_notify(order_id),
            key="payment",
        )
        await ctx.banners.show(
            message,
            "payment",
            "✅ Оплата получена, но заказ был отменён. Оператор свяжется с тобой.",
        )
        return

    if order.status.value == "new":
        await ctx.db.orders.mark_paid(order_id)
    order = await ctx.db.orders.get(order_id) or order

    if (
        payment.currency != ctx.settings.payment_currency
        or payment.total_amount != order.price * 100
    ):
        logger.warning(
            "Сумма оплаты заказа %s не совпала: %s %s вместо %s %s",
            order_id,
            payment.total_amount,
            payment.currency,
            order.price * 100,
            ctx.settings.payment_currency,
        )

    result = await ctx.orders.deliver(order_id)
    if result.ok and result.pending:
        await ctx.notifier.to_admins(
            f"💰 Автооплата по заказу #{order_id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Товар: {order.product_title}\n"
            f"Сумма: {texts.money(ctx.settings, order.price)}\n\n"
            "📡 Номер SMSFast куплен, жду SMS-код.",
            key="orders",
        )
        await ctx.banners.show(
            message,
            "payment",
            "✅ Оплата получена! Номер куплен — жди SMS, код придёт сюда автоматически.",
        )
    elif result.ok:
        await ctx.notifier.to_admins(
            f"💰 Автооплата по заказу #{order_id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Товар: {order.product_title}\n"
            f"Сумма: {texts.money(ctx.settings, order.price)}\n\n"
            "✅ Товар выдан автоматически.",
            key="orders",
        )
    else:
        await ctx.notifier.to_admins(
            f"⚠️ Заказ #{order_id} оплачен, но автовыдача не удалась.\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Товар: {order.product_title}\n"
            f"Сумма: {texts.money(ctx.settings, order.price)}\n"
            f"Причина: {result.message}\n\n"
            "Выдай товар вручную.",
            reply_markup=keyboards.kb_order_notify(order_id),
            key="orders",
        )
        await ctx.banners.show(
            message,
            "orders",
            "✅ Оплата получена! Не удалось выдать автоматически — оператор "
            "свяжется с тобой и решит вопрос.",
        )
