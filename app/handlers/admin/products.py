"""Админ: товары, сток и добавление позиций."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.constants import (
    ADMIN_CATEGORIES_PAGE_SIZE,
    ADMIN_PRODUCTS_PAGE_SIZE,
    ADMIN_LISTS_LIMIT,
)
from app.context import AppContext
from app.handlers.utils import paginate
from app.states import AddProduct, AddStock
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

logger = logging.getLogger(__name__)
router = Router(name="admin_products")


# ---------------------------------------------------------------------------
# Добавление товара
# ---------------------------------------------------------------------------


@router.message(Command("addproduct"))
async def cmd_addproduct(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    total = await ctx.db.categories.count()
    if not total:
        await ctx.banners.show(
            message,
            "admin",
            "Сначала создай категорию — каталог пуст. Обратись к разработчику.",
        )
        return

    pages, page, offset = paginate(total, ADMIN_CATEGORIES_PAGE_SIZE, 0)
    categories = await ctx.db.categories.list_page(
        ADMIN_CATEGORIES_PAGE_SIZE, offset
    )
    await state.set_state(AddProduct.category)
    await ctx.banners.show(
        message,
        "admin",
        texts.addproduct_categories_text(page, pages),
        keyboards.kb_addproduct_categories(categories, page, pages),
    )


@router.callback_query(AddProduct.category, F.data.startswith("apc:"))
async def addproduct_category_page(
    callback: CallbackQuery, ctx: AppContext
) -> None:
    total = await ctx.db.categories.count()
    pages, page, offset = paginate(total, ADMIN_CATEGORIES_PAGE_SIZE, tail_int(callback.data) or 0)
    categories = await ctx.db.categories.list_page(
        ADMIN_CATEGORIES_PAGE_SIZE, offset
    )
    await ctx.banners.show(
        callback,
        "admin",
        texts.addproduct_categories_text(page, pages),
        keyboards.kb_addproduct_categories(categories, page, pages),
    )
    await callback.answer()


@router.callback_query(AddProduct.category, F.data.startswith("apcat:"))
async def addproduct_category_pick(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    category = await ctx.db.categories.get(tail_int(callback.data) or 0)
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.update_data(
        category_id=category.id, category_title=category.title
    )
    await state.set_state(AddProduct.title)
    await ctx.banners.show(
        callback,
        "admin",
        f"📦 Новый товар\nКатегория: {category.title}\n\n"
        "Отправь название товара.\n/cancel — отмена.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data == "apcancel")
async def addproduct_cancel(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        callback, "admin", "Добавление товара отменено.", keyboards.kb_admin_panel()
    )
    await callback.answer()


@router.message(AddProduct.title, F.text)
async def addproduct_title(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    title = message.text.strip()
    if len(title) < 2 or len(title) > 100:
        await ctx.banners.show(
            message,
            "admin",
            "Название должно быть от 2 до 100 символов. Попробуй ещё раз.",
        )
        return

    await state.update_data(title=title)
    await state.set_state(AddProduct.price)
    data = await state.get_data()
    await ctx.banners.show(
        message,
        "admin",
        f"Категория: {data.get('category_title', '—')}\n"
        f"Укажи цену в {ctx.settings.currency} (только число):",
    )


@router.message(AddProduct.price, F.text)
async def addproduct_price(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    digits = re.sub(r"[^\d]", "", message.text)
    if not digits or int(digits) <= 0 or int(digits) > 10_000_000:
        await ctx.banners.show(
            message, "admin", "Нужна цена числом больше нуля. Например: 149"
        )
        return

    await state.update_data(price=int(digits))
    await state.set_state(AddProduct.description)
    await ctx.banners.show(
        message,
        "admin",
        "Отправь описание товара (или «-», чтобы оставить пустым):",
    )


@router.message(AddProduct.description, F.text)
async def addproduct_description(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    description = "" if message.text.strip() == "-" else message.text.strip()
    if len(description) > 1000:
        await ctx.banners.show(
            message, "admin", "Описание слишком длинное (максимум 1000 символов)."
        )
        return

    data = await state.get_data()
    product_id = await ctx.db.products.create(
        data["title"],
        data["price"],
        description,
        category_id=data.get("category_id"),
    )
    await state.clear()
    await ctx.banners.show(
        message,
        "admin",
        f"✅ Товар #{product_id} добавлен.\n"
        f"Категория: {data.get('category_title', '—')}\n"
        f"Теперь добавь сток: /addstock {product_id}\n"
        "Или через /admin → 📦 Товары.",
    )


@router.message(
    StateFilter(
        AddProduct.category,
        AddProduct.title,
        AddProduct.price,
        AddProduct.description,
    ),
    ~F.text,
)
async def addproduct_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "admin", "Отправь ответ текстом, пожалуйста."
    )


# ---------------------------------------------------------------------------
# Сток
# ---------------------------------------------------------------------------


@router.message(Command("addstock"))
async def cmd_addstock(
    message: Message, command: CommandObject, state: FSMContext, ctx: AppContext
) -> None:
    parts = (command.args or "").split()
    if not parts or not parts[0].isdigit():
        total = await ctx.db.products.count()
        products = await ctx.db.products.list(limit=20)
        lines = "\n".join(
            f"#{product.id} · {product.title} · {product.stock} шт."
            for product in products
        )
        await ctx.banners.show(
            message,
            "admin",
            "Использование: /addstock <ID товара>\n\n"
            f"Товары (первые 20 из {total}, полностью — /admin → 📦 Товары):\n"
            f"{lines or 'пока нет товаров'}",
        )
        return

    product_id = int(parts[0])
    product = await ctx.db.products.get(product_id)
    if product is None:
        await ctx.banners.show(
            message, "admin", "Товар с таким ID не найден."
        )
        return

    await state.set_state(AddStock.content)
    await state.update_data(product_id=product_id)
    await ctx.banners.show(
        message,
        "admin",
        f"📦 Товар #{product_id} · {product.title}\n\n"
        "Отправь позиции для стока: каждая строка — отдельный товар.\n"
        "Например:\n+1 555 000-00-01 | код 1234\n+1 555 000-00-02 | код 5678\n\n"
        "/cancel — отмена.",
    )


@router.message(AddStock.content, F.text)
async def addstock_content(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not lines:
        await ctx.banners.show(
            message, "admin", "Нужна хотя бы одна строка. Попробуй ещё раз."
        )
        return

    data = await state.get_data()
    product_id = data.get("product_id")
    product = await ctx.db.products.get(product_id) if product_id else None
    if product is None:
        await state.clear()
        await ctx.banners.show(
            message, "admin", "Товар не найден. Начни заново: /addstock <ID>."
        )
        return

    count = await ctx.db.products.add_stock(product_id, lines)
    await state.clear()
    await ctx.banners.show(
        message,
        "admin",
        f"✅ Добавлено позиций: {count}.\n"
        f"Теперь в наличии: {await ctx.db.products.stock_count(product_id)} шт.\n"
        f"Товар: #{product_id} · {product.title}",
    )


@router.message(AddStock.content, ~F.text)
async def addstock_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "admin", "Отправь позиции текстом, пожалуйста."
    )


@router.message(Command("stock"))
async def cmd_stock(message: Message, ctx: AppContext) -> None:
    total = await ctx.db.products.count()
    products = await ctx.db.products.list(limit=30)
    if not products:
        await ctx.banners.show(
            message, "admin", "Товаров пока нет. Добавь: /addproduct"
        )
        return

    lines = [
        f"#{product.id} · {product.title} · "
        f"{texts.money(ctx.settings, product.price)} · {product.stock} шт."
        for product in products
    ]
    await ctx.banners.show(
        message,
        "admin",
        f"📦 Товары и остатки (первые 30 из {total}):\n\n" + "\n".join(lines),
    )


@router.message(Command("delproduct"))
async def cmd_delproduct(
    message: Message, command: CommandObject, ctx: AppContext
) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await ctx.banners.show(
            message, "admin", "Использование: /delproduct <ID товара>"
        )
        return

    product_id = int(args)
    product = await ctx.db.products.get(product_id)
    if product is None or not product.active:
        await ctx.banners.show(
            message, "admin", "Активный товар с таким ID не найден."
        )
        return

    await ctx.db.products.deactivate(product_id)
    await ctx.banners.show(
        message,
        "admin",
        f"🗑 Товар #{product_id} · {product.title} удалён из каталога.\n"
        "Старые заказы сохранятся.",
    )


# ---------------------------------------------------------------------------
# Товары в админ-панели
# ---------------------------------------------------------------------------


async def _show_admin_products(
    callback: CallbackQuery, ctx: AppContext, page: int = 0
) -> None:
    total = await ctx.db.products.count()
    if not total:
        await ctx.banners.show(
            callback,
            "admin",
            "📦 Товаров пока нет.\nДобавь командой /addproduct.",
            keyboards.kb_admin_panel(),
        )
        return

    pages, page, offset = paginate(total, ADMIN_PRODUCTS_PAGE_SIZE, page)
    products = await ctx.db.products.list(
        limit=ADMIN_PRODUCTS_PAGE_SIZE, offset=offset
    )
    await ctx.banners.show(
        callback,
        "admin",
        f"📦 Товары\nСтраница {page + 1} из {pages} · всего {total}\n"
        "Выбери товар:",
        keyboards.kb_admin_products(ctx.settings, products, page, pages),
    )


@router.callback_query(F.data == "adm:products")
async def cb_admin_products(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await _show_admin_products(callback, ctx, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:products:"))
async def cb_admin_products_page(
    callback: CallbackQuery, ctx: AppContext
) -> None:
    await _show_admin_products(callback, ctx, tail_int(callback.data) or 0)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:product:"))
async def cb_admin_product(callback: CallbackQuery, ctx: AppContext) -> None:
    product = await ctx.db.products.get(tail_int(callback.data) or 0)
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await ctx.banners.show(
        callback,
        "admin",
        texts.product_admin_text(ctx.settings, product),
        keyboards.kb_admin_product(product),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:addstock:"))
async def cb_admin_addstock(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    product = await ctx.db.products.get(tail_int(callback.data) or 0)
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    await state.set_state(AddStock.content)
    await state.update_data(product_id=product.id)
    await ctx.banners.show(
        callback,
        "admin",
        f"📦 Сток для товара #{product.id} · {product.title}\n\n"
        "Отправь позиции: каждая строка — отдельный товар.\n"
        "Например:\n+1 555 000-00-01 | код 1234\n+1 555 000-00-02 | код 5678\n\n"
        "/cancel — отмена.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:delprod:"))
async def cb_admin_delprod(callback: CallbackQuery, ctx: AppContext) -> None:
    product = await ctx.db.products.get(tail_int(callback.data) or 0)
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    await ctx.db.products.deactivate(product.id)
    await ctx.banners.show(
        callback,
        "admin",
        f"🗑 Товар #{product.id} · {product.title} удалён из каталога.\n"
        "Старые заказы сохранятся.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer("Удалено.")
