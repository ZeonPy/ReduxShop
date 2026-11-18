from __future__ import annotations

import unittest

from app.constants import OrderStatus
from app.models import Category, Order, Product, Ticket, User
from app.ui import keyboards
from tests import make_config


def callbacks(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]


class KeyboardsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = make_config()
        self.category = Category(
            id=7, title="🇩🇪 Германия", products=1, min_price=110, stock=3
        )
        self.product = Product(
            id=9,
            category_id=7,
            title="Виртуальный номер · Германия",
            description="",
            price=110,
            active=True,
            category="🇩🇪 Германия",
            stock=2,
        )

    def test_main_menu_admin_button(self) -> None:
        self.assertIn("adm:panel", callbacks(keyboards.kb_main(True)))
        self.assertNotIn("adm:panel", callbacks(keyboards.kb_main(False)))

    def test_catalog_and_category_buttons(self) -> None:
        catalog = keyboards.kb_catalog(
            self.config, [self.category], page=0, pages=2
        )
        data = callbacks(catalog)
        self.assertIn("cat:7", data)
        self.assertIn("catalog:1", data)
        self.assertIn("menu", data)

        category = keyboards.kb_category(self.config, [self.product])
        self.assertIn("prod:9", callbacks(category))

    def test_product_hides_buy_without_stock(self) -> None:
        empty = Product(
            id=10,
            category_id=7,
            title="Нет в наличии",
            description="",
            price=110,
            active=True,
            category="",
            stock=0,
        )
        self.assertNotIn("buy:10", callbacks(keyboards.kb_product(empty)))
        self.assertIn("buy:9", callbacks(keyboards.kb_product(self.product)))

        provider = Product(
            id=11,
            category_id=7,
            title="Виртуальный номер · Австрия",
            description="",
            price=149,
            active=True,
            category="🇦🇹 Австрия",
            stock=0,
            provider_id=50,
        )
        self.assertIn("buy:11", callbacks(keyboards.kb_product(provider)))
        self.assertIn(
            "buy:11", callbacks(keyboards.kb_product(provider, provider_ready=True))
        )
        self.assertNotIn(
            "buy:11", callbacks(keyboards.kb_product(provider, provider_ready=False))
        )
        self.assertFalse(provider.can_buy(provider_ready=False))
        self.assertTrue(provider.can_buy(provider_ready=True))

    def test_payment_switches_with_auto_payment(self) -> None:
        self.assertIn("paid:3", callbacks(keyboards.kb_payment(3, False)))
        self.assertIn("pay:3", callbacks(keyboards.kb_payment(3, True)))

    def test_admin_panel_has_settings_and_banners(self) -> None:
        data = callbacks(keyboards.kb_admin_panel())
        self.assertIn("adm:settings", data)
        self.assertIn("adm:banners", data)

    def test_admin_settings_buttons(self) -> None:
        data = callbacks(keyboards.kb_admin_settings())
        for callback in (
            "adm:set:shop_name",
            "adm:set:shop_link",
            "adm:set:payment_details",
            "adm:set:min_price",
            "adm:set:cheap_limit",
            "adm:set:cheap_multiplier",
            "adm:set:expensive_multiplier",
            "adm:set:deliverability",
            "adm:reprice",
            "adm:smsfast",
            "adm:banners",
            "adm:set:payment_card",
        ):
            self.assertIn(callback, data)

        smsfast = callbacks(keyboards.kb_smsfast(self.config))
        for callback in (
            "adm:smsfast:sync",
            "adm:smsfast:balance",
            "adm:set:smsfast_api_key",
            "adm:set:smsfast_service",
            "adm:smsfast:toggle",
        ):
            self.assertIn(callback, smsfast)

    def test_banner_keyboard_marks_custom(self) -> None:
        self.config.banner_file_ids["main"] = "custom-file-id"
        data = callbacks(keyboards.kb_admin_banners(self.config))
        self.assertIn("adm:banners:toggle", data)
        self.assertIn("adm:banner:main", data)
        self.assertIn("adm:banner:about", data)

    def test_admin_order_buttons_by_status(self) -> None:
        order = Order(
            id=5,
            user_id=2,
            product_id=9,
            price=110,
            status=OrderStatus.NEW,
            created_at="2026-01-01 00:00:00",
            product_title="Товар",
        )
        data = callbacks(keyboards.kb_admin_order(order))
        # Номер нельзя покупать до подтверждения оплаты, поэтому у нового
        # заказа нет кнопки выдачи — только «Отметить оплату» и «Отменить».
        self.assertNotIn("adm:deliver:5", data)
        self.assertIn("adm:markpaid:5", data)
        self.assertIn("adm:cancel:5", data)

        paid = Order(
            id=5,
            user_id=2,
            product_id=9,
            price=110,
            status=OrderStatus.PAID,
            created_at="2026-01-01 00:00:00",
            product_title="Товар",
        )
        data = callbacks(keyboards.kb_admin_order(paid))
        self.assertIn("adm:deliver:5", data)
        self.assertIn("adm:cancel:5", data)
        self.assertNotIn("adm:markpaid:5", data)

        order = Order(
            id=5,
            user_id=2,
            product_id=9,
            price=110,
            status=OrderStatus.DELIVERED,
            created_at="2026-01-01 00:00:00",
            product_title="Товар",
        )
        data = callbacks(keyboards.kb_admin_order(order))
        self.assertNotIn("adm:deliver:5", data)
        self.assertIn("adm:cmsg:2", data)

    def test_cancelled_provider_order_offers_manual_delivery(self) -> None:
        failed = Order(
            id=5,
            user_id=2,
            product_id=9,
            price=110,
            status=OrderStatus.CANCELLED,
            created_at="2026-01-01 00:00:00",
            product_title="Товар",
            provider="smsfast",
            provider_id="act-1",
            provider_error="таймаут",
        )
        data = callbacks(keyboards.kb_admin_order(failed))
        self.assertIn("adm:manual:5", data)
        self.assertNotIn("adm:deliver:5", data)
        self.assertNotIn("adm:cancel:5", data)

        manual_cancel = Order(
            id=5,
            user_id=2,
            product_id=9,
            price=110,
            status=OrderStatus.CANCELLED,
            created_at="2026-01-01 00:00:00",
            product_title="Товар",
        )
        self.assertNotIn(
            "adm:manual:5", callbacks(keyboards.kb_admin_order(manual_cancel))
        )

        failed_notify = callbacks(keyboards.kb_order_failed(5))
        self.assertIn("adm:manual:5", failed_notify)
        self.assertIn("adm:order:5", failed_notify)

    def test_admin_ticket_buttons(self) -> None:
        ticket = Ticket(
            id=4,
            user_id=2,
            status="open",
            created_at="2026-01-01 00:00:00",
            updated_at="2026-01-01 00:00:00",
        )
        data = callbacks(keyboards.kb_admin_ticket(ticket))
        self.assertIn("adm:treply:4", data)
        self.assertIn("adm:tclose:4", data)

    def test_client_display(self) -> None:
        user = User(id=2, username="client", full_name="Клиент", created_at="")
        data = callbacks(keyboards.kb_admin_client(user.id))
        self.assertIn("adm:cmsg:2", data)


if __name__ == "__main__":
    unittest.main()
