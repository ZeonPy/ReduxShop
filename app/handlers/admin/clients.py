"""Админ: клиенты и личные сообщения."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.constants import ADMIN_LISTS_LIMIT
from app.context import AppContext
from app.states import ClientMessage
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

router = Router(name="admin_clients")


@router.callback_query(F.data == "adm:clients")
async def cb_admin_clients(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    users = await ctx.db.users.list_recent(ADMIN_LISTS_LIMIT)
    if not users:
        await ctx.banners.show(
            callback,
            "admin",
            "👥 Клиентов пока нет.",
            keyboards.kb_admin_panel(),
        )
    else:
        await ctx.banners.show(
            callback,
            "admin",
            "👥 Последние клиенты\nВыбери клиента:",
            keyboards.kb_admin_clients(users),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:client:"))
async def cb_admin_client(callback: CallbackQuery, ctx: AppContext) -> None:
    user = await ctx.db.users.get(tail_int(callback.data) or 0)
    if user is None:
        await callback.answer("Клиент не найден.", show_alert=True)
        return

    orders_count = await ctx.db.users.orders_count(user.id)
    username = f"@{user.username}" if user.username else "—"
    await ctx.banners.show(
        callback,
        "admin",
        f"👤 Клиент\n"
        f"Имя: {user.full_name or 'Без имени'}\n"
        f"Username: {username}\n"
        f"ID: {user.id}\n"
        f"Заказов: {orders_count}\n"
        f"В боте с: {texts.fmt_dt(user.created_at)}",
        keyboards.kb_admin_client(user.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:cmsg:"))
async def cb_admin_cmsg(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    user_id = tail_int(callback.data) or 0
    user = await ctx.db.users.get(user_id)
    if user is None:
        await callback.answer("Клиент не найден.", show_alert=True)
        return

    await state.set_state(ClientMessage.text)
    await state.update_data(user_id=user_id)
    await ctx.banners.show(
        callback,
        "admin",
        f"✉️ Сообщение клиенту {texts.display_user(user)}\n\n"
        "Напиши текст — я передам его от имени магазина. /cancel — отмена.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer()


@router.message(Command("chat"))
async def cmd_chat(
    message: Message, command: CommandObject, state: FSMContext, ctx: AppContext
) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await ctx.banners.show(
            message, "admin", "Использование: /chat <ID клиента>"
        )
        return

    user = await ctx.db.users.get(int(args))
    if user is None:
        await ctx.banners.show(
            message,
            "admin",
            "Клиент не найден. Он должен хотя бы раз нажать /start в боте.",
        )
        return

    await state.set_state(ClientMessage.text)
    await state.update_data(user_id=user.id)
    await ctx.banners.show(
        message,
        "admin",
        f"✉️ Чат с клиентом {texts.display_user(user)}\n\n"
        "Отправить сообщение — я передам его клиенту от имени магазина.\n"
        "/cancel — выйти.",
    )


@router.message(ClientMessage.text, F.text)
async def client_message_text(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    data = await state.get_data()
    user_id = data.get("user_id")
    if not user_id:
        await state.clear()
        await ctx.banners.show(
            message, "admin", "Клиент не выбран. Используй /chat <ID>."
        )
        return

    sent = await ctx.notifier.to_user(
        user_id,
        f"✉️ Сообщение от {ctx.settings.shop_name}:\n\n{message.text}",
        key="support",
    )
    await state.clear()
    if not sent:
        await ctx.banners.show(
            message,
            "admin",
            "Не удалось доставить: клиент не запускал бота или заблокировал его.",
        )
        return
    await ctx.banners.show(
        message, "admin", f"✅ Сообщение отправлено клиенту (ID {user_id})."
    )


@router.message(ClientMessage.text, ~F.text)
async def client_message_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "admin", "Отправь сообщение текстом, пожалуйста."
    )
