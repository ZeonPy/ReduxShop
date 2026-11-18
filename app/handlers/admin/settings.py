"""Админ: гибкие настройки магазина."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.context import AppContext
from app.services.config import (
    PRICING_KEYS,
    SETTING_HINTS,
    SETTING_TITLES,
    ConfigError,
)
from app.states import AdminSetting
from app.ui import keyboards, texts
from app.ui.banners import BANNERS

router = Router(name="admin_settings")


def _current_value(ctx: AppContext, key: str) -> str:
    settings = ctx.settings
    if key == "shop_name":
        return settings.shop_name
    if key == "shop_link":
        return settings.shop_link
    if key == "payment_details":
        return settings.payment_details
    if key == "payment_card":
        return settings.payment_card
    if key == "payment_url":
        return settings.payment_url
    if key == "currency":
        return settings.currency
    if key == "min_price":
        return str(settings.pricing.min_price)
    if key == "cheap_limit":
        return str(settings.pricing.cheap_limit)
    if key == "cheap_multiplier":
        return str(settings.pricing.cheap_multiplier)
    if key == "expensive_multiplier":
        return str(settings.pricing.expensive_multiplier)
    if key == "deliverability":
        return str(settings.pricing.deliverability)
    if key == "smsfast_api_key":
        return settings.smsfast_key_masked
    if key == "smsfast_service":
        return settings.smsfast_service
    if key == "smsfast_base_url":
        return settings.smsfast_base_url
    raise ConfigError("Неизвестная настройка.")


async def show_settings(
    event: Message | CallbackQuery, ctx: AppContext
) -> None:
    products = await ctx.db.products.count()
    await ctx.banners.show(
        event,
        "admin",
        texts.settings_text(
            ctx.settings,
            products=products,
            banners_custom=len(ctx.settings.banner_file_ids),
            banner_total=len(BANNERS),
        ),
        keyboards.kb_admin_settings(),
    )


@router.message(Command("settings"))
async def cmd_settings(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await show_settings(message, ctx)


@router.callback_query(F.data == "adm:settings")
async def cb_settings(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await show_settings(callback, ctx)
    await callback.answer()


@router.callback_query(F.data == "adm:reprice")
async def cb_reprice(callback: CallbackQuery, ctx: AppContext) -> None:
    updated = await ctx.catalog.apply_retail_prices(force=True)
    await show_settings(callback, ctx)
    await callback.answer(f"Цены пересчитаны: {updated} товаров.")


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_set_value(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    key = (callback.data or "").rsplit(":", 1)[-1]
    if key not in SETTING_TITLES:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return

    await state.set_state(AdminSetting.value)
    await state.update_data(setting_key=key)
    current = _current_value(ctx, key)
    await ctx.banners.show(
        callback,
        "admin",
        f"⚙️ {SETTING_TITLES[key]}\n\n"
        f"Сейчас: {current}\n\n"
        f"{SETTING_HINTS[key]}\n\n"
        "Отправь новое значение одним сообщением. /cancel — отмена.",
        keyboards.kb_admin_settings(),
    )
    await callback.answer()


@router.message(AdminSetting.value, F.text)
async def setting_value_text(
    message: Message, state: FSMContext, ctx: AppContext
) -> None:
    data = await state.get_data()
    key = data.get("setting_key")
    if key not in SETTING_TITLES:
        await state.clear()
        await show_settings(message, ctx)
        return

    try:
        pricing_changed = await ctx.config_service.update(
            ctx.settings, key, message.text
        )
    except ConfigError as exc:
        await ctx.banners.show(
            message,
            "admin",
            f"⚠️ {exc}\n\nПопробуй ещё раз или нажми /cancel.",
        )
        return

    await state.clear()
    note = "✅ Сохранено."
    if pricing_changed or key in PRICING_KEYS:
        updated = await ctx.catalog.apply_retail_prices(force=True)
        note = f"✅ Сохранено. Цены пересчитаны: {updated} товаров."
    await ctx.banners.show(message, "admin", note)
    await show_settings(message, ctx)


@router.message(AdminSetting.value, ~F.text)
async def setting_value_non_text(message: Message, ctx: AppContext) -> None:
    await ctx.banners.show(
        message, "admin", "Отправь значение текстом, пожалуйста."
    )
