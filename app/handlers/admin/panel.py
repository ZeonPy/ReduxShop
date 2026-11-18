"""Админ-панель и статистика."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.context import AppContext
from app.ui import keyboards, texts

router = Router(name="admin_panel")


@router.message(Command("admin"))
async def cmd_admin(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        message,
        "admin",
        "🛠 Админ-панель ReduxShop\nВыбери раздел:",
        keyboards.kb_admin_panel(),
    )


@router.callback_query(F.data == "adm:panel")
async def cb_admin_panel(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        callback,
        "admin",
        "🛠 Админ-панель ReduxShop\nВыбери раздел:",
        keyboards.kb_admin_panel(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(callback: CallbackQuery, ctx: AppContext) -> None:
    stats = await ctx.db.stats.summary()
    await ctx.banners.show(
        callback,
        "admin",
        texts.stats_text(ctx.settings, stats),
        keyboards.kb_admin_panel(),
    )
    await callback.answer()
