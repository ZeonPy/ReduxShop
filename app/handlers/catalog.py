"""Каталог: страны, товары и создание заказа."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.constants import CATALOG_PAGE_SIZE
from app.context import AppContext
from app.handlers.utils import chat_id, paginate
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

logger = logging.getLogger(__name__)
router = Router(name="catalog")


async def _show_catalog(
    event: Message | CallbackQuery, ctx: AppContext, page: int = 0
) -> None:
    total = await ctx.db.categories.count()
    if not total:
        await ctx.banners.show(
            event,
            "catalog",
            "🛍 Каталог пока пуст. Загляни позже.",
            keyboards.kb_main(
                ctx.settings.is_admin(getattr(event.from_user, "id", None))
            ),
        )
        return

    pages, page, offset = paginate(total, CATALOG_PAGE_SIZE, page)
    categories = await ctx.db.categories.list_page(CATALOG_PAGE_SIZE, offset)
    await ctx.banners.show(
        event,
        "catalog",
        texts.catalog_text(total, page, pages),
        keyboards.kb_catalog(ctx.settings, categories, page, pages),
    )


@router.message(Command("catalog"))
async def cmd_catalog(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await _show_catalog(message, ctx)


@router.callback_query(F.data == "catalog")
async def cb_catalog(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await _show_catalog(callback, ctx)
    await callback.answer()


@router.callback_query(F.data.startswith("catalog:"))
async def cb_catalog_page(callback: CallbackQuery, ctx: AppContext) -> None:
    total = await ctx.db.categories.count()
    if not total:
        await callback.answer("Каталог пуст.", show_alert=True)
        return
    await _show_catalog(callback, ctx, tail_int(callback.data) or 0)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: CallbackQuery, ctx: AppContext) -> None:
    category = await ctx.db.categories.get(tail_int(callback.data) or 0)
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    products = await ctx.db.categories.products(category.id)
    if products:
        text = (
            f"{category.title}\n\n"
            "Доступные виртуальные номера:\n"
            "Выбери товар, чтобы посмотреть описание и цену."
        )
    else:
        text = (
            f"{category.title}\n\n"
            "В этой стране пока нет товаров в наличии. Загляни позже."
        )
    await ctx.banners.show(
        callback, "country", text, keyboards.kb_category(ctx.settings, products)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:"))
async def cb_product(callback: CallbackQuery, ctx: AppContext) -> None:
    product = await ctx.db.products.get(tail_int(callback.data) or 0)
    if product is None or not product.active:
        await callback.answer("Товар больше недоступен.", show_alert=True)
        return

    stock_text = f"{product.stock} шт." if product.stock else "нет в наличии"
    text = (
        f"🛍 {product.title}\n\n"
        f"{product.description or 'Описание не указано.'}\n\n"
        f"💰 Цена: {texts.money(ctx.settings, product.price)}\n"
        f"📦 В наличии: {stock_text}"
    )
    await ctx.banners.show(
        callback, "product", text, keyboards.kb_product(product)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    product = await ctx.db.products.get(tail_int(callback.data) or 0)
    if product is None or not product.active:
        await callback.answer("Товар недоступен.", show_alert=True)
        return
    if product.stock <= 0:
        await callback.answer("Этого товара нет в наличии.", show_alert=True)
        return

    order, created = await ctx.orders.get_or_create(
        callback.from_user.id, product
    )
    if created:
        await ctx.notifier.to_admins(
            f"🆕 Новый заказ #{order.id}\n"
            f"Клиент: {texts.display_order_user(order)}\n"
            f"Товар: {order.product_title}\n"
            f"Сумма: {texts.money(ctx.settings, order.price)}",
            reply_markup=keyboards.kb_order_notify(order.id),
            key="orders",
        )

    if ctx.payments.enabled:
        sent = await ctx.payments.send_invoice(chat_id(callback), order)
        if sent:
            await ctx.banners.show(
                callback,
                "payment",
                texts.invoice_text(ctx.settings, order),
                keyboards.kb_payment(order.id, auto_payment=True),
            )
            await callback.answer("Счёт на оплату отправлен 👇")
            return
        logger.warning(
            "Автооплата включена, но счёт по заказу %s не ушёл — "
            "показываю ручную оплату.",
            order.id,
        )

    await ctx.banners.show(
        callback,
        "payment",
        texts.payment_text(ctx.settings, order),
        keyboards.kb_payment(order.id, auto_payment=False),
    )
    await callback.answer()
