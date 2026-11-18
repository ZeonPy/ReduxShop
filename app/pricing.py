"""Розничные цены ReduxShop.

Правило по умолчанию: дешёвые направления продаём с наценкой ×3, дорогие — ×2,
но не ниже 110 ₽. Цена округляется вверх до «красивого» числа,
оканчивающегося на 9: 119, 149, 199, 249, 299, 349, 399, 499, ...

Правила можно менять в админ-панели: они хранятся в базе и применяются
к каталогу одной кнопкой «Пересчитать цены».
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_PRICE = 110
CHEAP_LIMIT = 50
CHEAP_MULTIPLIER = 3
EXPENSIVE_MULTIPLIER = 2


def _round_up(raw: int) -> int:
    """Округляет цену вверх до приятного покупателю числа."""
    if raw < 200:
        step = 10
    elif raw < 500:
        step = 50
    elif raw < 1000:
        step = 100
    else:
        step = 50
    return ((raw + step - 1) // step) * step - 1


@dataclass(frozen=True, slots=True)
class PricingRules:
    min_price: int = MIN_PRICE
    cheap_limit: int = CHEAP_LIMIT
    cheap_multiplier: int = CHEAP_MULTIPLIER
    expensive_multiplier: int = EXPENSIVE_MULTIPLIER

    def price(self, wholesale: int) -> int:
        wholesale = max(1, int(wholesale))
        multiplier = (
            self.cheap_multiplier
            if wholesale <= self.cheap_limit
            else self.expensive_multiplier
        )
        return max(self.min_price, _round_up(wholesale * multiplier))

    @property
    def signature(self) -> str:
        return (
            f"nice-v2-min{self.min_price}"
            f"-x{self.cheap_multiplier}"
            f"-x{self.expensive_multiplier}"
            f"-l{self.cheap_limit}"
        )


DEFAULT_PRICING = PricingRules()

# Совместимые имена для старых импортов и тестов.
PRICING_VERSION = DEFAULT_PRICING.signature


def retail_price(wholesale: int) -> int:
    """Розничная цена по правилам по умолчанию."""
    return DEFAULT_PRICING.price(wholesale)
