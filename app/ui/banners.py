"""Баннеры экранов ReduxShop.

Каждое сообщение бота уходит фотографией с подписью и кнопками. После первой
отправки Telegram возвращает file_id, и дальше баннер переиспользуется без
повторной загрузки файла.

Класс `BannerService` не хранит глобальное состояние: его можно создать
в тестах с другим каталогом ассетов или с фейковым ботом.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from app.runtime import RuntimeConfig

logger = logging.getLogger(__name__)

EMPTY_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[])

BANNERS: dict[str, str] = {
    "main": "main.jpg",
    "catalog": "catalog.jpg",
    "country": "country.jpg",
    "product": "product.jpg",
    "payment": "payment.jpg",
    "orders": "orders.jpg",
    "support": "support.jpg",
    "about": "about.jpg",
    "admin": "admin.jpg",
}

BANNER_LABELS: dict[str, str] = {
    "main": "Главное меню",
    "catalog": "Каталог",
    "country": "Страна",
    "product": "Товар",
    "payment": "Оплата",
    "orders": "Заказы",
    "support": "Поддержка",
    "about": "О магазине",
    "admin": "Админ-панель",
}

# В подпись к фото Telegram пускает не больше 1024 символов.
CAPTION_LIMIT = 1000

SHORT_CAPTIONS: dict[str, str] = {
    "main": "ReduxShop",
    "catalog": "🛍 ReduxShop · Каталог",
    "country": "🌍 ReduxShop · Страна",
    "product": "📱 ReduxShop · Товар",
    "payment": "💳 ReduxShop · Оплата",
    "orders": "📦 ReduxShop · Заказы",
    "support": "🆘 ReduxShop · Поддержка",
    "about": "ℹ️ ReduxShop",
    "admin": "🛠 ReduxShop · Админка",
}


class BannerService:
    """Отправляет и редактирует экраны с баннерами."""

    def __init__(self, bot, config: RuntimeConfig) -> None:
        self._bot = bot
        self._config = config
        self._assets_dir = Path(config.assets_dir)
        self._file_ids: dict[str, str] = {}
        # Последние сообщения бота в каждом чате: перед новым экраном
        # удаляем их, чтобы чат не засорялся историей.
        self._recent: dict[int, list[int]] = {}

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    async def send(
        self,
        chat_id: int,
        key: str,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
    ) -> Message | None:
        """Отправляет новое сообщение с баннером."""
        await self._cleanup(chat_id)
        media = self._media(key)
        if media is None:
            return await self._send_text(chat_id, text, reply_markup, parse_mode)

        if len(text) <= CAPTION_LIMIT:
            try:
                sent = await self._bot.send_photo(
                    chat_id,
                    media,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                self._remember(key, sent)
                self._track(chat_id, sent)
                return sent
            except TelegramBadRequest as exc:
                logger.warning("Не смог отправить баннер %s: %s", key, exc)
                return await self._send_text(chat_id, text, reply_markup, parse_mode)

        await self._send_short_photo(chat_id, key, media)
        return await self._send_text(chat_id, text, reply_markup, parse_mode)

    async def show(
        self,
        event: Message | CallbackQuery,
        key: str,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
    ) -> Message | None:
        """Показывает экран, переиспользуя сообщение callback'а."""
        if isinstance(event, CallbackQuery):
            return await self._show_in_callback(event, key, text, reply_markup, parse_mode)

        return await self.send(
            event.chat.id, key, text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _media(self, key: str) -> FSInputFile | str | None:
        if not self._config.banners_enabled:
            return None
        custom = self._config.banner_file_ids.get(key)
        if custom:
            return custom
        cached = self._file_ids.get(key)
        if cached:
            return cached
        name = BANNERS.get(key)
        if not name:
            return None
        path = self._assets_dir / name
        if not path.is_file():
            return None
        return FSInputFile(path, filename=name)

    def _remember(self, key: str, sent: Message | None) -> None:
        if sent is not None and sent.photo:
            self._file_ids[key] = sent.photo[-1].file_id

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        parse_mode: str | None,
    ) -> Message | None:
        try:
            sent = await self._bot.send_message(
                chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            self._track(chat_id, sent)
            return sent
        except TelegramBadRequest as exc:
            logger.warning("Не смог отправить текст экрана: %s", exc)
            return None

    async def _send_short_photo(self, chat_id: int, key: str, media) -> None:
        try:
            sent = await self._bot.send_photo(
                chat_id, media, caption=SHORT_CAPTIONS.get(key, "ReduxShop")
            )
            self._remember(key, sent)
            self._track(chat_id, sent)
        except TelegramBadRequest as exc:
            logger.warning("Не смог отправить баннер %s: %s", key, exc)

    async def _show_in_callback(
        self,
        callback: CallbackQuery,
        key: str,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        parse_mode: str | None,
    ) -> Message | None:
        message = callback.message
        if not isinstance(message, Message):
            return await self.send(
                callback.from_user.id,
                key,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )

        media = self._media(key)
        if media is None:
            return await self._replace_with_text(message, text, reply_markup)

        if len(text) > CAPTION_LIMIT:
            await self._delete(message)
            await self.send(
                message.chat.id,
                key,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return None

        if message.photo:
            try:
                sent = await message.edit_media(
                    InputMediaPhoto(media=media, caption=text, parse_mode=parse_mode),
                    reply_markup=(
                        reply_markup if reply_markup is not None else EMPTY_KEYBOARD
                    ),
                )
                if isinstance(sent, Message):
                    self._remember(key, sent)
                    self._track(chat_id, sent)
                return sent if isinstance(sent, Message) else None
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return None
                logger.debug("Не смог заменить баннер: %s", exc)
            await self._delete(message)

        elif message.text or message.caption:
            await self._delete(message)

        try:
            sent = await message.answer_photo(
                media,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            self._remember(key, sent)
            self._track(message.chat.id, sent)
            return sent
        except TelegramBadRequest as exc:
            logger.warning("Не смог отправить баннер %s: %s", key, exc)
            return await self._send_text(
                message.chat.id, text, reply_markup, parse_mode
            )

    async def _replace_with_text(
        self,
        message: Message,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> Message | None:
        if message.photo:
            # Баннера нет — заменяем фото обычным текстом.
            await self._delete(message)
            return await self._send_text(
                message.chat.id, text, reply_markup, parse_mode=None
            )
        try:
            sent = await message.edit_text(
                text,
                reply_markup=(
                    reply_markup if reply_markup is not None else EMPTY_KEYBOARD
                ),
            )
            if isinstance(sent, Message):
                self._track(message.chat.id, sent)
            return sent if isinstance(sent, Message) else None
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return None
            logger.debug("Не смог отредактировать экран: %s", exc)
            return await self._send_text(
                message.chat.id, text, reply_markup, parse_mode=None
            )

    def _track(self, chat_id: int, message: Message | None) -> None:
        if message is None or not self._config.clean_chat:
            return
        ids = self._recent.setdefault(chat_id, [])
        if message.message_id not in ids:
            ids.append(message.message_id)
        del ids[:-4]

    async def _cleanup(self, chat_id: int) -> None:
        if not self._config.clean_chat:
            return
        ids = self._recent.pop(chat_id, [])
        for message_id in ids:
            try:
                await self._bot.delete_message(chat_id, message_id)
            except TelegramBadRequest:
                pass
            except Exception as exc:  # сеть/права — не ломаем отправку
                logger.debug("Не смог удалить сообщение %s: %s", message_id, exc)

    @staticmethod
    async def _delete(message: Message) -> None:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
