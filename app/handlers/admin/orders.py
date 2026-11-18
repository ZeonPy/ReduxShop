"""Админ: заказы, выдача, оплата и отмена."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.constants import ADMIN_LISTS_LIMIT, OrderStatus
from app.context import AppContext
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

router = Router(name="admin_orders")


@router.callback_query(F.data == "adm:orders")
async def cb_admin_orders(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    orders = await ctx.db.orders.list_recent(ADMIN_LISTS_LIMIT)
    if not orders:
        await ctx.banners.show(
            callback, "admin", "🧾 Заказов пока нет.", keyboards.kb_admin_panel()
        )
    else:
        await ctx.banners.show(
            callback,
            "admin",
            "🧾 Последние заказы\nВыбери заказ:",
            keyboards.kb_admin_orders(ctx.settings, orders),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:order:"))
async def cb_admin_order(callback: CallbackQuery, ctx: AppContext) -> None:
    order = await ctx.db.orders.get(tail_int(callback.data) or 0)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    await ctx.banners.show(
        callback,
        "admin",
        texts.admin_order_text(ctx.settings, order),
        keyboards.kb_admin_order(order),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:deliver:"))
async def cb_admin_deliver(callback: CallbackQuery, ctx: AppContext) -> None:
    order_id = tail_int(callback.data) or 0
    result = await ctx.orders.deliver(order_id)
    await callback.answer(result.message, show_alert=not result.ok)

    order = await ctx.db.orders.get(order_id)
    if order is not None:
        await ctx.banners.show(
            callback,
            "admin",
            texts.admin_order_text(ctx.settings, order),
            keyboards.kb_admin_order(order),
        )


@router.callback_query(F.data.startswith("adm:manual:"))
async def cb_admin_manual(callback: CallbackQuery, ctx: AppContext) -> None:
    """Ручная выдача отменённого заказа после сбоя SMSFast."""
    order_id = tail_int(callback.data) or 0
    result = await ctx.orders.deliver_manual(order_id)
    await callback.answer(result.message[:200], show_alert=not result.ok)

    order = await ctx.db.orders.get(order_id)
    if order is not None:
        await ctx.banners.show(
            callback,
            "admin",
            texts.admin_order_text(ctx.settings, order),
            keyboards.kb_admin_order(order),
        )


@router.callback_query(F.data.startswith("adm:markpaid:"))
async def cb_admin_markpaid(callback: CallbackQuery, ctx: AppContext) -> None:
    order_id = tail_int(callback.data) or 0
    order = await ctx.db.orders.get(order_id)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.status == OrderStatus.NEW:
        await ctx.db.orders.mark_paid(order_id)
    elif order.status != OrderStatus.PAID:
        await callback.answer(
            "Заказ уже не в статусе «ожидает оплаты».", show_alert=True
        )
        return

    result = await ctx.orders.deliver(order_id)
    order = await ctx.db.orders.get(order_id) or order
    await ctx.banners.show(
        callback,
        "admin",
        texts.admin_order_text(ctx.settings, order),
        keyboards.kb_admin_order(order),
    )
    await callback.answer(result.message[:200], show_alert=not result.ok)


@router.callback_query(F.data.startswith("adm:cancel:"))
async def cb_admin_cancel(callback: CallbackQuery, ctx: AppContext) -> None:
    order_id = tail_int(callback.data) or 0
    order = await ctx.db.orders.get(order_id)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.status == OrderStatus.DELIVERED:
        await callback.answer("Выданный заказ отменить нельзя.", show_alert=True)
        return
    if order.status == OrderStatus.CANCELLED:
        await callback.answer("Заказ уже отменён.", show_alert=True)
        return

    if order.status == OrderStatus.PROCESSING:
        await ctx.fulfillment.cancel(order)
    await ctx.db.orders.set_status(order_id, OrderStatus.CANCELLED)
    await ctx.notifier.to_user(
        order.user_id,
        f"❌ Заказ #{order_id} отменён.\n"
        "Если это ошибка — напиши в поддержку через бота.",
        key="orders",
    )
    order = await ctx.db.orders.get(order_id) or order
    await ctx.banners.show(
        callback,
        "admin",
        texts.admin_order_text(ctx.settings, order),
        keyboards.kb_admin_order(order),
    )
    await callback.answer("Заказ отменён.")
