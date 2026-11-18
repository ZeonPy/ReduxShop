"""Гибкие настройки магазина: чтение, валидация и сохранение."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.config import Settings
from app.db import Database
from app.pricing import PricingRules
from app.runtime import RuntimeConfig
from app.services.smsfast import DEFAULT_SERVICE, SMSFAST_SERVICES
from app.ui.banners import BANNERS

logger = logging.getLogger(__name__)

BANNERS_ENABLED_KEY = "banners_enabled"
BANNER_PREFIX = "banner:"

TEXT_KEYS = {
    "shop_name": (2, 64),
    "shop_link": (8, 200),
    "payment_details": (2, 500),
    "payment_card": (0, 500),
    "currency": (1, 8),
}

PRICING_FIELDS = {
    "min_price": (1, 1_000_000),
    "cheap_limit": (0, 1_000_000),
    "cheap_multiplier": (1, 10),
    "expensive_multiplier": (1, 10),
    "deliverability": (1, 100),
}
PRICING_KEYS = frozenset(PRICING_FIELDS)

SMSFAST_TEXT_KEYS = {
    "smsfast_api_key": (0, 200),
    "smsfast_service": (1, 16),
    "smsfast_base_url": (10, 300),
}
SMSFAST_KEYS = frozenset(SMSFAST_TEXT_KEYS)

SETTING_TITLES = {
    "shop_name": "Название магазина",
    "shop_link": "Ссылка на канал",
    "payment_details": "Реквизиты оплаты",
    "payment_card": "💳 Карта для оплаты",
    "currency": "Валюта",
    "min_price": "Минимальная цена",
    "cheap_limit": "Порог дешёвых стран",
    "cheap_multiplier": "Наценка для дешёвых",
    "expensive_multiplier": "Наценка для дорогих",
    "deliverability": "Доставляемость SMS",
    "smsfast_api_key": "SMSFast API-ключ",
    "smsfast_service": "Сервис SMSFast",
    "smsfast_base_url": "Адрес API SMSFast",
}

SETTING_HINTS = {
    "shop_name": "2–64 символа. Например: ReduxShop",
    "shop_link": "Ссылка вида https://t.me/reduxstore",
    "payment_details": "Телефон СБП или реквизиты. Можно несколько строк.",
    "payment_card": (
        "Карта для оплаты. Можно несколько строк. Оставь пустым — только СБП."
    ),
    "currency": "Символ валюты, например ₽ или $",
    "min_price": "Целое число, не меньше 1. Например: 110",
    "cheap_limit": "Закупка до этой суммы идёт с первой наценкой",
    "cheap_multiplier": "Целое число от 1 до 10. Например: 3",
    "expensive_multiplier": "Целое число от 1 до 10. Например: 2",
    "deliverability": (
        "Процент номеров, на которые приходит SMS. 85 значит, что в цену "
        "заложен резерв: закупка делится на 0,85. Обычно 80–95."
    ),
    "smsfast_api_key": (
        "Ключ из личного кабинета SMSFast. Отправь «-», чтобы удалить ключ."
    ),
    "smsfast_service": (
        "Код сервиса: "
        + ", ".join(f"{code} — {name}" for code, name in SMSFAST_SERVICES.items())
    ),
    "smsfast_base_url": "Обычно https://smsfastapi.com/stubs/handler_api.php",
}


class ConfigError(ValueError):
    """Некорректное значение настройки."""


class ConfigService:
    def __init__(self, base: Settings, db: Database) -> None:
        self._base = base
        self._db = db

    async def load(self) -> RuntimeConfig:
        config = RuntimeConfig.from_settings(self._base)
        stored = await self._db.settings.all()

        pricing_values: dict[str, int] = {}
        for key, raw in stored.items():
            try:
                if key == BANNERS_ENABLED_KEY:
                    config.banners_enabled = raw != "0"
                elif key == "smsfast_enabled":
                    config.smsfast_enabled = raw != "0"
                elif key.startswith(BANNER_PREFIX):
                    screen = key.removeprefix(BANNER_PREFIX)
                    if screen in BANNERS and raw:
                        config.banner_file_ids[screen] = raw
                elif key in TEXT_KEYS:
                    self._apply_text(config, key, self.parse(key, raw))
                elif key in PRICING_KEYS:
                    pricing_values[key] = int(self.parse(key, raw))
                elif key in SMSFAST_TEXT_KEYS:
                    self._apply_smsfast(config, key, self.parse(key, raw))
            except (ConfigError, ValueError) as exc:
                logger.warning("Игнорирую настройку %s=%r: %s", key, raw, exc)

        if pricing_values:
            config.pricing = replace(config.pricing, **pricing_values)
        return config

    def parse(self, key: str, raw: str) -> str:
        text = raw.strip()
        if key in TEXT_KEYS:
            minimum, maximum = TEXT_KEYS[key]
            if key == "payment_details":
                text = text.replace("\\n", "\n")
            if not (minimum <= len(text) <= maximum):
                raise ConfigError(
                    f"Нужно от {minimum} до {maximum} символов."
                )
            if key == "shop_link" and not text.startswith(("http://", "https://")):
                raise ConfigError("Ссылка должна начинаться с http:// или https://")
            if key == "currency" and "\n" in text:
                raise ConfigError("Валюта должна быть одной строкой.")
            return text

        if key in PRICING_FIELDS:
            minimum, maximum = PRICING_FIELDS[key]
            cleaned = text.replace(" ", "").replace("_", "")
            if not cleaned.isdigit():
                raise ConfigError("Нужно целое число без букв и знаков.")
            value = int(cleaned)
            if not minimum <= value <= maximum:
                raise ConfigError(f"Допустимо от {minimum} до {maximum}.")
            return str(value)

        if key == "smsfast_api_key":
            if text in {"", "-", "—", "удалить"}:
                return ""
            if not (8 <= len(text) <= 200):
                raise ConfigError("Ключ SMSFast должен быть от 8 до 200 символов.")
            return text

        if key == "smsfast_service":
            code = text.lower().strip()
            if code not in SMSFAST_SERVICES:
                allowed = ", ".join(SMSFAST_SERVICES)
                raise ConfigError(f"Неизвестный сервис. Допустимо: {allowed}.")
            return code

        if key == "smsfast_base_url":
            if not text.startswith(("http://", "https://")):
                raise ConfigError("Адрес API должен начинаться с http:// или https://")
            if len(text) > 300:
                raise ConfigError("Слишком длинный адрес API.")
            return text.rstrip("?")

        raise ConfigError("Неизвестная настройка.")

    async def update(self, config: RuntimeConfig, key: str, raw: str) -> bool:
        """Сохраняет настройку. True — изменились правила цен."""
        value = self.parse(key, raw)
        await self._db.settings.set(key, value)

        if key in TEXT_KEYS:
            self._apply_text(config, key, value)
            return False
        if key in PRICING_KEYS:
            changes = {key: int(value)}
            config.pricing = replace(config.pricing, **changes)
            return True
        if key in SMSFAST_TEXT_KEYS:
            self._apply_smsfast(config, key, value)
            return False
        raise ConfigError("Неизвестная настройка.")

    async def set_banners_enabled(
        self, config: RuntimeConfig, enabled: bool
    ) -> None:
        config.banners_enabled = enabled
        await self._db.settings.set(BANNERS_ENABLED_KEY, "1" if enabled else "0")

    async def set_smsfast_enabled(
        self, config: RuntimeConfig, enabled: bool
    ) -> None:
        config.smsfast_enabled = enabled
        await self._db.settings.set("smsfast_enabled", "1" if enabled else "0")

    @staticmethod
    def _apply_smsfast(config: RuntimeConfig, key: str, value: str) -> None:
        if key == "smsfast_api_key":
            config.smsfast_api_key = value
        elif key == "smsfast_service":
            config.smsfast_service = value or DEFAULT_SERVICE
        elif key == "smsfast_base_url":
            config.smsfast_base_url = value
        else:  # pragma: no cover - защита от опечатки в ключах
            raise ConfigError("Неизвестная настройка SMSFast.")

    async def set_banner(
        self, config: RuntimeConfig, screen: str, file_id: str
    ) -> None:
        if screen not in BANNERS:
            raise ConfigError("Неизвестный экран.")
        if not file_id:
            raise ConfigError("Пустой file_id.")
        await self._db.settings.set(f"{BANNER_PREFIX}{screen}", file_id)
        config.banner_file_ids[screen] = file_id

    async def reset_banner(self, config: RuntimeConfig, screen: str) -> None:
        if screen not in BANNERS:
            raise ConfigError("Неизвестный экран.")
        await self._db.settings.delete(f"{BANNER_PREFIX}{screen}")
        config.banner_file_ids.pop(screen, None)

    @staticmethod
    def _apply_text(config: RuntimeConfig, key: str, value: str) -> None:
        if key == "shop_name":
            config.shop_name = value
        elif key == "shop_link":
            config.shop_link = value
        elif key == "payment_details":
            config.payment_details = value
        elif key == "payment_card":
            config.payment_card = value
        elif key == "currency":
            config.currency = value
        else:  # pragma: no cover - защита от опечатки в ключах
            raise ConfigError("Неизвестная текстовая настройка.")
