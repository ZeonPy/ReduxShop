"""Настройки, которые можно менять из админ-панели."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
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

    @classmethod
    def from_settings(cls, base: Settings) -> "RuntimeConfig":
        return cls(
            base=base,
            shop_name=base.shop_name,
            shop_link=base.shop_link,
            currency=base.currency,
            payment_details=base.payment_details,
            pricing=DEFAULT_PRICING,
        )

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
    def public_payment_details(self) -> str:
        details = self.payment_details.strip()
        if not details or "УКАЖИ" in details.upper():
            return "Реквизиты уточни в поддержке — нажми «🆘 Поддержка»."
        return details

    @property
    def pricing_signature(self) -> str:
        return self.pricing.signature

    def retail_price(self, wholesale: int) -> int:
        return self.pricing.price(wholesale)
