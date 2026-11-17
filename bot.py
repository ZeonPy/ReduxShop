"""ReduxShop — Telegram-бот магазина виртуальных номеров.

Возможности:
  • каталог товаров и оформление заказа;
  • ручная выдача товара администратором (сток);
  • заявки «Я оплатил» и подтверждение оплаты;
  • автооплата через Telegram Payments (если задан PAYMENT_PROVIDER_TOKEN);
  • поддержка: клиент пишет боту, админ отвечает через бота;
  • админ-панель с заказами, обращениями, клиентами, товарами и статистикой.

Запуск: python bot.py  (токен и ADMIN_IDS — в .env)
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if not config.BOT_TOKEN or "ВСТАВЬ" in config.BOT_TOKEN.upper():
    raise SystemExit(
        "Не найден токен бота.\n"
        "Открой .env в папке reduxshop-bot и заполни строку BOT_TOKEN=..."
    )

bot = Bot(
    token=config.BOT_TOKEN,
    session=AiohttpSession(proxy=config.PROXY_URL) if config.PROXY_URL else None,
)
dp = Dispatcher()
dp.message.filter(F.chat.type == ChatType.PRIVATE)
db = Database(config.DB_PATH)

CATALOG_PAGE_SIZE = 12
ADMIN_PRODUCTS_PAGE_SIZE = 12
ADMIN_CATEGORIES_PAGE_SIZE = 20

STATUS_LABELS = {
    "new": "🟡 ожидает оплаты",
    "paid": "🟢 оплачен",
    "delivered": "✅ выдан",
    "cancelled": "❌ отменён",
}
STATUS_EMOJI = {
    "new": "🟡",
    "paid": "🟢",
    "delivered": "✅",
    "cancelled": "❌",
}


class SupportState(StatesGroup):
    message = State()


class AdminReply(StatesGroup):
    text = State()


class ClientMessage(StatesGroup):
    text = State()


class AddProduct(StatesGroup):
    category = State()
    title = State()
    price = State()
    description = State()


class AddStock(StatesGroup):
    content = State()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def money(value: int) -> str:
    return f"{value} {config.CURRENCY}"


def fmt_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def display_user(user) -> str:
    name = user["full_name"] or "Без имени"
    username = f" (@{user['username']})" if user["username"] else ""
    return f"{name}{username} · ID {user['id']}"


def display_order_user(order) -> str:
    name = order["full_name"] or "Без имени"
    username = f" (@{order['username']})" if order["username"] else ""
    return f"{name}{username} · ID {order['user_id']}"


def display_ticket_user(ticket) -> str:
    name = ticket["full_name"] or "Без имени"
    username = f" (@{ticket['username']})" if ticket["username"] else ""
    return f"{name}{username} · ID {ticket['user_id']}"


def payment_details() -> str:
    details = config.PAYMENT_DETAILS
    if not details or "УКАЖИ" in details.upper():
        return "Реквизиты уточни в поддержке — нажми «🆘 Поддержка»."
    return details


def auto_payment_enabled() -> bool:
    return bool(config.PAYMENT_PROVIDER_TOKEN)


def order_payload(order_id: int) -> str:
    return f"order:{order_id}"


def parse_order_payload(payload: str | None) -> int | None:
    if not payload or not payload.startswith("order:"):
        return None
    tail = payload.split(":", 1)[1]
    return int(tail) if tail.isdigit() else None


def cb_id(data: str) -> int:
    return int(data.split(":")[-1])


async def safe_edit(message: Message | None, text: str, reply_markup=None, parse_mode=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as exc:
        logging.debug("Не смог отредактировать сообщение: %s", exc)


async def notify_admins(text: str, reply_markup=None) -> None:
    if not config.ADMIN_IDS:
        logging.warning("ADMIN_IDS пуст: уведомление не отправлено. %s", text)
        return
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception as exc:
            logging.warning("Не смог написать админу %s: %s", admin_id, exc)


async def admin_callback(callback: CallbackQuery) -> bool:
    if is_admin(callback.from_user.id):
        return True
    await callback.answer("⛔ Нет доступа", show_alert=True)
    return False


async def require_admin(message: Message) -> bool:
    if message.from_user and is_admin(message.from_user.id):
        return True
    await message.answer("⛔ Эта команда доступна только администраторам.")
    return False


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------


def kb_main(admin: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛍 Каталог", callback_data="catalog")
    builder.button(text="📦 Мои заказы", callback_data="myorders")
    builder.button(text="🆘 Поддержка", callback_data="support")
    builder.button(text="ℹ️ О магазине", callback_data="about")
    if admin:
        builder.button(text="🛠 Админ-панель", callback_data="adm:panel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def kb_catalog(categories, page: int, pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        price = category["min_price"]
        tail = f"от {money(price)}" if price else "скоро"
        if category["stock"]:
            tail += f" · {category['stock']} шт."
        builder.button(
            text=f"{category['title']} · {tail}",
            callback_data=f"cat:{category['id']}",
        )
    builder.adjust(2)

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"catalog:{page - 1}")
        )
    if page + 1 < pages:
        nav.append(
            InlineKeyboardButton(text="Ещё ➡️", callback_data=f"catalog:{page + 1}")
        )
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🏠 В меню", callback_data="menu"))
    return builder.as_markup()


def kb_category(category, products) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        stock = product["stock"]
        tail = f"{stock} шт." if stock else "нет в наличии"
        builder.button(
            text=f"{product['title']} · {money(product['price'])} · {tail}",
            callback_data=f"prod:{product['id']}",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="⬅️ Все страны", callback_data="catalog"),
        InlineKeyboardButton(text="🏠 В меню", callback_data="menu"),
    )
    return builder.as_markup()


def kb_product(product) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if product["active"] and product["stock"] > 0:
        builder.button(text="🛒 Купить", callback_data=f"buy:{product['id']}")
    builder.button(
        text="⬅️ К стране", callback_data=f"cat:{product['category_id']}"
    )
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_payment(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if auto_payment_enabled():
        builder.button(text="💳 Оплатить", callback_data=f"pay:{order_id}")
    else:
        builder.button(text="✅ Я оплатил", callback_data=f"paid:{order_id}")
    builder.button(text="⬅️ Каталог", callback_data="catalog")
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_my_orders(orders) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=f"#{order['id']} · {STATUS_EMOJI.get(order['status'], '•')} · "
            f"{order['product_title']} · {money(order['price'])}",
            callback_data=f"myord:{order['id']}",
        )
    builder.button(text="⬅️ В меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_my_order(order) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order["status"] == "new":
        if auto_payment_enabled():
            builder.button(text="💳 Оплатить", callback_data=f"pay:{order['id']}")
        else:
            builder.button(text="✅ Я оплатил", callback_data=f"paid:{order['id']}")
    builder.button(text="⬅️ Мои заказы", callback_data="myorders")
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_support(ticket_id: int | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if ticket_id:
        builder.button(text="❌ Закрыть обращение", callback_data=f"tkt:userclose:{ticket_id}")
    builder.button(text="⬅️ В меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🧾 Заказы", callback_data="adm:orders")
    builder.button(text="🆘 Обращения", callback_data="adm:tickets")
    builder.button(text="👥 Клиенты", callback_data="adm:clients")
    builder.button(text="📦 Товары", callback_data="adm:products")
    builder.button(text="📊 Статистика", callback_data="adm:stats")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def kb_order_notify(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Выдать товар", callback_data=f"adm:deliver:{order_id}")
    builder.button(text="🧾 Открыть заказ", callback_data=f"adm:order:{order_id}")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_orders(orders) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=f"#{order['id']} · {STATUS_EMOJI.get(order['status'], '•')} · {money(order['price'])}",
            callback_data=f"adm:order:{order['id']}",
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_order(order) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order["status"] not in ("delivered", "cancelled"):
        builder.button(text="📤 Выдать товар", callback_data=f"adm:deliver:{order['id']}")
        if order["status"] == "new":
            builder.button(text="💰 Отметить оплату", callback_data=f"adm:markpaid:{order['id']}")
        builder.button(text="❌ Отменить", callback_data=f"adm:cancel:{order['id']}")
    builder.button(text="✉️ Написать клиенту", callback_data=f"adm:cmsg:{order['user_id']}")
    builder.button(text="⬅️ Заказы", callback_data="adm:orders")
    builder.adjust(2)
    return builder.as_markup()


def kb_ticket_notify(ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Ответить", callback_data=f"adm:treply:{ticket_id}")
    builder.button(text="🧾 Открыть", callback_data=f"adm:ticket:{ticket_id}")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_tickets(tickets) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        name = (ticket["full_name"] or "Клиент")[:24]
        builder.button(
            text=f"#{ticket['id']} · {name} · ID {ticket['user_id']}",
            callback_data=f"adm:ticket:{ticket['id']}",
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_ticket(ticket) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if ticket["status"] == "open":
        builder.button(text="✍️ Ответить", callback_data=f"adm:treply:{ticket['id']}")
        builder.button(text="✅ Закрыть", callback_data=f"adm:tclose:{ticket['id']}")
    builder.button(text="✉️ Написать клиенту", callback_data=f"adm:cmsg:{ticket['user_id']}")
    builder.button(text="⬅️ Обращения", callback_data="adm:tickets")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_clients(users) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        name = (user["full_name"] or "Без имени")[:26]
        builder.button(
            text=f"{name} · ID {user['id']} · заказов {user['orders_count']}",
            callback_data=f"adm:client:{user['id']}",
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_client(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ Написать сообщение", callback_data=f"adm:cmsg:{user_id}")
    builder.button(text="⬅️ Клиенты", callback_data="adm:clients")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_products(products, page: int = 0, pages: int = 1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        title = product["title"]
        if len(title) > 32:
            title = title[:31] + "…"
        builder.button(
            text=f"#{product['id']} · {title} · {money(product['price'])} · "
            f"{product['stock']} шт.",
            callback_data=f"adm:product:{product['id']}",
        )
    builder.adjust(1)

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"adm:products:{page - 1}"
            )
        )
    if page + 1 < pages:
        nav.append(
            InlineKeyboardButton(
                text="Ещё ➡️", callback_data=f"adm:products:{page + 1}"
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="⬅️ Панель", callback_data="adm:panel"))
    return builder.as_markup()


def kb_addproduct_categories(categories, page: int, pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=category["title"][:60], callback_data=f"apcat:{category['id']}"
        )
    builder.adjust(2)

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"apc:{page - 1}")
        )
    if page + 1 < pages:
        nav.append(
            InlineKeyboardButton(text="Ещё ➡️", callback_data=f"apc:{page + 1}")
        )
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="apcancel"))
    return builder.as_markup()


def kb_admin_product(product) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить сток", callback_data=f"adm:addstock:{product['id']}")
    if product["active"]:
        builder.button(text="🗑 Удалить товар", callback_data=f"adm:delprod:{product['id']}")
    builder.button(text="⬅️ Товары", callback_data="adm:products")
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Тексты
# ---------------------------------------------------------------------------


def payment_text(order) -> str:
    return (
        f"🧾 Заказ #{order['id']} создан.\n\n"
        f"Товар: {order['product_title']}\n"
        f"Сумма: {money(order['price'])}\n\n"
        f"Реквизиты для оплаты:\n{payment_details()}\n\n"
        "После оплаты нажми «✅ Я оплатил» — оператор проверит платёж и выдаст товар."
    )


def invoice_text(order) -> str:
    return (
        f"🧾 Заказ #{order['id']} создан.\n\n"
        f"Товар: {order['product_title']}\n"
        f"Сумма: {money(order['price'])}\n\n"
        "Счёт на оплату отправлен отдельным сообщением 👇\n"
        "После оплаты товар выдастся автоматически в этом чате.\n"
        "Потерял счёт — открой «📦 Мои заказы» и нажми «💳 Оплатить»."
    )


async def send_order_invoice(chat_id: int, order) -> bool:
    """Отправляет счёт Telegram Payments. False — если не получилось (тогда ручная оплата)."""
    if not auto_payment_enabled():
        return False
    if order["price"] <= 0:
        logging.error("Некорректная цена заказа %s: %s", order["id"], order["price"])
        return False

    title = (order["product_title"] or "Товар")[:32]
    description = (
        f"Заказ #{order['id']} в {config.SHOP_NAME}. "
        "Данные товара придут в этот чат автоматически после оплаты."
    )[:255]
    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=order_payload(order["id"]),
            provider_token=config.PAYMENT_PROVIDER_TOKEN,
            currency=config.PAYMENT_CURRENCY,
            prices=[LabeledPrice(label=title, amount=order["price"] * 100)],
            protect_content=True,
        )
        return True
    except Exception as exc:
        logging.error("Не удалось отправить счёт по заказу %s: %s", order["id"], exc)
        return False


def user_order_text(order) -> str:
    return (
        f"🧾 Заказ #{order['id']}\n"
        f"Товар: {order['product_title']}\n"
        f"Сумма: {money(order['price'])}\n"
        f"Статус: {status_label(order['status'])}\n"
        f"Создан: {fmt_dt(order['created_at'])}"
    )


def admin_order_text(order) -> str:
    return (
        f"🧾 Заказ #{order['id']}\n"
        f"Клиент: {display_order_user(order)}\n"
        f"Товар: {order['product_title']}\n"
        f"Сумма: {money(order['price'])}\n"
        f"Статус: {status_label(order['status'])}\n"
        f"Создан: {fmt_dt(order['created_at'])}\n"
        f"Оплачен: {fmt_dt(order['paid_at'])}\n"
        f"Выдан: {fmt_dt(order['delivered_at'])}"
    )


def product_admin_text(product) -> str:
    description = product["description"] or "—"
    active = "да" if product["active"] else "нет (удалён)"
    return (
        f"📦 Товар #{product['id']}\n"
        f"Категория: {product['category']}\n"
        f"Название: {product['title']}\n"
        f"Цена: {money(product['price'])}\n"
        f"В наличии: {product['stock']} шт.\n"
        f"Активен: {active}\n\n"
        f"Описание: {description}"
    )


# ---------------------------------------------------------------------------
# Пользовательские команды
# ---------------------------------------------------------------------------


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.full_name or "")
    await message.answer(
        f"👋 Добро пожаловать в {config.SHOP_NAME}!\n\n"
        "Здесь можно купить виртуальный номер для приёма SMS.\n"
        "Выбери раздел ниже 👇",
        reply_markup=kb_main(is_admin(user.id)),
    )


@dp.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    payment_help = (
        "«💳 Оплатить» — счёт Telegram, товар выдаётся автоматически."
        if auto_payment_enabled()
        else "«✅ Я оплатил» — сообщить об оплате по реквизитам."
    )
    await message.answer(
        f"ℹ️ {config.SHOP_NAME}\n\n"
        "🛍 Каталог — товары и цены\n"
        "📦 Мои заказы — статусы и выданные данные\n"
        "🆘 Поддержка — написать оператору\n"
        "ℹ️ О магазине — ссылка на канал\n\n"
        f"Команды: /start, /help, /paysupport, /id\n"
        f"Чтобы купить: Каталог → товар → «Купить» → {payment_help}",
        reply_markup=kb_main(is_admin(message.from_user.id)),
    )


@dp.message(Command("paysupport"))
async def cmd_paysupport(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "💳 Помощь по оплате и возвратам\n\n"
        "Если деньги списались, а товар не пришёл — напиши сюда одним сообщением:\n"
        "• номер заказа;\n"
        "• сумму и время оплаты.\n\n"
        "Оператор проверит платёж и поможет. Возврат по оплате в Telegram "
        "оформляется через поддержку магазина.\n\n"
        "Напиши сообщение следующим шагом 👇"
    )
    await state.set_state(SupportState.message)


def catalog_text(total: int, page: int, pages: int) -> str:
    return (
        "🛍 Каталог стран\n"
        "Выбери страну — покажу доступные виртуальные номера.\n\n"
        f"Страница {page + 1} из {pages} · всего {total} стран"
    )


@dp.message(Command("catalog"))
async def cmd_catalog(message: Message, state: FSMContext) -> None:
    await state.clear()
    total = await db.count_categories()
    if not total:
        await message.answer("🛍 Каталог пока пуст. Загляни позже.")
        return
    pages = max(1, (total + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    categories = await db.list_categories(CATALOG_PAGE_SIZE, 0)
    await message.answer(
        catalog_text(total, 0, pages),
        reply_markup=kb_catalog(categories, 0, pages),
    )


@dp.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Твой ID: {message.from_user.id}\nID чата: {message.chat.id}"
    )


@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return
    await state.clear()
    await message.answer("🛠 Админ-панель ReduxShop\nВыбери раздел:", reply_markup=kb_admin_panel())


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("Отменено. Панель: /admin", reply_markup=kb_admin_panel())
    else:
        await message.answer("Отменено.", reply_markup=kb_main(False))


# ---------------------------------------------------------------------------
# Callback-кнопки пользователя
# ---------------------------------------------------------------------------


@dp.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback.message,
        f"🏠 Главное меню {config.SHOP_NAME}\nВыбери раздел 👇",
        kb_main(is_admin(callback.from_user.id)),
    )
    await callback.answer()


@dp.callback_query(F.data == "catalog")
async def cb_catalog(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    total = await db.count_categories()
    if not total:
        await safe_edit(
            callback.message,
            "🛍 Каталог пока пуст. Загляни позже.",
            kb_main(is_admin(callback.from_user.id)),
        )
    else:
        pages = max(1, (total + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
        categories = await db.list_categories(CATALOG_PAGE_SIZE, 0)
        await safe_edit(
            callback.message,
            catalog_text(total, 0, pages),
            kb_catalog(categories, 0, pages),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("catalog:"))
async def cb_catalog_page(callback: CallbackQuery) -> None:
    total = await db.count_categories()
    if not total:
        await callback.answer("Каталог пуст.", show_alert=True)
        return
    pages = max(1, (total + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    page = min(max(cb_id(callback.data), 0), pages - 1)
    categories = await db.list_categories(CATALOG_PAGE_SIZE, page)
    await safe_edit(
        callback.message,
        catalog_text(total, page, pages),
        kb_catalog(categories, page, pages),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: CallbackQuery) -> None:
    category = await db.get_category(cb_id(callback.data))
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    products = await db.list_category_products(category["id"])
    if products:
        text = (
            f"{category['title']}\n\n"
            "Доступные виртуальные номера:\n"
            "Выбери товар, чтобы посмотреть описание и цену."
        )
    else:
        text = (
            f"{category['title']}\n\n"
            "В этой стране пока нет товаров в наличии. Загляни позже."
        )
    await safe_edit(callback.message, text, kb_category(category, products))
    await callback.answer()


@dp.callback_query(F.data.startswith("prod:"))
async def cb_product(callback: CallbackQuery) -> None:
    product = await db.get_product(cb_id(callback.data))
    if product is None or not product["active"]:
        await callback.answer("Товар больше недоступен.", show_alert=True)
        return
    stock_text = f"{product['stock']} шт." if product["stock"] else "нет в наличии"
    text = (
        f"🛍 {product['title']}\n\n"
        f"{product['description'] or 'Описание не указано.'}\n\n"
        f"💰 Цена: {money(product['price'])}\n"
        f"📦 В наличии: {stock_text}"
    )
    await safe_edit(callback.message, text, kb_product(product))
    await callback.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    product_id = cb_id(callback.data)
    product = await db.get_product(product_id)
    if product is None or not product["active"]:
        await callback.answer("Товар недоступен.", show_alert=True)
        return
    if product["stock"] <= 0:
        await callback.answer("Этого товара нет в наличии.", show_alert=True)
        return

    user = callback.from_user
    await db.upsert_user(user.id, user.username, user.full_name or "")

    open_order = await db.get_open_order(user.id, product_id)
    if open_order:
        order_id = open_order["id"]
    else:
        order_id = await db.create_order(user.id, product_id, product["price"])
        order = await db.get_order(order_id)
        await notify_admins(
            f"🆕 Новый заказ #{order_id}\n"
            f"Клиент: {display_order_user(order)}\n"
            f"Товар: {order['product_title']}\n"
            f"Сумма: {money(order['price'])}",
            reply_markup=kb_order_notify(order_id),
        )

    order = await db.get_order(order_id)
    if auto_payment_enabled():
        sent = await send_order_invoice(callback.message.chat.id, order)
        if sent:
            await safe_edit(callback.message, invoice_text(order), kb_payment(order_id))
            await callback.answer("Счёт на оплату отправлен 👇")
            return
        logging.warning(
            "Автооплата включена, но счёт по заказу %s не ушёл — показываю ручную оплату.",
            order_id,
        )
    await safe_edit(callback.message, payment_text(order), kb_payment(order_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("paid:"))
async def cb_paid(callback: CallbackQuery) -> None:
    order_id = cb_id(callback.data)
    order = await db.get_order(order_id)
    if order is None or order["user_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order["status"] == "delivered":
        await callback.answer("Заказ уже выдан.", show_alert=True)
        return
    if order["status"] == "cancelled":
        await callback.answer("Заказ отменён.", show_alert=True)
        return
    if order["status"] == "paid":
        await callback.answer("Оплата уже отмечена, жди выдачи.", show_alert=True)
        return

    await db.mark_paid(order_id)
    order = await db.get_order(order_id)
    await notify_admins(
        f"💰 Клиент отметил оплату по заказу #{order_id}\n"
        f"Клиент: {display_order_user(order)}\n"
        f"Товар: {order['product_title']}\n"
        f"Сумма: {money(order['price'])}\n\n"
        "Проверь платёж и выдай товар.",
        reply_markup=kb_order_notify(order_id),
    )
    await callback.answer("Принято, проверяем оплату.")
    await callback.message.answer(
        "✅ Отметил, что ты оплатил. Оператор проверит платёж и выдаст товар — "
        "данные придут сюда."
    )


@dp.callback_query(F.data.startswith("pay:"))
async def cb_pay(callback: CallbackQuery) -> None:
    order = await db.get_order(cb_id(callback.data))
    if order is None or order["user_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order["status"] == "delivered":
        await callback.answer("Заказ уже выдан.", show_alert=True)
        return
    if order["status"] == "cancelled":
        await callback.answer("Заказ отменён.", show_alert=True)
        return
    if order["status"] != "new":
        await callback.answer("Оплата уже получена, жди выдачи.", show_alert=True)
        return
    if not auto_payment_enabled():
        await callback.answer(
            "Автооплата не подключена. Оплати по реквизитам из заказа.",
            show_alert=True,
        )
        return
    if await db.stock_count(order["product_id"]) <= 0:
        await callback.answer(
            "Товар закончился. Напиши в поддержку — решим вопрос.",
            show_alert=True,
        )
        return
    sent = await send_order_invoice(callback.message.chat.id, order)
    await callback.answer(
        "Счёт на оплату отправлен 👇" if sent else "Не удалось создать счёт. Напиши в поддержку.",
        show_alert=not sent,
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    order_id = parse_order_payload(query.invoice_payload)
    order = await db.get_order(order_id) if order_id is not None else None
    if order is None:
        await query.answer(
            ok=False, error_message="Заказ не найден. Создай новый в каталоге."
        )
        return
    if order["user_id"] != query.from_user.id:
        await query.answer(
            ok=False, error_message="Этот счёт выставлен другому пользователю."
        )
        return
    if order["status"] == "delivered":
        await query.answer(ok=False, error_message="Заказ уже выдан.")
        return
    if order["status"] == "cancelled":
        await query.answer(ok=False, error_message="Заказ отменён. Создай новый.")
        return
    if await db.stock_count(order["product_id"]) <= 0:
        await query.answer(
            ok=False,
            error_message="Товар закончился. Напиши в поддержку — поможем.",
        )
        return
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    order_id = parse_order_payload(payment.invoice_payload)
    if order_id is None:
        logging.warning("Оплата без привязки к заказу: %s", payment.invoice_payload)
        await message.answer(
            "✅ Оплата получена, но заказ не найден. Напиши в поддержку — разберёмся."
        )
        return

    order = await db.get_order(order_id)
    if order is None:
        logging.warning("Оплата по несуществующему заказу %s", order_id)
        await message.answer(
            "✅ Оплата получена, но заказ не найден. Напиши в поддержку — разберёмся."
        )
        return
    if order["user_id"] != message.from_user.id:
        logging.warning(
            "Оплата заказа %s пришла не от владельца: %s",
            order_id,
            message.from_user.id,
        )
        return
    if order["status"] == "delivered":
        await message.answer("✅ Оплата по этому заказу уже обработана, товар выдан.")
        return
    if order["status"] == "cancelled":
        await notify_admins(
            f"⚠️ Оплата по отменённому заказу #{order_id}\n"
            f"Клиент: {display_order_user(order)}\n"
            f"Сумма: {money(order['price'])}\n\n"
            "Нужно вернуть деньги или выдать товар вручную.",
            reply_markup=kb_order_notify(order_id),
        )
        await message.answer(
            "✅ Оплата получена, но заказ был отменён. Оператор свяжется с тобой."
        )
        return

    if order["status"] == "new":
        await db.mark_paid(order_id)
    order = await db.get_order(order_id)

    if (
        payment.currency != config.PAYMENT_CURRENCY
        or payment.total_amount != order["price"] * 100
    ):
        logging.warning(
            "Сумма оплаты заказа %s не совпала: %s %s вместо %s %s",
            order_id,
            payment.total_amount,
            payment.currency,
            order["price"] * 100,
            config.PAYMENT_CURRENCY,
        )

    ok, detail = await perform_delivery(order_id)
    if ok:
        await notify_admins(
            f"💰 Автооплата по заказу #{order_id}\n"
            f"Клиент: {display_order_user(order)}\n"
            f"Товар: {order['product_title']}\n"
            f"Сумма: {money(order['price'])}\n\n"
            "✅ Товар выдан автоматически."
        )
    else:
        await notify_admins(
            f"⚠️ Заказ #{order_id} оплачен, но автовыдача не удалась.\n"
            f"Клиент: {display_order_user(order)}\n"
            f"Товар: {order['product_title']}\n"
            f"Сумма: {money(order['price'])}\n"
            f"Причина: {detail}\n\n"
            "Выдай товар вручную.",
            reply_markup=kb_order_notify(order_id),
        )
        await message.answer(
            "✅ Оплата получена! Товара не оказалось в наличии — оператор выдаст его "
            "вручную или свяжется с тобой."
        )


@dp.callback_query(F.data == "myorders")
async def cb_my_orders(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    orders = await db.list_user_orders(callback.from_user.id, 10)
    if not orders:
        await safe_edit(
            callback.message,
            "📦 У тебя пока нет заказов.\nЗагляни в каталог 👇",
            kb_main(is_admin(callback.from_user.id)),
        )
    else:
        await safe_edit(
            callback.message,
            "📦 Твои последние заказы\nВыбери заказ, чтобы посмотреть детали:",
            kb_my_orders(orders),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("myord:"))
async def cb_my_order(callback: CallbackQuery) -> None:
    order = await db.get_order(cb_id(callback.data))
    if order is None or order["user_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    text = user_order_text(order)
    if order["status"] == "new":
        if auto_payment_enabled():
            text += "\n\n💳 Нажми «Оплатить» — счёт придёт отдельным сообщением."
        else:
            text += f"\n\nОплата:\n{payment_details()}"
    if order["status"] == "delivered":
        stock = await db.fetchone("SELECT content FROM stock WHERE order_id = ?", (order["id"],))
        if stock:
            text += f"\n\n🔑 Выданный товар:\n{stock['content']}"

    await safe_edit(callback.message, text, kb_my_order(order))
    await callback.answer()


@dp.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback.message,
        f"ℹ️ {config.SHOP_NAME}\n\n"
        "Магазин виртуальных номеров для приёма SMS.\n"
        f"Наш канал: {config.SHOP_LINK}\n\n"
        "Заказ: Каталог → товар → «Купить». После оплаты оператор выдаёт номер в этом боте.\n"
        "Вопросы — через «🆘 Поддержка».",
        kb_main(is_admin(callback.from_user.id)),
    )
    await callback.answer()


@dp.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    ticket = await db.get_open_ticket(callback.from_user.id)
    await safe_edit(
        callback.message,
        "🆘 Поддержка ReduxShop\n\n"
        "Напиши сообщение одним текстом — я передам его оператору. "
        "Ответ придёт сюда же.\n\n"
        "Можно продолжать писать: сообщения добавятся в открытое обращение.",
        kb_support(ticket["id"] if ticket else None),
    )
    await state.set_state(SupportState.message)
    await callback.answer()


@dp.callback_query(F.data.startswith("tkt:userclose:"))
async def cb_ticket_user_close(callback: CallbackQuery, state: FSMContext) -> None:
    ticket = await db.get_ticket(cb_id(callback.data))
    if ticket is None or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    await state.clear()
    await db.close_ticket(ticket["id"])
    await notify_admins(f"✅ Клиент закрыл обращение #{ticket['id']}")
    await safe_edit(
        callback.message,
        "✅ Обращение закрыто. Если появится новый вопрос — снова нажми «🆘 Поддержка».",
        kb_main(is_admin(callback.from_user.id)),
    )
    await callback.answer("Обращение закрыто.")


# ---------------------------------------------------------------------------
# Поддержка: сообщения клиента
# ---------------------------------------------------------------------------


async def relay_user_message(message: Message, ticket_id: int) -> None:
    await db.add_ticket_message(ticket_id, "user", message.text)
    user = message.from_user
    await notify_admins(
        f"🆘 Обращение #{ticket_id}\n"
        f"Клиент: {user.full_name or 'Без имени'}"
        f"{f' (@{user.username})' if user.username else ''} · ID {user.id}\n\n"
        f"{message.text}",
        reply_markup=kb_ticket_notify(ticket_id),
    )


@dp.message(SupportState.message, F.text)
async def support_message(message: Message, state: FSMContext) -> None:
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.full_name or "")
    ticket = await db.get_or_create_open_ticket(user.id)
    await relay_user_message(message, ticket["id"])
    await message.answer(
        "✅ Передал оператору. Ответ придёт сюда.\n"
        "Можешь продолжать писать — сообщения добавятся в это обращение."
    )
    await state.clear()


@dp.message(SupportState.message)
async def support_non_text(message: Message) -> None:
    await message.answer("Отправь сообщение текстом, пожалуйста.")


# ---------------------------------------------------------------------------
# Админ-команды
# ---------------------------------------------------------------------------


def addproduct_categories_text(page: int, pages: int) -> str:
    return (
        "📦 Новый товар\n\n"
        "Выбери страну-категорию, в которую добавить товар.\n"
        f"Страница {page + 1} из {pages}"
    )


@dp.message(Command("addproduct"))
async def cmd_addproduct(message: Message, state: FSMContext) -> None:
    if not await require_admin(message):
        return
    total = await db.count_categories()
    if not total:
        await message.answer("Сначала создай категорию — каталог пуст. Обратись к разработчику.")
        return
    pages = max(1, (total + ADMIN_CATEGORIES_PAGE_SIZE - 1) // ADMIN_CATEGORIES_PAGE_SIZE)
    categories = await db.list_categories(ADMIN_CATEGORIES_PAGE_SIZE, 0)
    await state.set_state(AddProduct.category)
    await message.answer(
        addproduct_categories_text(0, pages),
        reply_markup=kb_addproduct_categories(categories, 0, pages),
    )


@dp.callback_query(AddProduct.category, F.data.startswith("apc:"))
async def addproduct_category_page(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    total = await db.count_categories()
    pages = max(1, (total + ADMIN_CATEGORIES_PAGE_SIZE - 1) // ADMIN_CATEGORIES_PAGE_SIZE)
    page = min(max(cb_id(callback.data), 0), pages - 1)
    categories = await db.list_categories(ADMIN_CATEGORIES_PAGE_SIZE, page)
    await safe_edit(
        callback.message,
        addproduct_categories_text(page, pages),
        kb_addproduct_categories(categories, page, pages),
    )
    await callback.answer()


@dp.callback_query(AddProduct.category, F.data.startswith("apcat:"))
async def addproduct_category_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    category = await db.get_category(cb_id(callback.data))
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    await state.update_data(
        category_id=category["id"], category_title=category["title"]
    )
    await state.set_state(AddProduct.title)
    await safe_edit(
        callback.message,
        f"📦 Новый товар\nКатегория: {category['title']}\n\n"
        "Отправь название товара.\n/cancel — отмена.",
    )
    await callback.answer()


@dp.callback_query(F.data == "apcancel")
async def addproduct_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    await safe_edit(callback.message, "Добавление товара отменено.", kb_admin_panel())
    await callback.answer()


@dp.message(AddProduct.title, F.text)
async def addproduct_title(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    title = message.text.strip()
    if len(title) < 2 or len(title) > 100:
        await message.answer("Название должно быть от 2 до 100 символов. Попробуй ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(AddProduct.price)
    data = await state.get_data()
    category_title = data.get("category_title", "—")
    await message.answer(
        f"Категория: {category_title}\n"
        f"Укажи цену в {config.CURRENCY} (только число):"
    )


@dp.message(AddProduct.price, F.text)
async def addproduct_price(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    digits = re.sub(r"[^\d]", "", message.text)
    if not digits or int(digits) <= 0 or int(digits) > 10_000_000:
        await message.answer("Нужна цена числом больше нуля. Например: 149")
        return
    await state.update_data(price=int(digits))
    await state.set_state(AddProduct.description)
    await message.answer(
        "Отправь описание товара (или «-», чтобы оставить пустым):"
    )


@dp.message(AddProduct.description, F.text)
async def addproduct_description(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    description = "" if message.text.strip() == "-" else message.text.strip()
    if len(description) > 1000:
        await message.answer("Описание слишком длинное (максимум 1000 символов).")
        return
    data = await state.get_data()
    product_id = await db.add_product(
        data["title"],
        data["price"],
        description,
        category_id=data.get("category_id"),
    )
    await state.clear()
    await message.answer(
        f"✅ Товар #{product_id} добавлен.\n"
        f"Категория: {data.get('category_title', '—')}\n"
        f"Теперь добавь сток: /addstock {product_id}\n"
        "Или через /admin → 📦 Товары."
    )


@dp.message(Command("addstock"))
async def cmd_addstock(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not await require_admin(message):
        return
    parts = (command.args or "").split()
    if not parts or not parts[0].isdigit():
        total = await db.count_products()
        products = await db.list_products(limit=20)
        lines = "\n".join(
            f"#{product['id']} · {product['title']} · {product['stock']} шт."
            for product in products
        )
        await message.answer(
            "Использование: /addstock <ID товара>\n\n"
            f"Товары (первые 20 из {total}, полностью — /admin → 📦 Товары):\n"
            f"{lines or 'пока нет товаров'}"
        )
        return
    product_id = int(parts[0])
    product = await db.get_product(product_id)
    if product is None:
        await message.answer("Товар с таким ID не найден.")
        return
    await state.set_state(AddStock.content)
    await state.update_data(product_id=product_id)
    await message.answer(
        f"📦 Товар #{product_id} · {product['title']}\n\n"
        "Отправь позиции для стока: каждая строка — отдельный товар.\n"
        "Например:\n+1 555 000-00-01 | код 1234\n+1 555 000-00-02 | код 5678\n\n"
        "/cancel — отмена."
    )


@dp.message(AddStock.content, F.text)
async def addstock_content(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not lines:
        await message.answer("Нужна хотя бы одна строка. Попробуй ещё раз.")
        return
    data = await state.get_data()
    product_id = data.get("product_id")
    product = await db.get_product(product_id) if product_id else None
    if product is None:
        await state.clear()
        await message.answer("Товар не найден. Начни заново: /addstock <ID>.")
        return
    count = await db.add_stock(product_id, lines)
    await state.clear()
    await message.answer(
        f"✅ Добавлено позиций: {count}.\n"
        f"Теперь в наличии: {await db.stock_count(product_id)} шт.\n"
        f"Товар: #{product_id} · {product['title']}"
    )


@dp.message(Command("stock"))
async def cmd_stock(message: Message) -> None:
    if not await require_admin(message):
        return
    total = await db.count_products()
    products = await db.list_products(limit=30)
    if not products:
        await message.answer("Товаров пока нет. Добавь: /addproduct")
        return
    lines = [
        f"#{product['id']} · {product['title']} · {money(product['price'])} · "
        f"{product['stock']} шт."
        for product in products
    ]
    await message.answer(
        f"📦 Товары и остатки (первые 30 из {total}):\n\n" + "\n".join(lines)
    )


@dp.message(Command("delproduct"))
async def cmd_delproduct(message: Message, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Использование: /delproduct <ID товара>")
        return
    product_id = int(args)
    product = await db.get_product(product_id)
    if product is None or not product["active"]:
        await message.answer("Активный товар с таким ID не найден.")
        return
    await db.deactivate_product(product_id)
    await message.answer(
        f"🗑 Товар #{product_id} · {product['title']} удалён из каталога.\n"
        "Старые заказы сохранятся."
    )


@dp.message(Command("chat"))
async def cmd_chat(message: Message, command: CommandObject, state: FSMContext) -> None:
    if not await require_admin(message):
        return
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Использование: /chat <ID клиента>")
        return
    user_id = int(args)
    user = await db.get_user(user_id)
    if user is None:
        await message.answer(
            "Клиент не найден. Он должен хотя бы раз нажать /start в боте."
        )
        return
    await state.set_state(ClientMessage.text)
    await state.update_data(user_id=user_id)
    await message.answer(
        f"✉️ Чат с клиентом {display_user(user)}\n\n"
        "Отправь сообщение — я передам его клиенту от имени магазина.\n"
        "/cancel — выйти."
    )


# ---------------------------------------------------------------------------
# Админ-состояния
# ---------------------------------------------------------------------------


@dp.message(AdminReply.text, F.text)
async def admin_reply_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket = await db.get_ticket(ticket_id) if ticket_id else None
    if ticket is None:
        await state.clear()
        await message.answer("Обращение не найдено.")
        return
    if ticket["status"] != "open":
        await state.clear()
        await message.answer("Это обращение уже закрыто. Ответ не отправлен.")
        return
    await db.add_ticket_message(ticket_id, "admin", message.text)
    try:
        await bot.send_message(
            ticket["user_id"],
            f"💬 Ответ поддержки {config.SHOP_NAME}:\n\n{message.text}",
        )
    except Exception as exc:
        logging.warning("Не смог отправить ответ клиенту %s: %s", ticket["user_id"], exc)
        await state.clear()
        await message.answer("Сообщение сохранено, но доставить клиенту не удалось.")
        return
    await state.clear()
    await message.answer(f"✅ Ответ отправлен клиенту по обращению #{ticket_id}.")


@dp.message(ClientMessage.text, F.text)
async def client_message_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if not user_id:
        await state.clear()
        await message.answer("Клиент не выбран. Используй /chat <ID>.")
        return
    try:
        await bot.send_message(
            user_id,
            f"✉️ Сообщение от {config.SHOP_NAME}:\n\n{message.text}",
        )
    except Exception as exc:
        logging.warning("Не смог отправить сообщение клиенту %s: %s", user_id, exc)
        await message.answer("Не удалось доставить: клиент не запускал бота или заблокировал его.")
        return
    await state.clear()
    await message.answer(f"✅ Сообщение отправлено клиенту (ID {user_id}).")


# ---------------------------------------------------------------------------
# Админ-callback'и
# ---------------------------------------------------------------------------


@dp.callback_query(F.data == "adm:panel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    await safe_edit(
        callback.message,
        "🛠 Админ-панель ReduxShop\nВыбери раздел:",
        kb_admin_panel(),
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:orders")
async def cb_admin_orders(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    orders = await db.list_orders(15)
    if not orders:
        await safe_edit(callback.message, "🧾 Заказов пока нет.", kb_admin_panel())
    else:
        await safe_edit(
            callback.message,
            "🧾 Последние заказы\nВыбери заказ:",
            kb_admin_orders(orders),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:order:"))
async def cb_admin_order(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    order = await db.get_order(cb_id(callback.data))
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    await safe_edit(callback.message, admin_order_text(order), kb_admin_order(order))
    await callback.answer()


async def perform_delivery(order_id: int) -> tuple[bool, str]:
    order = await db.get_order(order_id)
    if order is None:
        return False, "Заказ не найден."
    if order["status"] == "delivered":
        return False, "Этот заказ уже выдан."
    if order["status"] == "cancelled":
        return False, "Заказ отменён."

    new_order, item = await db.deliver_order(order_id)
    if new_order is None or item is None:
        return False, "Нет свободного товара. Добавь сток: /addstock <ID>."

    try:
        await bot.send_message(
            new_order["user_id"],
            f"🎁 Заказ #{new_order['id']} выдан!\n\n"
            f"Товар: {html.escape(new_order['product_title'])}\n\n"
            f"<pre>{html.escape(item['content'])}</pre>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logging.warning(
            "Заказ %s выдан, но сообщение клиенту %s не доставлено: %s",
            order_id,
            new_order["user_id"],
            exc,
        )
        return True, "Товар выдан, но клиент не получил сообщение (заблокировал бота?)."

    return True, "Товар выдан, клиент получил данные."


@dp.callback_query(F.data.startswith("adm:deliver:"))
async def cb_admin_deliver(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    order_id = cb_id(callback.data)
    ok, message = await perform_delivery(order_id)
    await callback.answer(message, show_alert=not ok)
    order = await db.get_order(order_id)
    if order:
        await safe_edit(callback.message, admin_order_text(order), kb_admin_order(order))


@dp.callback_query(F.data.startswith("adm:markpaid:"))
async def cb_admin_markpaid(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    order_id = cb_id(callback.data)
    order = await db.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order["status"] != "new":
        await callback.answer("Заказ уже не в статусе «ожидает оплаты».", show_alert=True)
        return
    await db.mark_paid(order_id)
    order = await db.get_order(order_id)
    await safe_edit(callback.message, admin_order_text(order), kb_admin_order(order))
    await callback.answer("Оплата отмечена.")


@dp.callback_query(F.data.startswith("adm:cancel:"))
async def cb_admin_cancel(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    order_id = cb_id(callback.data)
    order = await db.get_order(order_id)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order["status"] == "delivered":
        await callback.answer("Выданный заказ отменить нельзя.", show_alert=True)
        return
    if order["status"] == "cancelled":
        await callback.answer("Заказ уже отменён.", show_alert=True)
        return
    await db.set_order_status(order_id, "cancelled")
    try:
        await bot.send_message(
            order["user_id"],
            f"❌ Заказ #{order_id} отменён.\n"
            "Если это ошибка — напиши в поддержку через бота.",
        )
    except Exception as exc:
        logging.warning("Не смог уведомить клиента %s: %s", order["user_id"], exc)
    order = await db.get_order(order_id)
    await safe_edit(callback.message, admin_order_text(order), kb_admin_order(order))
    await callback.answer("Заказ отменён.")


@dp.callback_query(F.data == "adm:tickets")
async def cb_admin_tickets(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    tickets = await db.list_open_tickets(15)
    if not tickets:
        await safe_edit(callback.message, "🆘 Открытых обращений нет.", kb_admin_panel())
    else:
        await safe_edit(
            callback.message,
            "🆘 Открытые обращения\nВыбери обращение:",
            kb_admin_tickets(tickets),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:ticket:"))
async def cb_admin_ticket(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    ticket = await db.get_ticket(cb_id(callback.data))
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    messages = await db.list_ticket_messages(ticket["id"], 10)
    history = []
    for item in messages:
        who = "👤 Клиент" if item["sender"] == "user" else "🛠 Поддержка"
        text = item["text"]
        if len(text) > 300:
            text = text[:300] + "…"
        history.append(f"{who}: {text}")
    text = (
        f"🆘 Обращение #{ticket['id']}\n"
        f"Клиент: {display_ticket_user(ticket)}\n"
        f"Статус: {'открыто' if ticket['status'] == 'open' else 'закрыто'}\n"
        f"Создано: {fmt_dt(ticket['created_at'])}\n\n"
        "История:\n" + ("\n\n".join(history) if history else "сообщений нет")
    )
    await safe_edit(callback.message, text, kb_admin_ticket(ticket))
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:treply:"))
async def cb_admin_treply(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    ticket = await db.get_ticket(cb_id(callback.data))
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    if ticket["status"] != "open":
        await callback.answer("Обращение закрыто.", show_alert=True)
        return
    await state.set_state(AdminReply.text)
    await state.update_data(ticket_id=ticket["id"])
    await callback.message.answer(
        f"✍️ Ответ клиенту по обращению #{ticket['id']}\n"
        f"Клиент: {display_ticket_user(ticket)}\n\n"
        "Напиши текст ответа одним сообщением. /cancel — отмена."
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:tclose:"))
async def cb_admin_tclose(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    ticket = await db.get_ticket(cb_id(callback.data))
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    if ticket["status"] != "open":
        await callback.answer("Уже закрыто.", show_alert=True)
        return
    await db.close_ticket(ticket["id"])
    try:
        await bot.send_message(
            ticket["user_id"],
            f"✅ Обращение #{ticket['id']} закрыто оператором.\n"
            "Если остались вопросы — снова нажми «🆘 Поддержка».",
        )
    except Exception as exc:
        logging.warning("Не смог уведомить клиента %s: %s", ticket["user_id"], exc)
    await safe_edit(
        callback.message,
        f"✅ Обращение #{ticket['id']} закрыто.\nКлиент уведомлён.",
        kb_admin_panel(),
    )
    await callback.answer("Закрыто.")


@dp.callback_query(F.data == "adm:clients")
async def cb_admin_clients(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    users = await db.list_users(20)
    if not users:
        await safe_edit(callback.message, "👥 Клиентов пока нет.", kb_admin_panel())
    else:
        await safe_edit(
            callback.message,
            "👥 Последние клиенты\nВыбери клиента:",
            kb_admin_clients(users),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:client:"))
async def cb_admin_client(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    user = await db.get_user(cb_id(callback.data))
    if user is None:
        await callback.answer("Клиент не найден.", show_alert=True)
        return
    orders_count = await db.scalar("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user["id"],))
    username = f"@{user['username']}" if user["username"] else "—"
    await safe_edit(
        callback.message,
        f"👤 Клиент\n"
        f"Имя: {user['full_name'] or 'Без имени'}\n"
        f"Username: {username}\n"
        f"ID: {user['id']}\n"
        f"Заказов: {orders_count}\n"
        f"В боте с: {fmt_dt(user['created_at'])}",
        kb_admin_client(user["id"]),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:cmsg:"))
async def cb_admin_cmsg(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    user_id = cb_id(callback.data)
    user = await db.get_user(user_id)
    if user is None:
        await callback.answer("Клиент не найден.", show_alert=True)
        return
    await state.set_state(ClientMessage.text)
    await state.update_data(user_id=user_id)
    await callback.message.answer(
        f"✉️ Сообщение клиенту {display_user(user)}\n\n"
        "Напиши текст — я передам его от имени магазина. /cancel — отмена."
    )
    await callback.answer()


async def show_admin_products(callback: CallbackQuery, page: int = 0) -> None:
    total = await db.count_products()
    if not total:
        await safe_edit(
            callback.message,
            "📦 Товаров пока нет.\nДобавь командой /addproduct.",
            kb_admin_panel(),
        )
        return
    pages = max(1, (total + ADMIN_PRODUCTS_PAGE_SIZE - 1) // ADMIN_PRODUCTS_PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    products = await db.list_products(
        limit=ADMIN_PRODUCTS_PAGE_SIZE, offset=page * ADMIN_PRODUCTS_PAGE_SIZE
    )
    await safe_edit(
        callback.message,
        f"📦 Товары\nСтраница {page + 1} из {pages} · всего {total}\nВыбери товар:",
        kb_admin_products(products, page, pages),
    )


@dp.callback_query(F.data == "adm:products")
async def cb_admin_products(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    await state.clear()
    await show_admin_products(callback, 0)
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:products:"))
async def cb_admin_products_page(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    await show_admin_products(callback, cb_id(callback.data))
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:product:"))
async def cb_admin_product(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    product = await db.get_product(cb_id(callback.data))
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await safe_edit(callback.message, product_admin_text(product), kb_admin_product(product))
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:addstock:"))
async def cb_admin_addstock(callback: CallbackQuery, state: FSMContext) -> None:
    if not await admin_callback(callback):
        return
    product = await db.get_product(cb_id(callback.data))
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await state.set_state(AddStock.content)
    await state.update_data(product_id=product["id"])
    await callback.message.answer(
        f"📦 Сток для товара #{product['id']} · {product['title']}\n\n"
        "Отправь позиции: каждая строка — отдельный товар.\n"
        "Например:\n+1 555 000-00-01 | код 1234\n+1 555 000-00-02 | код 5678\n\n"
        "/cancel — отмена."
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:delprod:"))
async def cb_admin_delprod(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    product = await db.get_product(cb_id(callback.data))
    if product is None:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await db.deactivate_product(product["id"])
    await safe_edit(
        callback.message,
        f"🗑 Товар #{product['id']} · {product['title']} удалён из каталога.\n"
        "Старые заказы сохранятся.",
        kb_admin_panel(),
    )
    await callback.answer("Удалено.")


@dp.callback_query(F.data == "adm:stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    if not await admin_callback(callback):
        return
    stats = await db.stats()
    await safe_edit(
        callback.message,
        f"📊 Статистика {config.SHOP_NAME}\n\n"
        f"👥 Клиентов: {stats['users']}\n"
        f"🧾 Заказов: {stats['orders']} (выдано {stats['delivered']})\n"
        f"💰 Выручка: {money(stats['revenue'])}\n"
        f"🆘 Открытых обращений: {stats['open_tickets']}",
        kb_admin_panel(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Прочие сообщения
# ---------------------------------------------------------------------------


@dp.message(StateFilter(None), F.text)
async def fallback_text(message: Message) -> None:
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.full_name or "")

    if is_admin(user.id):
        await message.answer(
            "🛠 Панель администратора: /admin\n"
            "Команды: /addproduct, /addstock <ID>, /stock, /chat <ID>",
            reply_markup=kb_main(True),
        )
        return

    ticket = await db.get_open_ticket(user.id)
    if ticket:
        await relay_user_message(message, ticket["id"])
        await message.answer("✅ Передал в поддержку.")
        return

    await message.answer("Выбери действие в меню 👇", reply_markup=kb_main(False))


@dp.errors()
async def handle_error(event: ErrorEvent) -> bool:
    logging.error("Ошибка при обработке обновления", exc_info=event.exception)
    return True


async def main() -> None:
    await db.connect()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="catalog", description="Каталог товаров"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="paysupport", description="Помощь по оплате"),
            BotCommand(command="id", description="Мой ID"),
        ]
    )
    if not config.ADMIN_IDS:
        logging.warning(
            "ADMIN_IDS пуст — админ-панель и уведомления недоступны. "
            "Укажи свой ID в .env (узнать: /id)."
        )
    if auto_payment_enabled():
        logging.info("Автооплата Telegram Payments включена (%s)", config.PAYMENT_CURRENCY)
    else:
        logging.info("Автооплата выключена — работает ручная оплата по реквизитам")
    logging.info("База данных: %s", config.DB_PATH)
    logging.info("ReduxShop запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
