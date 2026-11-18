"""Уведомления админов и клиентов.

Единственная точка, через которую бот пишет людям вне обработки экрана.
Все сообщения идут с баннером — включая служебные уведомления.
"""

from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardMarkup

from app.runtime import RuntimeConfig
from app.ui.banners import BannerService

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot, settings: RuntimeConfig, banners: BannerService) -> None:
        self._bot = bot
        self._settings = settings
        self._banners = banners

    async def to_admins(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        key: str = "admin",
    ) -> int:
        if not self._settings.admin_ids:
            logger.warning("ADMIN_IDS пуст: уведомление не отправлено. %s", text)
            return 0

        delivered = 0
        for admin_id in self._settings.admin_ids:
            try:
                await self._banners.send(
                    admin_id, key, text, reply_markup=reply_markup
                )
                delivered += 1
            except Exception as exc:  # сеть, блокировка бота и т.п.
                logger.warning("Не смог написать админу %s: %s", admin_id, exc)
        return delivered

    async def to_user(
        self,
        user_id: int,
        text: str,
        key: str = "main",
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        try:
            sent = await self._banners.send(
                user_id,
                key,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return sent is not None
        except Exception as exc:
            logger.warning("Не смог написать клиенту %s: %s", user_id, exc)
            return False
