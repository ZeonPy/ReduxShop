from __future__ import annotations

import unittest

from app.countries import COUNTRIES
from app.pricing import (
    CHEAP_LIMIT,
    DEFAULT_DELIVERABILITY,
    MIN_PRICE,
    PRICING_VERSION,
    PricingRules,
    retail_price,
)


FULL_DELIVERY = PricingRules(deliverability=100)


class PricingTest(unittest.TestCase):
    def test_minimum_price_for_cheap_countries(self) -> None:
        self.assertEqual(retail_price(1), MIN_PRICE)
        self.assertGreaterEqual(retail_price(31), MIN_PRICE)
        self.assertGreaterEqual(retail_price(50), MIN_PRICE)
        self.assertGreaterEqual(retail_price(51), MIN_PRICE)

    def test_multiplier_depends_on_wholesale(self) -> None:
        self.assertEqual(FULL_DELIVERY.price(40), 119)  # 40 × 3 = 120 → 119
        self.assertEqual(FULL_DELIVERY.price(49), 149)  # 49 × 3 = 147 → 149
        self.assertEqual(FULL_DELIVERY.price(60), 119)  # 60 × 2 = 120 → 119
        self.assertEqual(FULL_DELIVERY.price(75), 149)  # 75 × 2 = 150 → 149

    def test_deliverability_reserve_is_included(self) -> None:
        self.assertEqual(DEFAULT_DELIVERABILITY, 85)
        rules = PricingRules(deliverability=85)
        # 100 / 0,85 = 117,65 → 118, затем наценка ×2.
        self.assertEqual(rules.reserved_cost(100), 118)
        self.assertGreater(
            rules.price(100), PricingRules(deliverability=100).price(100)
        )
        self.assertEqual(rules.price(40), 149)

    def test_rounding_ends_with_nine(self) -> None:
        for wholesale in (1, 31, 40, 49, 60, 75, 100, 200, 500, 1000):
            price = retail_price(wholesale)
            self.assertTrue(
                price == MIN_PRICE or price % 10 == 9, (wholesale, price)
            )
            self.assertGreaterEqual(price, MIN_PRICE)

    def test_cheap_limit_is_inclusive(self) -> None:
        self.assertEqual(CHEAP_LIMIT, 50)
        self.assertGreaterEqual(retail_price(50), 110)
        self.assertGreaterEqual(retail_price(51), 110)

    def test_all_catalog_countries_have_retail_price(self) -> None:
        self.assertEqual(len(COUNTRIES), 193)
        for country in COUNTRIES:
            price = retail_price(country.wholesale)
            self.assertGreaterEqual(price, MIN_PRICE, country.name)
            self.assertTrue(
                price == MIN_PRICE or price % 10 == 9, country.name
            )
        self.assertEqual(
            PRICING_VERSION, "nice-v3-min110-x3-x2-l50-d85"
        )

    def test_known_country_prices(self) -> None:
        by_name = {country.name: country for country in COUNTRIES}
        self.assertEqual(retail_price(by_name["Германия"].wholesale), 119)
        self.assertEqual(retail_price(by_name["Великобритания"].wholesale), 110)
        self.assertEqual(retail_price(by_name["США"].wholesale), 149)
        self.assertEqual(retail_price(by_name["Япония"].wholesale), 179)
        self.assertEqual(retail_price(by_name["Казахстан"].wholesale), 179)
        self.assertEqual(retail_price(by_name["Австрия"].wholesale), 149)
        self.assertEqual(retail_price(by_name["Бельгия"].wholesale), 349)
        self.assertEqual(retail_price(by_name["Турция"].wholesale), 499)


if __name__ == "__main__":
    unittest.main()
