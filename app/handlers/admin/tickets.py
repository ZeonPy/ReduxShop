"""Админ: обращения в поддержку."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.constants import ADMIN_LISTS_LIMIT, TICKET_HISTORY_LIMIT, TicketStatus
from app.context import AppContext
from app.states import AdminReply
from app.ui import keyboards, texts
from app.ui.callbacks import tail_int

router = Router(name="admin_tickets")


@router.callback_query(F.data == "adm:tickets")
async def cb_admin_tickets(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    tickets = await ctx.db.tickets.list_open(ADMIN_LISTS_LIMIT)
    if not tickets:
        await ctx.banners.show(
            callback,
            "admin",
            "🆘 Открытых обращений нет.",
            keyboards.kb_admin_panel(),
        )
    else:
        await ctx.banners.show(
            callback,
            "admin",
            "🆘 Открытые обращения\nВыбери обращение:",
            keyboards.kb_admin_tickets(tickets),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ticket:"))
async def cb_admin_ticket(callback: CallbackQuery, ctx: AppContext) -> None:
    ticket = await ctx.db.tickets.get(tail_int(callback.data) or 0)
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    messages = await ctx.db.tickets.messages(ticket.id, TICKET_HISTORY_LIMIT)
    await ctx.banners.show(
        callback,
        "admin",
        texts.ticket_admin_text(ticket, messages),
        keyboards.kb_admin_ticket(ticket),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:treply:"))
async def cb_admin_treply(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    ticket = await ctx.db.tickets.get(tail_int(callback.data) or 0)
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    if ticket.status != TicketStatus.OPEN:
        await callback.answer("Обращение закрыто.", show_alert=True)
        return

    await state.set_state(AdminReply.text)
    await state.update_data(ticket_id=ticket.id)
    await ctx.banners.show(
        callback,
        "admin",
        f"✍️ Ответ клиенту по обращению #{ticket.id}\n"
        f"Клиент: {texts.display_ticket_user(ticket)}\n\n"
        "Напиши текст ответа одним сообщением. /cancel — отмена.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:tclose:"))
async def cb_admin_tclose(callback: CallbackQuery, ctx: AppContext) -> None:
    ticket_id = tail_int(callback.data) or 0
    ticket = await ctx.db.tickets.get(ticket_id)
    if ticket is None:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    if ticket.status != TicketStatus.OPEN:
        await callback.answer("Уже закрыто.", show_alert=True)
        return

    await ctx.tickets.close(ticket_id)
    await ctx.notifier.to_user(
        ticket.user_id,
        f"✅ Обращение #{ticket_id} закрыто оператором.\n"
        "Если остались вопросы — снова нажми «🆘 Поддержка».",
        key="support",
    )
    await ctx.banners.show(
        callback,
        "admin",
        f"✅ Обращение #{ticket_id} закрыто.\nКлиент уведомлён.",
        keyboards.kb_admin_panel(),
    )
    await callback.answer("Закрыто.")


@router.message(AdminReply.text, F.text)
async def admin_reply_text(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    ticket = await ctx.db.tickets.get(ticket_id) if ticket_id else None
    if ticket is None:
        await state.clear()
        await ctx.banners.show(message, "admin", "Обращение не найдено.")
        return
    if ticket.status != TicketStatus.OPEN:
        await state.clear()
        await ctx.banners.show(
            message, "admin", "Это обращение уже закрыто. Ответ не отправлен."
        )
        return

    await ctx.tickets.add_admin_reply(ticket_id, message.text)
    sent = await ctx.notifier.to_user(
        ticket.user_id,
        f"💬 Ответ поддержки {ctx.settings.shop_name}:\n\n{message.text}",
        key="support",
    )
    await state.clear()
    if not sent:
        await ctx.banners.show(
            message,
            "admin",
            "Сообщение сохранено, но доставить клиенту не удалось.",
        )
        return
    await ctx.banners.show(
        message,
        "admin",
        f"✅ Ответ отправлен клиенту по обращению #{ticket_id}.",
    )


@router.message(AdminReply.text, ~F.text)
async def admin_reply_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "admin", "Отправь ответ текстом, пожалуйста."
    )
