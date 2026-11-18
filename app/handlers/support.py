"""Поддержка: обращения клиента."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.context import AppContext
from app.handlers.utils import telegram_user_line
from app.states import SupportState
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

router = Router(name="support")


@router.callback_query(F.data == "support")
async def cb_support(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    ticket = await ctx.tickets.current(callback.from_user.id)
    await ctx.banners.show(
        callback,
        "support",
        texts.support_intro_text(ctx.settings),
        keyboards.kb_support(ticket.id if ticket else None),
    )
    await state.set_state(SupportState.message)
    await callback.answer()


@router.callback_query(F.data.startswith("tkt:userclose:"))
async def cb_ticket_user_close(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    ticket = await ctx.db.tickets.get(tail_int(callback.data) or 0)
    if ticket is None or ticket.user_id != callback.from_user.id:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return

    await state.clear()
    await ctx.tickets.close(ticket.id)
    await ctx.notifier.to_admins(
        f"✅ Клиент закрыл обращение #{ticket.id}", key="support"
    )
    await ctx.banners.show(
        callback,
        "support",
        "✅ Обращение закрыто. Если появится новый вопрос — снова нажми "
        "«🆘 Поддержка».",
        keyboards.kb_main(ctx.settings.is_admin(callback.from_user.id)),
    )
    await callback.answer("Обращение закрыто.")


@router.message(SupportState.message, F.text)
async def support_message(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    user = message.from_user
    ticket = await ctx.tickets.relay_user_message(user.id, message.text)
    await ctx.notifier.to_admins(
        f"🆘 Обращение #{ticket.id}\n"
        f"Клиент: {telegram_user_line(user)}\n\n"
        f"{message.text}",
        reply_markup=keyboards.kb_ticket_notify(ticket.id),
        key="support",
    )
    await ctx.banners.show(
        message,
        "support",
        "✅ Передал оператору. Ответ придёт сюда.\n"
        "Можешь продолжать писать — сообщения добавятся в это обращение.",
    )
    await state.clear()


@router.message(SupportState.message)
async def support_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "support", "Отправь сообщение текстом, пожалуйста."
    )
