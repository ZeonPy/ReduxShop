"""Общие фикстуры для тестов."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.config import Settings
from app.runtime import RuntimeConfig


def make_settings(base: Path | None = None, **overrides) -> Settings:
    root = base or Path(tempfile.mkdtemp(prefix="reduxshop-test-"))
    values = dict(
        bot_token="123456:TEST",
        admin_ids=frozenset({1}),
        shop_name="ReduxShop",
        shop_link="https://t.me/reduxstore",
        currency="₽",
        payment_details="+79631969503",
        payment_provider_token="",
        payment_currency="RUB",
        proxy_url="",
        data_dir=root,
        db_path=root / "shop.db",
    )
    values.update(overrides)
    return Settings(**values)


def make_config(base: Path | None = None, **overrides) -> RuntimeConfig:
    return RuntimeConfig.from_settings(make_settings(base, **overrides))
