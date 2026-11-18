"""Админ: SMSFast, баланс, сервис и синхронизация цен."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.context import AppContext
from app.services.smsfast import SmsFastError
from app.ui import keyboards, texts

logger = logging.getLogger(__name__)
router = Router(name="admin_smsfast")


async def show_smsfast(
    event: CallbackQuery,
    ctx: AppContext,
    *,
    balance: float | None = None,
    note: str | None = None,
) -> None:
    status = await ctx.catalog.provider_status()
    text = texts.smsfast_admin_text(
        ctx.settings,
        countries=status.countries,
        mapped=status.mapped,
        with_cost=status.with_cost,
        last_sync=status.last_sync,
        balance=balance,
        delivered=status.delivered,
        failed=status.failed,
        deliverability=status.deliverability,
    )
    if note:
        text = f"{note}\n\n{text}"
    await ctx.banners.show(
        event, "admin", text, keyboards.kb_smsfast(ctx.settings)
    )


@router.callback_query(F.data == "adm:smsfast")
async def cb_smsfast(
    callback: CallbackQuery, state: FSMContext, ctx: AppContext
) -> None:
    await state.clear()
    await show_smsfast(callback, ctx)
    await callback.answer()


@router.callback_query(F.data == "adm:smsfast:balance")
async def cb_smsfast_balance(callback: CallbackQuery, ctx: AppContext) -> None:
    if not ctx.settings.smsfast_ready:
        await callback.answer(
            "SMSFast не настроен: добавь API-ключ.", show_alert=True
        )
        return
    await callback.answer("Проверяю баланс…")
    try:
        balance = await ctx.smsfast.balance()
    except SmsFastError as exc:
        await show_smsfast(callback, ctx, note=f"⚠️ {exc}")
        return
    await show_smsfast(callback, ctx, balance=balance)


@router.callback_query(F.data == "adm:smsfast:sync")
async def cb_smsfast_sync(callback: CallbackQuery, ctx: AppContext) -> None:
    if not ctx.settings.smsfast_ready:
        await callback.answer(
            "SMSFast не настроен: добавь API-ключ.", show_alert=True
        )
        return
    await callback.answer("Синхронизирую цены…")
    try:
        result = await ctx.catalog.sync_provider(ctx.smsfast)
    except SmsFastError as exc:
        await show_smsfast(callback, ctx, note=f"⚠️ Синхронизация не удалась: {exc}")
        return
    except Exception as exc:
        logger.exception("SMSFast: сбой синхронизации")
        await show_smsfast(callback, ctx, note=f"⚠️ Сбой синхронизации: {exc}")
        return

    note = (
        "✅ Синхронизация SMSFast\n"
        f"Сервис: {result.service}\n"
        f"Стран сопоставлено: {result.matched} из {result.countries}\n"
        f"Цен получено: {result.priced}\n"
        f"Товаров обновлено: {result.updated}\n"
        f"Без mapping: {result.missing_map} · без цены: {result.missing_price}"
    )
    if result.balance is not None:
        note += f"\nБаланс: {result.balance:.2f} {ctx.settings.currency}".replace(
            ".", ","
        )
    await show_smsfast(callback, ctx, note=note)


@router.callback_query(F.data == "adm:smsfast:toggle")
async def cb_smsfast_toggle(callback: CallbackQuery, ctx: AppContext) -> None:
    await ctx.config_service.set_smsfast_enabled(
        ctx.settings, not ctx.settings.smsfast_enabled
    )
    await show_smsfast(
        callback,
        ctx,
        note=(
            "🟢 SMSFast включён."
            if ctx.settings.smsfast_enabled
            else "🔴 SMSFast выключен, автовыдача не работает."
        ),
    )
    await callback.answer()
