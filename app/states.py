"""Состояния FSM."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SupportState(StatesGroup):
    message = State()


class AdminReply(StatesGroup):
    text = State()


class ClientMessage(StatesGroup):
    text = State()


class AddProduct(StatesGroup):
    category = State()
    title = State()
    price = State()
    description = State()


class AddStock(StatesGroup):
    content = State()


class AdminSetting(StatesGroup):
    value = State()


class BannerUpload(StatesGroup):
    photo = State()
