from __future__ import annotations

import unittest

from app.constants import OrderStatus, TicketStatus
from app.models import Order, Stats, Ticket, User
from app.ui import texts
from tests import make_config


class TextsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = make_config()
        self.order = Order(
            id=12,
            user_id=5,
            product_id=1,
            price=149,
            status=OrderStatus.NEW,
            created_at="2026-01-02 03:04:05",
            product_title="Виртуальный номер · США",
            full_name="Иван",
            username="ivan",
        )

    def test_money_and_status(self) -> None:
        self.assertEqual(texts.money(self.config, 149), "149 ₽")
        self.assertEqual(
            texts.status_label(OrderStatus.NEW), "🟡 ожидает оплаты"
        )

    def test_welcome_mentions_catalog_size(self) -> None:
        text = texts.welcome_text(self.config)
        self.assertIn("193", text)
        self.assertIn("ReduxShop", text)

    def test_payment_text_contains_requisites_and_steps(self) -> None:
        text = texts.payment_text(self.config, self.order)
        self.assertIn("+79631969503", text)
        self.assertIn("Я оплатил", text)
        self.assertIn("149 ₽", text)

    def test_payment_text_includes_card_when_set(self) -> None:
        self.config.payment_card = "+79990008877"
        text = texts.payment_text(self.config, self.order)
        self.assertIn("+79631969503", text)
        self.assertIn("+79990008877", text)

    def test_delivery_escapes_html(self) -> None:
        order = Order(
            id=1,
            user_id=1,
            product_id=1,
            price=110,
            status=OrderStatus.DELIVERED,
            created_at="",
            product_title="<b>Товар</b>",
        )
        text = texts.delivery_text(order, "<script>alert(1)</script>")
        self.assertIn("&lt;b&gt;", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)

    def test_settings_text_shows_rules_and_banners(self) -> None:
        text = texts.settings_text(
            self.config, products=193, banners_custom=2, banner_total=9
        )
        self.assertIn("Настройки магазина", text)
        self.assertIn("×3", text)
        self.assertIn("минимум 110", text)
        self.assertIn("своих 2 из 9", text)

    def test_stats_text(self) -> None:
        stats = Stats(
            users=10, orders=20, delivered=15, revenue=5000, open_tickets=2
        )
        text = texts.stats_text(self.config, stats)
        self.assertIn("5000 ₽", text)
        self.assertIn("выдано 15", text)

    def test_ticket_text(self) -> None:
        ticket = Ticket(
            id=3,
            user_id=5,
            status=TicketStatus.OPEN,
            created_at="2026-01-02 03:04:05",
            updated_at="",
            full_name="Иван",
            username="ivan",
        )
        text = texts.ticket_admin_text(ticket, [])
        self.assertIn("Обращение #3", text)
        self.assertIn("сообщений нет", text)


if __name__ == "__main__":
    unittest.main()
