"""Розничные цены ReduxShop.

Правило простое: дешёвые направления продаём с наценкой ×3, дорогие — ×2,
но не ниже 110 ₽. Цена округляется вверх до «красивого» числа:
119, 149, 199, 249, 299, 349, 399, 499, 599, …, 1349.

Закупочные цены лежат в countries_data.py, поэтому розницу всегда можно
пересчитать заново — от сохранённых цен это не зависит.
"""

from __future__ import annotations

MIN_PRICE = 110
CHEAP_LIMIT = 50
CHEAP_MULTIPLIER = 3
EXPENSIVE_MULTIPLIER = 2

# Меняйте версию, если правила цен изменились: бот один раз пересчитает каталог.
PRICING_VERSION = "nice-v1-min110"


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


def retail_price(wholesale: int) -> int:
    wholesale = max(1, int(wholesale))
    multiplier = (
        CHEAP_MULTIPLIER if wholesale <= CHEAP_LIMIT else EXPENSIVE_MULTIPLIER
    )
    return max(MIN_PRICE, _round_up(wholesale * multiplier))
