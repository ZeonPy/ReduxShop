"""Команды и главное меню."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import __version__
from app.context import AppContext
from app.pricing import MIN_PRICE, PRICING_VERSION
from app.states import SupportState
from app.ui import keyboards, texts

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, ctx: AppContext) -> None:
    await state.clear()
    await ctx.banners.show(
        message,
        "main",
        texts.welcome_text(ctx.settings),
        keyboards.kb_main(ctx.settings.is_admin(message.from_user.id)),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext, ctx: AppContext) -> None:
    await state.clear()
    await ctx.banners.show(
        message,
        "about",
        texts.help_text(ctx.settings, ctx.payments.enabled),
        keyboards.kb_main(ctx.settings.is_admin(message.from_user.id)),
    )


@router.message(Command("paysupport"))
async def cmd_paysupport(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        message, "support", texts.payment_help_text(ctx.settings)
    )
    await state.set_state(SupportState.message)


@router.message(Command("id"))
async def cmd_id(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message,
        "about",
        f"Твой ID: {message.from_user.id}\nID чата: {message.chat.id}",
    )


@router.message(Command("version"))
async def cmd_version(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message,
        "about",
        f"ℹ️ {ctx.settings.shop_name}\n\n"
        f"Версия: {__version__}\n"
        f"Прайс: {PRICING_VERSION}, минимум {MIN_PRICE} {ctx.settings.currency}\n\n"
        "Каталог виртуальных номеров для приёма SMS.",
        keyboards.kb_main(ctx.settings.is_admin(message.from_user.id)),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, ctx: AppContext) -> None:
    await state.clear()
    if ctx.settings.is_admin(message.from_user.id):
        await ctx.banners.show(
            message,
            "admin",
            "Отменено. Панель: /admin",
            keyboards.kb_admin_panel(),
        )
    else:
        await ctx.banners.show(
            message, "main", "Отменено.", keyboards.kb_main(False)
        )


@router.callback_query(F.data == "menu")
async def cb_menu(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        callback,
        "main",
        texts.menu_text(ctx.settings),
        keyboards.kb_main(ctx.settings.is_admin(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == "about")
async def cb_about(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await ctx.banners.show(
        callback,
        "about",
        texts.about_text(ctx.settings),
        keyboards.kb_main(ctx.settings.is_admin(callback.from_user.id)),
    )
    await callback.answer()
