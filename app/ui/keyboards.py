"""Inline-клавиатуры.

Callback_data соответствует прежней версии бота: старые сообщения в чатах
продолжают работать после обновления.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.runtime import RuntimeConfig
from app.constants import OrderStatus, STATUS_EMOJI, TicketStatus
from app.models import Category, Order, Product, Ticket, User
from app.ui import texts
from app.ui.banners import BANNER_LABELS, BANNERS


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


def kb_catalog(
    settings: RuntimeConfig, categories: list[Category], page: int, pages: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        tail = (
            f"от {texts.money(settings, category.min_price)}"
            if category.min_price
            else "скоро"
        )
        if category.stock:
            tail += f" · {category.stock} шт."
        builder.button(
            text=f"{category.title} · {tail}",
            callback_data=f"cat:{category.id}",
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


def kb_category(
    settings: RuntimeConfig, products: list[Product]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        tail = f"{product.stock} шт." if product.stock else "нет в наличии"
        builder.button(
            text=(
                f"{product.title} · {texts.money(settings, product.price)} · {tail}"
            ),
            callback_data=f"prod:{product.id}",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="⬅️ Все страны", callback_data="catalog"),
        InlineKeyboardButton(text="🏠 В меню", callback_data="menu"),
    )
    return builder.as_markup()


def kb_product(product: Product) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if product.active and product.stock > 0:
        builder.button(text="🛒 Купить", callback_data=f"buy:{product.id}")
    builder.button(text="⬅️ К стране", callback_data=f"cat:{product.category_id}")
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_payment(order_id: int, auto_payment: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if auto_payment:
        builder.button(text="💳 Оплатить", callback_data=f"pay:{order_id}")
    else:
        builder.button(text="✅ Я оплатил", callback_data=f"paid:{order_id}")
    builder.button(text="⬅️ Каталог", callback_data="catalog")
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_my_orders(settings: RuntimeConfig, orders: list[Order]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=(
                f"#{order.id} · {STATUS_EMOJI.get(order.status, '•')} · "
                f"{order.product_title} · {texts.money(settings, order.price)}"
            ),
            callback_data=f"myord:{order.id}",
        )
    builder.button(text="⬅️ В меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_my_order(order: Order, auto_payment: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order.status == OrderStatus.NEW:
        if auto_payment:
            builder.button(text="💳 Оплатить", callback_data=f"pay:{order.id}")
        else:
            builder.button(text="✅ Я оплатил", callback_data=f"paid:{order.id}")
    builder.button(text="⬅️ Мои заказы", callback_data="myorders")
    builder.button(text="🏠 Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def kb_support(ticket_id: int | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if ticket_id:
        builder.button(
            text="❌ Закрыть обращение", callback_data=f"tkt:userclose:{ticket_id}"
        )
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
    builder.button(text="⚙️ Настройки", callback_data="adm:settings")
    builder.button(text="🖼 Баннеры", callback_data="adm:banners")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def kb_order_notify(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Выдать товар", callback_data=f"adm:deliver:{order_id}")
    builder.button(text="🧾 Открыть заказ", callback_data=f"adm:order:{order_id}")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_orders(settings: RuntimeConfig, orders: list[Order]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=(
                f"#{order.id} · {STATUS_EMOJI.get(order.status, '•')} · "
                f"{texts.money(settings, order.price)}"
            ),
            callback_data=f"adm:order:{order.id}",
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_order(order: Order) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order.status not in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        builder.button(text="📤 Выдать товар", callback_data=f"adm:deliver:{order.id}")
        if order.status == OrderStatus.NEW:
            builder.button(
                text="💰 Отметить оплату", callback_data=f"adm:markpaid:{order.id}"
            )
        builder.button(text="❌ Отменить", callback_data=f"adm:cancel:{order.id}")
    builder.button(text="✉️ Написать клиенту", callback_data=f"adm:cmsg:{order.user_id}")
    builder.button(text="⬅️ Заказы", callback_data="adm:orders")
    builder.adjust(2)
    return builder.as_markup()


def kb_ticket_notify(ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Ответить", callback_data=f"adm:treply:{ticket_id}")
    builder.button(text="🧾 Открыть", callback_data=f"adm:ticket:{ticket_id}")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_tickets(tickets: list[Ticket]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        name = (ticket.full_name or "Клиент")[:24]
        builder.button(
            text=f"#{ticket.id} · {name} · ID {ticket.user_id}",
            callback_data=f"adm:ticket:{ticket.id}",
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_ticket(ticket: Ticket) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if ticket.status == TicketStatus.OPEN:
        builder.button(text="✍️ Ответить", callback_data=f"adm:treply:{ticket.id}")
        builder.button(text="✅ Закрыть", callback_data=f"adm:tclose:{ticket.id}")
    builder.button(
        text="✉️ Написать клиенту", callback_data=f"adm:cmsg:{ticket.user_id}"
    )
    builder.button(text="⬅️ Обращения", callback_data="adm:tickets")
    builder.adjust(2)
    return builder.as_markup()


def kb_admin_clients(users: list[User]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        name = (user.full_name or "Без имени")[:26]
        builder.button(
            text=f"{name} · ID {user.id} · заказов {user.orders_count}",
            callback_data=f"adm:client:{user.id}",
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


def kb_admin_products(
    settings: RuntimeConfig,
    products: list[Product],
    page: int = 0,
    pages: int = 1,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        title = product.title
        if len(title) > 32:
            title = title[:31] + "…"
        builder.button(
            text=(
                f"#{product.id} · {title} · {texts.money(settings, product.price)} · "
                f"{product.stock} шт."
            ),
            callback_data=f"adm:product:{product.id}",
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


def kb_addproduct_categories(
    categories: list[Category], page: int, pages: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=category.title[:60], callback_data=f"apcat:{category.id}"
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


def kb_admin_product(product: Product) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить сток", callback_data=f"adm:addstock:{product.id}"
    )
    if product.active:
        builder.button(
            text="🗑 Удалить товар", callback_data=f"adm:delprod:{product.id}"
        )
    builder.button(text="⬅️ Товары", callback_data="adm:products")
    builder.adjust(1)
    return builder.as_markup()


def kb_admin_settings() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data="adm:set:shop_name")
    builder.button(text="🔗 Ссылка", callback_data="adm:set:shop_link")
    builder.button(text="💳 Реквизиты", callback_data="adm:set:payment_details")
    builder.button(text="💱 Валюта", callback_data="adm:set:currency")
    builder.button(text="💰 Мин. цена", callback_data="adm:set:min_price")
    builder.button(text="🎯 Порог дешёвых", callback_data="adm:set:cheap_limit")
    builder.button(text="📈 Наценка ≤ порога", callback_data="adm:set:cheap_multiplier")
    builder.button(
        text="📉 Наценка > порога", callback_data="adm:set:expensive_multiplier"
    )
    builder.button(text="🖼 Баннеры", callback_data="adm:banners")
    builder.button(text="🔄 Пересчитать цены", callback_data="adm:reprice")
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def kb_admin_banners(settings: RuntimeConfig) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle = (
        "🔴 Выключить баннеры"
        if settings.banners_enabled
        else "🟢 Включить баннеры"
    )
    builder.button(text=toggle, callback_data="adm:banners:toggle")
    for screen, label in BANNER_LABELS.items():
        mark = " · своё" if screen in settings.banner_file_ids else ""
        builder.button(
            text=f"{label}{mark}", callback_data=f"adm:banner:{screen}"
        )
    builder.button(text="⬅️ Панель", callback_data="adm:panel")
    builder.adjust(1)
    return builder.as_markup()


def kb_banner_screen(screen: str, has_custom: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Заменить фото", callback_data=f"adm:bannerset:{screen}")
    if has_custom:
        builder.button(
            text="♻️ Вернуть стандартный",
            callback_data=f"adm:bannerreset:{screen}",
        )
    builder.button(text="⬅️ Баннеры", callback_data="adm:banners")
    builder.adjust(1)
    return builder.as_markup()
