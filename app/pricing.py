"""Розничные цены ReduxShop.

Правило по умолчанию: дешёвые направления продаём с наценкой ×3, дорогие — ×2,
но не ниже 110 ₽. Цена округляется вверх до «красивого» числа,
оканчивающегося на 9: 119, 149, 199, 249, 299, 349, 399, 499, ...

Доставляемость SMS — доля номеров, на которые реально приходит код. Часть
активаций заканчивается без SMS, поэтому закупка делится на этот процент:
при 85% номер за 100 ₽ резервирует 118 ₽, и прибыль не съедается отказами.

Правила можно менять в админ-панели: они хранятся в базе и применяются
к каталогу одной кнопкой «Пересчитать цены».
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_PRICE = 110
CHEAP_LIMIT = 50
CHEAP_MULTIPLIER = 3
EXPENSIVE_MULTIPLIER = 2
DEFAULT_DELIVERABILITY = 85


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
    deliverability: int = DEFAULT_DELIVERABILITY

    def reserved_cost(self, wholesale: int) -> int:
        """Закупка с резервом на недоставленные SMS.

        При доставляемости 85% и закупке 100 ₽ одна успешная активация
        должна покрыть 100/0,85 = 117,65 ₽ расходов.
        """
        base = max(1, int(wholesale))
        percent = min(100, max(1, int(self.deliverability)))
        return max(base, math.ceil(base * 100 / percent))

    def price(self, wholesale: int) -> int:
        base = max(1, int(wholesale))
        multiplier = (
            self.cheap_multiplier
            if base <= self.cheap_limit
            else self.expensive_multiplier
        )
        return max(
            self.min_price, _round_up(self.reserved_cost(base) * multiplier)
        )

    @property
    def signature(self) -> str:
        return (
            f"nice-v3-min{self.min_price}"
            f"-x{self.cheap_multiplier}"
            f"-x{self.expensive_multiplier}"
            f"-l{self.cheap_limit}"
            f"-d{self.deliverability}"
        )


DEFAULT_PRICING = PricingRules()

# Совместимые имена для старых импортов и тестов.
PRICING_VERSION = DEFAULT_PRICING.signature


def retail_price(wholesale: int) -> int:
    """Розничная цена по правилам по умолчанию."""
    return DEFAULT_PRICING.price(wholesale)
