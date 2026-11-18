"""Админ: управление баннерами экранов."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.context import AppContext
from app.states import BannerUpload
from app.ui import keyboards, texts
from app.ui.banners import BANNER_LABELS, BANNERS

router = Router(name="admin_banners")


async def show_banners(
    event: Message | CallbackQuery, ctx: AppContext
) -> None:
    await ctx.banners.show(
        event,
        "admin",
        texts.banners_text(
            ctx.settings,
            custom=len(ctx.settings.banner_file_ids),
            total=len(BANNERS),
        ),
        keyboards.kb_admin_banners(ctx.settings),
    )


async def show_banner_screen(
    event: Message | CallbackQuery, ctx: AppContext, screen: str
) -> None:
    if screen not in BANNER_LABELS:
        return
    has_custom = screen in ctx.settings.banner_file_ids
    await ctx.banners.show(
        event,
        screen,
        texts.banner_screen_text(BANNER_LABELS[screen], has_custom),
        keyboards.kb_banner_screen(screen, has_custom),
    )


@router.callback_query(F.data == "adm:banners")
async def cb_banners(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await show_banners(callback, ctx)
    await callback.answer()


@router.callback_query(F.data == "adm:banners:toggle")
async def cb_banners_toggle(callback: CallbackQuery, ctx: AppContext) -> None:
    enabled = not ctx.settings.banners_enabled
    await ctx.config_service.set_banners_enabled(ctx.settings, enabled)
    await show_banners(callback, ctx)
    await callback.answer("Баннеры включены." if enabled else "Баннеры выключены.")


@router.callback_query(F.data.startswith("adm:banner:"))
async def cb_banner(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    screen = (callback.data or "").rsplit(":", 1)[-1]
    if screen not in BANNER_LABELS:
        await callback.answer("Неизвестный экран.", show_alert=True)
        return
    await show_banner_screen(callback, ctx, screen)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bannerset:"))
async def cb_banner_set(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    screen = (callback.data or "").rsplit(":", 1)[-1]
    if screen not in BANNER_LABELS:
        await callback.answer("Неизвестный экран.", show_alert=True)
        return

    await state.set_state(BannerUpload.photo)
    await state.update_data(banner_screen=screen)
    await ctx.banners.show(
        callback,
        "admin",
        f"🖼 Замена баннера «{BANNER_LABELS[screen]}»\n\n"
        "Отправь фото одним сообщением. Рекомендуемый размер: 1280×640.\n"
        "Фото сразу появится на этом экране.\n\n"
        "/cancel — отмена.",
        keyboards.kb_banner_screen(screen, screen in ctx.settings.banner_file_ids),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bannerreset:"))
async def cb_banner_reset(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    screen = (callback.data or "").rsplit(":", 1)[-1]
    if screen not in BANNER_LABELS:
        await callback.answer("Неизвестный экран.", show_alert=True)
        return

    await state.clear()
    await ctx.config_service.reset_banner(ctx.settings, screen)
    await show_banner_screen(callback, ctx, screen)
    await callback.answer("Вернул стандартный баннер.")


@router.message(BannerUpload.photo, F.photo)
async def banner_photo(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    data = await state.get_data()
    screen = data.get("banner_screen")
    if screen not in BANNER_LABELS:
        await state.clear()
        await show_banners(message, ctx)
        return

    file_id = message.photo[-1].file_id
    await ctx.config_service.set_banner(ctx.settings, screen, file_id)
    await state.clear()
    await ctx.banners.show(
        message,
        screen,
        f"✅ Баннер «{BANNER_LABELS[screen]}» обновлён.\n\n"
        "Новое изображение уже на экране.",
        keyboards.kb_banner_screen(screen, True),
    )


@router.message(BannerUpload.photo, ~F.photo)
async def banner_non_photo(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message,
        "admin",
        "Нужно именно фото. Отправь картинку одним сообщением или /cancel.",
    )
