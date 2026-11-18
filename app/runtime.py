"""Настройки, которые можно менять из админ-панели."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import DEFAULT_SMSFAST_BASE_URL, Settings
from app.pricing import DEFAULT_PRICING, PricingRules


@dataclass(slots=True)
class RuntimeConfig:
    """Текущие настройки приложения.

    Значения из `.env` — база; то, что админ изменил в панели, лежит в БД
    и применяется поверх. Объект живёт всё время работы бота, поэтому
    изменения видны во всех хендлерах без перезапуска.
    """

    base: Settings
    shop_name: str
    shop_link: str
    currency: str
    payment_details: str
    pricing: PricingRules = DEFAULT_PRICING
    banners_enabled: bool = True
    banner_file_ids: dict[str, str] = field(default_factory=dict)
    smsfast_api_key: str = ""
    smsfast_service: str = "ot"
    smsfast_base_url: str = DEFAULT_SMSFAST_BASE_URL
    smsfast_enabled: bool = True
    smsfast_poll_interval: int = 5
    smsfast_timeout: int = 900
    clean_chat: bool = True
    payment_card: str = ""
    payment_url: str = ""

    @classmethod
    def from_settings(cls, base: Settings) -> "RuntimeConfig":
        return cls(
            base=base,
            shop_name=base.shop_name,
            shop_link=base.shop_link,
            currency=base.currency,
            payment_details=base.payment_details,
            pricing=DEFAULT_PRICING,
            smsfast_api_key=base.smsfast_api_key,
            smsfast_service=base.smsfast_service,
            smsfast_base_url=base.smsfast_base_url,
            smsfast_enabled=base.smsfast_enabled,
            smsfast_poll_interval=base.smsfast_poll_interval,
            smsfast_timeout=base.smsfast_timeout,
            clean_chat=base.clean_chat,
            payment_card=base.payment_card,
            payment_url=base.payment_url,
        )

    @property
    def public_payment_details(self) -> str:
        sbp = self.payment_details.strip()
        card = self.payment_card.strip()
        lines = [sbp] if sbp else []
        if card and card not in lines:
            lines.append(card)
        return "\n".join(lines) or self.payment_details.strip() or "+79631969503"

    # ------------------------------------------------------------------
    # Совместимый интерфейс с Settings
    # ------------------------------------------------------------------

    @property
    def admin_ids(self) -> frozenset[int]:
        return self.base.admin_ids

    @property
    def auto_payment_enabled(self) -> bool:
        return self.base.auto_payment_enabled

    @property
    def smsfast_ready(self) -> bool:
        return bool(
            self.smsfast_enabled
            and self.smsfast_api_key.strip()
            and self.smsfast_base_url.strip()
        )

    @property
    def payment_provider_token(self) -> str:
        return self.base.payment_provider_token

    @property
    def payment_currency(self) -> str:
        return self.base.payment_currency

    @property
    def assets_dir(self) -> Path:
        return self.base.assets_dir

    @property
    def data_dir(self) -> Path:
        return self.base.data_dir

    @property
    def db_path(self) -> Path:
        return self.base.db_path

    @property
    def app_version(self) -> str:
        return self.base.app_version

    def is_admin(self, user_id: int | None) -> bool:
        return self.base.is_admin(user_id)

    @property
    def pricing_signature(self) -> str:
        return self.pricing.signature

    def retail_price(self, wholesale: int) -> int:
        return self.pricing.price(wholesale)

    @property
    def smsfast_key_masked(self) -> str:
        key = self.smsfast_api_key.strip()
        if not key:
            return "не задан"
        if len(key) <= 6:
            return "•" * len(key)
        return f"{key[:3]}…{key[-3:]}"
