"""Мелкие помощники хендлеров."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message


def paginate(total: int, size: int, page: int) -> tuple[int, int, int]:
    """Возвращает (всего страниц, текущая страница, offset)."""
    pages = max(1, (total + size - 1) // size)
    page = min(max(page, 0), pages - 1)
    return pages, page, page * size


def chat_id(event: Message | CallbackQuery) -> int:
    if isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            return event.message.chat.id
        return event.from_user.id
    return event.chat.id


def telegram_user_line(user) -> str:
    username = f" (@{user.username})" if user.username else ""
    return f"{user.full_name or 'Без имени'}{username} · ID {user.id}"
