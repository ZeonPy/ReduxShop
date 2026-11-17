"""Баннеры экранов ReduxShop: 3D-градиентные картинки из папки assets.

Каждый экран бота отправляется фотографией с подписью и кнопками.
После первой отправки Telegram возвращает file_id, и дальше баннер
переиспользуется без повторной загрузки файла.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

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


async def show_screen(
    event: Message | CallbackQuery,
    key: str,
    text: str,
    reply_markup=None,
) -> None:
    """Показывает экран с баннером и подписью.

    В callback-е переиспользует текущее сообщение: меняет фото или текст,
    чтобы чат не забивался дублями. Длинные тексты (история обращений,
    статистика) отправляются без баннера — Telegram не пустит их в подпись.
    """
    is_callback = isinstance(event, CallbackQuery)
    message = event.message if is_callback else event
    if not isinstance(message, Message):
        return

    media = banner_media(key) if len(text) <= CAPTION_LIMIT else None

    if media is None:
        if is_callback:
            if message.photo:
                # Длинный текст не влезает в подпись — заменяем фото текстом,
                # чтобы экран оставался одним сообщением.
                try:
                    await message.delete()
                except TelegramBadRequest:
                    pass
                await _send_text(message, text, reply_markup)
                return
            try:
                await message.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return
                logging.debug("Не смог отредактировать экран: %s", exc)
                await _send_text(message, text, reply_markup)
        else:
            await _send_text(message, text, reply_markup)
        return

    if is_callback and message.photo:
        try:
            sent = await message.edit_media(
                InputMediaPhoto(media=media, caption=text),
                reply_markup=reply_markup,
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
