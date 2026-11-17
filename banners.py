"""Баннеры экранов ReduxShop: 3D-градиентные картинки из папки assets.

Каждый экран бота отправляется фотографией с подписью и кнопками.
После первой отправки Telegram возвращает file_id, и дальше баннер
переиспользуется без повторной загрузки файла.
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

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

EMPTY_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[])

BANNERS = {
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

# В подпись к фото Telegram пускает не больше 1024 символов.
CAPTION_LIMIT = 1000

# Короткая подпись, если полный текст не влезает в caption.
SHORT_CAPTIONS = {
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

_FILE_IDS: dict[str, str] = {}


def banner_media(key: str) -> FSInputFile | str | None:
    """Возвращает file_id, если баннер уже загружали, иначе локальный файл."""
    cached = _FILE_IDS.get(key)
    if cached:
        return cached
    name = BANNERS.get(key)
    if not name:
        return None
    path = ASSETS_DIR / name
    if not path.is_file():
        return None
    return FSInputFile(path, filename=name)


def _remember(key: str, sent: Message | None) -> None:
    if sent is not None and sent.photo:
        _FILE_IDS[key] = sent.photo[-1].file_id


async def _send_text(message: Message, text: str, reply_markup) -> None:
    try:
        await message.answer(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        logging.warning("Не смог отправить текст экрана: %s", exc)


async def _send_photo(
    message: Message,
    media: FSInputFile | str,
    key: str,
    caption: str,
    reply_markup=None,
) -> None:
    try:
        sent = await message.answer_photo(
            media, caption=caption, reply_markup=reply_markup
        )
        _remember(key, sent)
    except TelegramBadRequest as exc:
        logging.warning("Не смог отправить баннер %s: %s", key, exc)


async def send_banner(
    bot,
    chat_id: int,
    key: str,
    text: str,
    reply_markup=None,
    parse_mode=None,
):
    """Отправляет любое сообщение бота фотографией с баннером.

    Если текст длинный и не влезает в подпись, сначала уходит баннер
    с короткой подписью, затем полный текст отдельным сообщением.
    """
    media = banner_media(key)
    if media is None:
        return await bot.send_message(
            chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    if len(text) <= CAPTION_LIMIT:
        try:
            sent = await bot.send_photo(
                chat_id,
                media,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            _remember(key, sent)
            return sent
        except TelegramBadRequest as exc:
            logging.warning("Не смог отправить баннер %s: %s", key, exc)
            return await bot.send_message(
                chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode
            )

    try:
        sent = await bot.send_photo(
            chat_id, media, caption=SHORT_CAPTIONS.get(key, "ReduxShop")
        )
        _remember(key, sent)
    except TelegramBadRequest as exc:
        logging.warning("Не смог отправить баннер %s: %s", key, exc)
    return await bot.send_message(
        chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode
    )


async def show_screen(
    event: Message | CallbackQuery,
    key: str,
    text: str,
    reply_markup=None,
) -> None:
    """Показывает экран с баннером и подписью.

    В callback-е переиспользует текущее сообщение: меняет фото или текст,
    чтобы чат не забивался дублями. Если текст длиннее подписи Telegram,
    сначала уходит баннер с короткой подписью, затем полный текст.
    """
    is_callback = isinstance(event, CallbackQuery)
    message = event.message if is_callback else event
    if not isinstance(message, Message):
        # Старое сообщение нельзя редактировать — отправляем экран заново.
        chat = getattr(message, "chat", None) or getattr(event, "from_user", None)
        bot = getattr(event, "bot", None)
        if bot is not None and chat is not None:
            await send_banner(
                bot, chat.id, key, text, reply_markup=reply_markup
            )
        return

    media = banner_media(key)

    if media is None:
        if is_callback:
            if message.photo:
                # Баннера нет — заменяем фото обычным текстом.
                try:
                    await message.delete()
                except TelegramBadRequest:
                    pass
                await _send_text(message, text, reply_markup)
                return
            try:
                await message.edit_text(
                    text,
                    reply_markup=(
                        reply_markup if reply_markup is not None else EMPTY_KEYBOARD
                    ),
                )
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return
                logging.debug("Не смог отредактировать экран: %s", exc)
                await _send_text(message, text, reply_markup)
        else:
            await _send_text(message, text, reply_markup)
        return

    if len(text) > CAPTION_LIMIT:
        if is_callback:
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
        await _send_photo(message, media, key, SHORT_CAPTIONS.get(key, "ReduxShop"))
        await _send_text(message, text, reply_markup)
        return

    if is_callback and message.photo:
        try:
            sent = await message.edit_media(
                InputMediaPhoto(media=media, caption=text),
                reply_markup=(
                    reply_markup if reply_markup is not None else EMPTY_KEYBOARD
                ),
            )
            if isinstance(sent, Message):
                _remember(key, sent)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
            logging.debug("Не смог заменить баннер: %s", exc)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
    elif is_callback:
        # Текстовый экран заменяем баннером, чтобы не копить сообщения.
        try:
            await message.delete()
        except TelegramBadRequest:
            pass

    try:
        sent = await message.answer_photo(
            media, caption=text, reply_markup=reply_markup
        )
        _remember(key, sent)
    except TelegramBadRequest as exc:
        logging.warning("Не смог отправить баннер %s: %s", key, exc)
        await _send_text(message, text, reply_markup)
