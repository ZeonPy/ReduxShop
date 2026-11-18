"""ReduxShop — Telegram-бот магазина виртуальных номеров.

Точка входа для Bothost и локального запуска. Вся логика — в пакете `app`.

Запуск: python bot.py
Настройки: .env рядом с этим файлом или переменные окружения Bothost.
"""

from __future__ import annotations

from app.main import main

if __name__ == "__main__":
    main()
