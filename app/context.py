"""Контейнер зависимостей приложения."""

from __future__ import annotations

from dataclasses import dataclass

from app.db import Database
from app.runtime import RuntimeConfig
from app.services.bootstrap import CatalogService
from app.services.config import ConfigService
from app.services.notifications import Notifier
from app.services.orders import OrderService
from app.services.payments import PaymentService
from app.services.tickets import TicketService
from app.ui.banners import BannerService


@dataclass(slots=True)
class AppContext:
    settings: RuntimeConfig
    db: Database
    bot: object
    banners: BannerService
    notifier: Notifier
    catalog: CatalogService
    orders: OrderService
    payments: PaymentService
    tickets: TicketService
    config_service: ConfigService

    @classmethod
    def build(
        cls,
        settings: RuntimeConfig,
        db: Database,
        bot,
        config_service: ConfigService,
    ) -> "AppContext":
        banners = BannerService(bot, settings)
        notifier = Notifier(bot, settings, banners)
        return cls(
            settings=settings,
            db=db,
            bot=bot,
            banners=banners,
            notifier=notifier,
            catalog=CatalogService(db, settings),
            orders=OrderService(db, notifier),
            payments=PaymentService(bot, settings),
            tickets=TicketService(db),
            config_service=config_service,
        )
