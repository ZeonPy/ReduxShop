"""Настройки ReduxShop-бота. Значения читаются из .env рядом с bot.py."""

from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")


def _load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env(ENV_FILE)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(part.strip())
    for part in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",")
    if part.strip().isdigit()
} or {8147109580}
SHOP_NAME = os.getenv("SHOP_NAME", "ReduxShop").strip() or "ReduxShop"
SHOP_LINK = os.getenv("SHOP_LINK", "https://t.me/reduxstore").strip()
CURRENCY = os.getenv("CURRENCY", "₽").strip() or "₽"

# Розничная наценка на цены каталога. 2.0 — продаём в два раза дороже закупки.
try:
    PRICE_MULTIPLIER = float(os.getenv("PRICE_MULTIPLIER", "2").replace(",", "."))
except ValueError:
    PRICE_MULTIPLIER = 2.0
if PRICE_MULTIPLIER <= 0:
    PRICE_MULTIPLIER = 2.0
PAYMENT_DETAILS = (
    os.getenv("PAYMENT_DETAILS", "+79631969503")
    .replace("\\n", "\n")
    .strip()
    or "+79631969503"
)
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "").strip()
PAYMENT_CURRENCY = os.getenv("PAYMENT_CURRENCY", "RUB").strip() or "RUB"

# Прокси для Telegram API. Пусто — подключаться напрямую.
# Пример: http://127.0.0.1:10810 или socks5://127.0.0.1:1080
PROXY_URL = os.getenv("PROXY_URL", "").strip()
# На Bothost прокси не нужен и локальный адрес там только помешает.
if os.getenv("BOT_ID"):
    PROXY_URL = ""

# Каталог для постоянного хранения базы (Bothost монтирует /app/data).
# Локально база лежит рядом с bot.py.
DATA_DIR = os.getenv("DATA_DIR", "").strip()
if not DATA_DIR:
    DATA_DIR = "/app/data" if os.path.isdir("/app/data") else BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH", "").strip() or os.path.join(DATA_DIR, "shop.db")
