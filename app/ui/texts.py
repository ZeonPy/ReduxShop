"""Тексты сообщений бота.

Все функции чистые: получают настройки и модели, возвращают строку.
Так тексты легко проверить в тестах и переиспользовать в разных хендлерах.
"""

from __future__ import annotations

import html
from datetime import datetime

from app.constants import OrderStatus, STATUS_LABELS, TicketStatus
from app.countries import COUNTRIES
from app.models import Order, Product, Stats, Ticket, TicketMessage, User
from app.runtime import RuntimeConfig


def money(settings: RuntimeConfig, value: int) -> str:
    return f"{value} {settings.currency}"


def fmt_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def status_label(status: OrderStatus) -> str:
    return STATUS_LABELS.get(status, status.value)


def display_user(user: User) -> str:
    name = user.full_name or "Без имени"
    username = f" (@{user.username})" if user.username else ""
    return f"{name}{username} · ID {user.id}"


def display_order_user(order: Order) -> str:
    name = order.full_name or "Без имени"
    username = f" (@{order.username})" if order.username else ""
    return f"{name}{username} · ID {order.user_id}"


def display_ticket_user(ticket: Ticket) -> str:
    name = ticket.full_name or "Без имени"
    username = f" (@{ticket.username})" if ticket.username else ""
    return f"{name}{username} · ID {ticket.user_id}"


def welcome_text(settings: RuntimeConfig) -> str:
    return (
        f"👋 Добро пожаловать в {settings.shop_name}!\n\n"
        f"Виртуальные номера для приёма SMS из {len(COUNTRIES)} стран.\n"
        "• 📲 данные приходят прямо в этот чат;\n"
        "• 💳 оплата по СБП или счётом Telegram;\n"
        "• 🕘 поддержка на связи каждый день.\n\n"
        "Выбери раздел ниже 👇"
    )


def menu_text(settings: RuntimeConfig) -> str:
    return (
        f"🏠 Главное меню {settings.shop_name}\n\n"
        "🛍 Каталог — выбрать номер\n"
        "📦 Мои заказы — статусы и выданные данные\n"
        "🆘 Поддержка — помощь оператора\n\n"
        "Что откроем?"
    )


def help_text(settings: RuntimeConfig, auto_payment: bool) -> str:
    payment_step = (
        "Оплати счёт Telegram — товар выдастся автоматически."
        if auto_payment
        else "Переведи сумму по реквизитам и нажми «✅ Я оплатил»."
    )
    return (
        f"ℹ️ {settings.shop_name} — помощь\n\n"
        "Как купить номер:\n"
        "1. Открой «🛍 Каталог» и выбери страну.\n"
        "2. Нажми на товар и «🛒 Купить».\n"
        f"3. {payment_step}\n"
        "4. Дождись проверки оплаты — данные придут в этот чат.\n\n"
        "Полезные команды:\n"
        "/start — главное меню\n"
        "/catalog — каталог стран\n"
        "/paysupport — помощь по оплате\n"
        "/id — узнать свой ID\n\n"
        "🔐 Не передавай номер и коды третьим лицам."
    )


def about_text(settings: RuntimeConfig) -> str:
    return (
        f"ℹ️ О магазине {settings.shop_name}\n\n"
        "Мы продаём виртуальные номера для приёма SMS.\n"
        f"• {len(COUNTRIES)} стран на выбор;\n"
        "• выдача данных прямо в чат;\n"
        "• оплата по СБП или счётом Telegram;\n"
        "• помощь оператора, если что-то пошло не так.\n\n"
        f"Наш канал: {settings.shop_link}\n\n"
        "Вопросы по заказу — через «🆘 Поддержка»."
    )


def payment_help_text(settings: RuntimeConfig) -> str:
    return (
        "💳 Помощь по оплате и возвратам\n\n"
        "Если деньги списались, а товар не пришёл, напиши сюда одним сообщением:\n"
        "• номер заказа;\n"
        "• сумму и время оплаты;\n"
        "• удобный способ связи.\n\n"
        "Оператор проверит платёж и поможет. Возврат по оплате в Telegram "
        "оформляется через поддержку магазина.\n\n"
        "Напиши сообщение следующим шагом 👇"
    )


def support_intro_text(settings: RuntimeConfig) -> str:
    return (
        f"🆘 Поддержка {settings.shop_name}\n\n"
        "Напиши вопрос одним сообщением — я передам его оператору. "
        "Ответ придёт сюда же.\n\n"
        "Чтобы решить вопрос быстрее, укажи номер заказа, сумму и время оплаты.\n\n"
        "Можно продолжать писать: сообщения добавятся в открытое обращение."
    )


def payment_details(settings: RuntimeConfig) -> str:
    return settings.public_payment_details


def payment_text(settings: RuntimeConfig, order: Order) -> str:
    return (
        f"🧾 Заказ #{order.id} создан\n\n"
        f"Товар: {order.product_title}\n"
        f"Сумма: {money(settings, order.price)}\n\n"
        f"Реквизиты для оплаты:\n{payment_details(settings)}\n\n"
        "1. Переведи точную сумму.\n"
        "2. Вернись в бота и нажми «✅ Я оплатил».\n"
        "3. Оператор проверит платёж и выдаст данные в этот чат.\n\n"
        "⚠️ Без отметки об оплате заказ может задержаться."
    )


def invoice_text(settings: RuntimeConfig, order: Order) -> str:
    return (
        f"🧾 Заказ #{order.id} создан\n\n"
        f"Товар: {order.product_title}\n"
        f"Сумма: {money(settings, order.price)}\n\n"
        "Счёт на оплату отправлен отдельным сообщением 👇\n"
        "После оплаты товар выдастся автоматически в этом чате.\n"
        "Потерял счёт — открой «📦 Мои заказы» и нажми «💳 Оплатить»."
    )


def user_order_text(settings: RuntimeConfig, order: Order) -> str:
    return (
        f"🧾 Заказ #{order.id}\n"
        f"Товар: {order.product_title}\n"
        f"Сумма: {money(settings, order.price)}\n"
        f"Статус: {status_label(order.status)}\n"
        f"Создан: {fmt_dt(order.created_at)}"
    )


def admin_order_text(settings: RuntimeConfig, order: Order) -> str:
    return (
        f"🧾 Заказ #{order.id}\n"
        f"Клиент: {display_order_user(order)}\n"
        f"Товар: {order.product_title}\n"
        f"Сумма: {money(settings, order.price)}\n"
        f"Статус: {status_label(order.status)}\n"
        f"Создан: {fmt_dt(order.created_at)}\n"
        f"Оплачен: {fmt_dt(order.paid_at)}\n"
        f"Выдан: {fmt_dt(order.delivered_at)}"
    )


def product_admin_text(settings: RuntimeConfig, product: Product) -> str:
    description = product.description or "—"
    active = "да" if product.active else "нет (удалён)"
    return (
        f"📦 Товар #{product.id}\n"
        f"Категория: {product.category}\n"
        f"Название: {product.title}\n"
        f"Цена: {money(settings, product.price)}\n"
        f"В наличии: {product.stock} шт.\n"
        f"Активен: {active}\n\n"
        f"Описание: {description}"
    )


def catalog_text(total: int, page: int, pages: int) -> str:
    return (
        "🛍 Каталог стран\n"
        "Выбери страну — покажу доступные виртуальные номера.\n"
        "Цена и наличие обновляются автоматически.\n\n"
        f"Страница {page + 1} из {pages} · всего {total} стран"
    )


def addproduct_categories_text(page: int, pages: int) -> str:
    return (
        "📦 Новый товар\n\n"
        "Выбери страну-категорию, в которую добавить товар.\n"
        f"Страница {page + 1} из {pages}"
    )


def ticket_admin_text(ticket: Ticket, messages: list[TicketMessage]) -> str:
    history = []
    for item in messages:
        who = "👤 Клиент" if item.sender == "user" else "🛠 Поддержка"
        text = item.text
        if len(text) > 300:
            text = text[:300] + "…"
        history.append(f"{who}: {text}")
    return (
        f"🆘 Обращение #{ticket.id}\n"
        f"Клиент: {display_ticket_user(ticket)}\n"
        f"Статус: {'открыто' if ticket.status == TicketStatus.OPEN else 'закрыто'}\n"
        f"Создано: {fmt_dt(ticket.created_at)}\n\n"
        "История:\n" + ("\n\n".join(history) if history else "сообщений нет")
    )


def stats_text(settings: RuntimeConfig, stats: Stats) -> str:
    return (
        f"📊 Статистика {settings.shop_name}\n\n"
        f"👥 Клиентов: {stats.users}\n"
        f"🧾 Заказов: {stats.orders} (выдано {stats.delivered})\n"
        f"💰 Выручка: {money(settings, stats.revenue)}\n"
        f"🆘 Открытых обращений: {stats.open_tickets}"
    )


def delivery_text(order: Order, item: str) -> str:
    return (
        f"🎁 Заказ #{order.id} выдан!\n\n"
        f"Товар: {html.escape(order.product_title)}\n\n"
        f"<pre>{html.escape(item)}</pre>\n\n"
        "Сохрани данные. Не передавай номер и коды третьим лицам.\n"
        "Если что-то не работает — открой «🆘 Поддержка» и укажи номер заказа."
    )


def settings_text(
    settings: RuntimeConfig,
    *,
    products: int,
    banners_custom: int,
    banner_total: int,
) -> str:
    details = settings.payment_details.replace("\n", " · ")
    if len(details) > 120:
        details = details[:117] + "…"
    rules = settings.pricing
    banners = "включены" if settings.banners_enabled else "выключены"
    return (
        "⚙️ Настройки магазина\n\n"
        f"Название: {settings.shop_name}\n"
        f"Ссылка: {settings.shop_link}\n"
        f"Валюта: {settings.currency}\n"
        f"Реквизиты: {details}\n\n"
        f"Прайс: ×{rules.cheap_multiplier} до {rules.cheap_limit} {settings.currency}, "
        f"×{rules.expensive_multiplier} дороже, минимум {rules.min_price} {settings.currency}\n"
        f"Товаров в каталоге: {products}\n"
        f"Баннеры: {banners} · своих {banners_custom} из {banner_total}\n"
        f"Автооплата: {'включена' if settings.auto_payment_enabled else 'выключена'}\n\n"
        "Выбери, что изменить 👇"
    )


def banners_text(
    settings: RuntimeConfig, *, custom: int, total: int
) -> str:
    status = "🟢 включены" if settings.banners_enabled else "🔴 выключены"
    return (
        "🖼 Баннеры магазина\n\n"
        f"Статус: {status}\n"
        f"Своих изображений: {custom} из {total}\n\n"
        "Можно заменить баннер любого экрана своим фото. "
        "Если баннеры выключить, бот будет присылать обычные текстовые сообщения."
    )


def banner_screen_text(screen_label: str, has_custom: bool) -> str:
    state = "своё изображение" if has_custom else "стандартный баннер"
    return (
        f"🖼 Баннер экрана «{screen_label}»\n\n"
        f"Сейчас: {state}.\n\n"
        "Отправь новое фото — я сразу поставлю его на этот экран. "
        "Рекомендуемый размер: 1280×640."
    )


def startup_text(
    settings: RuntimeConfig,
    *,
    version: str,
    products: int,
    min_price: int,
    cheap_limit: int,
    cheap_multiplier: int,
    expensive_multiplier: int,
    auto_payment: bool,
) -> str:
    payment = "включена" if auto_payment else "выключена (ручная оплата)"
    return (
        f"🚀 ReduxShop {version} запущен\n"
        f"Товаров в каталоге: {products}\n"
        f"Прайс: ×{cheap_multiplier} до {cheap_limit} {settings.currency}, "
        f"×{expensive_multiplier} дороже · минимум {min_price} {settings.currency}\n"
        f"Автооплата: {payment}\n"
        f"Баннеры: {'включены' if settings.banners_enabled else 'выключены'}"
    )
