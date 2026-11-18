"""Настройки приложения.

Единственное место, где читаются переменные окружения. Остальной код
получает готовый immutable `Settings` и не трогает `os.environ`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app import __version__

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
DEFAULT_ADMIN_ID = 8147109580


class ConfigurationError(RuntimeError):
    """Конфигурация не позволяет запустить бота."""


def _load_env_file(path: Path) -> None:
    """Загружает .env, не перетирая уже заданные переменные окружения."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids = {
        int(part.strip())
        for part in raw.replace(";", ",").split(",")
        if part.strip().isdigit()
    }
    return frozenset(ids or {DEFAULT_ADMIN_ID})


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    shop_name: str
    shop_link: str
    currency: str
    payment_details: str
    payment_provider_token: str
    payment_currency: str
    proxy_url: str
    data_dir: Path
    db_path: Path
    app_version: str = __version__

    @property
    def auto_payment_enabled(self) -> bool:
        return bool(self.payment_provider_token)

    @property
    def assets_dir(self) -> Path:
        return BASE_DIR / "assets"

    @property
    def public_payment_details(self) -> str:
        details = self.payment_details.strip()
        if not details or "УКАЖИ" in details.upper():
            return "Реквизиты уточни в поддержке — нажми «🆘 Поддержка»."
        return details

    def is_admin(self, user_id: int | None) -> bool:
        return user_id in self.admin_ids

    def validate(self) -> None:
        if not self.bot_token or "ВСТАВЬ" in self.bot_token.upper():
            raise ConfigurationError(
                "Не найден токен бота. Заполни BOT_TOKEN=... в .env "
                "или в переменных окружения Bothost."
            )


def load_settings() -> Settings:
    """Собирает настройки из окружения и .env рядом с проектом."""
    _load_env_file(ENV_FILE)

    data_dir = os.getenv("DATA_DIR", "").strip()
    if not data_dir:
        data_dir = "/app/data" if os.path.isdir("/app/data") else str(BASE_DIR)

    proxy_url = os.getenv("PROXY_URL", "").strip()
    if os.getenv("BOT_ID"):
        # На Bothost локальный прокси с компьютера недоступен.
        proxy_url = ""

    db_path = os.getenv("DB_PATH", "").strip() or str(Path(data_dir) / "shop.db")

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        shop_name=os.getenv("SHOP_NAME", "ReduxShop").strip() or "ReduxShop",
        shop_link=os.getenv("SHOP_LINK", "https://t.me/reduxstore").strip(),
        currency=os.getenv("CURRENCY", "₽").strip() or "₽",
        payment_details=os.getenv("PAYMENT_DETAILS", "+79631969503")
        .replace("\\n", "\n")
        .strip()
        or "+79631969503",
        payment_provider_token=os.getenv("PAYMENT_PROVIDER_TOKEN", "").strip(),
        payment_currency=os.getenv("PAYMENT_CURRENCY", "RUB").strip() or "RUB",
        proxy_url=proxy_url,
        data_dir=Path(data_dir),
        db_path=Path(db_path),
    )
