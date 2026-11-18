"""Последний роутер: сообщения, которые не подошли другим хендлерам."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.context import AppContext
from app.handlers.utils import telegram_user_line
from app.ui import keyboards

router = Router(name="fallback")


@router.message(StateFilter(None), F.text)
async def fallback_text(message: Message, ctx: AppContext) -> None:
    if ctx.settings.is_admin(message.from_user.id):
        await ctx.banners.show(
            message,
            "admin",
            "🛠 Панель администратора: /admin\n"
            "Команды: /addproduct, /addstock <ID>, /stock, /chat <ID>",
            keyboards.kb_main(True),
        )
        return

    ticket = await ctx.tickets.current(message.from_user.id)
    if ticket is not None:
        user = message.from_user
        await ctx.tickets.relay_user_message(user.id, message.text)
        await ctx.notifier.to_admins(
            f"🆘 Обращение #{ticket.id}\n"
            f"Клиент: {telegram_user_line(user)}\n\n"
            f"{message.text}",
            reply_markup=keyboards.kb_ticket_notify(ticket.id),
            key="support",
        )
        await ctx.banners.show(
            message, "support", "✅ Передал в поддержку."
        )
        return

    await ctx.banners.show(
        message,
        "main",
        "Выбери действие в меню 👇",
        keyboards.kb_main(False),
    )


@router.message(StateFilter(None))
async def fallback_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message,
        "main",
        "Отправь текстовое сообщение или выбери раздел в меню 👇",
        keyboards.kb_main(ctx.settings.is_admin(message.from_user.id)),
    )
