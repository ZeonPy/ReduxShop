"""Middleware: зависимости в хендлерах и защита админ-роутеров."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.config import Settings
from app.context import AppContext
from app.runtime import RuntimeConfig
from app.ui import keyboards

logger = logging.getLogger(__name__)


class ContextMiddleware(BaseMiddleware):
    """Кладёт AppContext в data и обновляет профиль пользователя."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["ctx"] = self._ctx
        message: Message | None = None
        if isinstance(event, Update):
            message = event.message or event.edited_message
        elif isinstance(event, Message):
            message = event
        if message is not None and message.from_user is not None:
            user = message.from_user
            await self._ctx.db.users.upsert(
                user.id, user.username, user.full_name or ""
            )
        return await handler(event, data)


class AdminMiddleware(BaseMiddleware):
    """Не пускает в админ-роутеры никого, кроме ADMIN_IDS."""

    def __init__(self, settings: RuntimeConfig) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if self._settings.is_admin(user.id if user else None):
            return await handler(event, data)

        ctx: AppContext | None = data.get("ctx")
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Нет доступа", show_alert=True)
        elif ctx is not None:
            await ctx.banners.show(
                event,
                "main",
                "⛔ Эта команда доступна только администраторам.",
                keyboards.kb_main(False),
            )
        logger.warning(
            "Отклонён доступ в админку: user=%s",
            getattr(user, "id", None),
        )
        return None
