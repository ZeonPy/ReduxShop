from __future__ import annotations

import unittest

from app.ui.banners import BannerService
from tests import make_config


class BannerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = make_config()
        self.service = BannerService(bot=object(), config=self.config)

    def test_default_banner_uses_asset_file(self) -> None:
        media = self.service._media("main")
        self.assertIsNotNone(media)
        self.assertFalse(isinstance(media, str))

    def test_custom_file_id_wins(self) -> None:
        self.config.banner_file_ids["main"] = "custom-file-id"
        self.assertEqual(self.service._media("main"), "custom-file-id")

    def test_disabled_banners_return_no_media(self) -> None:
        self.config.banners_enabled = False
        self.assertIsNone(self.service._media("main"))

    def test_unknown_screen_has_no_banner(self) -> None:
        self.assertIsNone(self.service._media("unknown"))

    def test_banner_images_exist(self) -> None:
        self.config.banners_enabled = True
        for key in (
            "main",
            "catalog",
            "country",
            "product",
            "payment",
            "orders",
            "support",
            "about",
            "admin",
        ):
            self.assertIsNotNone(self.service._media(key), key)


if __name__ == "__main__":
    unittest.main()
