"""Сборка и запуск приложения."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app import __version__
from app.config import ConfigurationError, Settings, load_settings
from app.context import AppContext
from app.db import Database
from app.handlers import common, fallback, orders, support
from app.handlers import catalog as catalog_handlers
from app.handlers.admin import clients as admin_clients
from app.handlers.admin import banners as admin_banners
from app.handlers.admin import orders as admin_orders
from app.handlers.admin import panel as admin_panel
from app.handlers.admin import products as admin_products
from app.handlers.admin import settings as admin_settings
from app.handlers.admin import smsfast as admin_smsfast
from app.handlers.admin import tickets as admin_tickets
from app.handlers.errors import router as errors_router
from app.middlewares import AdminMiddleware, ChatCleanupMiddleware, ContextMiddleware
from app.services.config import ConfigService
from app.ui import texts

logger = logging.getLogger(__name__)

ADMIN_ROUTERS = (
    admin_panel.router,
    admin_orders.router,
    admin_tickets.router,
    admin_clients.router,
    admin_products.router,
    admin_settings.router,
    admin_smsfast.router,
    admin_banners.router,
)


def build_dispatcher(ctx: AppContext) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.update.outer_middleware(ContextMiddleware(ctx))
    dp.update.outer_middleware(ChatCleanupMiddleware())

    dp.include_router(common.router)
    dp.include_router(catalog_handlers.router)
    dp.include_router(orders.router)
    dp.include_router(support.router)
    for admin_router in ADMIN_ROUTERS:
        dp.include_router(admin_router)
    dp.include_router(fallback.router)
    dp.include_router(errors_router)

    guard = AdminMiddleware(ctx.settings)
    for admin_router in ADMIN_ROUTERS:
        admin_router.message.middleware(guard)
        admin_router.callback_query.middleware(guard)

    return dp


async def _before_polling(ctx: AppContext) -> None:
    state = await ctx.catalog.ensure_ready()
    await ctx.fulfillment.resume_pending()
    me = await ctx.bot.get_me()
    logger.info("Telegram: @%s (id %s)", me.username, me.id)
    await ctx.bot.delete_webhook(drop_pending_updates=False)
    await ctx.bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="catalog", description="Каталог товаров"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="paysupport", description="Помощь по оплате"),
            BotCommand(command="id", description="Мой ID"),
        ]
    )

    if not ctx.settings.admin_ids:
        logger.warning(
            "ADMIN_IDS пуст — админ-панель и уведомления недоступны. "
            "Укажи свой ID в .env (узнать: /id)."
        )
    logger.info(
        "Автооплата %s",
        "включена (Telegram Payments)" if ctx.payments.enabled else "выключена",
    )
    logger.info("База данных: %s", ctx.settings.db_path)
    logger.info(
        "SMSFast: %s, сервис %s",
        "подключён" if ctx.settings.smsfast_ready else "не настроен",
        ctx.settings.smsfast_service,
    )
    logger.info(
        "Прайс: ×%s до %s %s, ×%s дороже, минимум %s %s (прайс %s)",
        ctx.settings.pricing.cheap_multiplier,
        ctx.settings.pricing.cheap_limit,
        ctx.settings.currency,
        ctx.settings.pricing.expensive_multiplier,
        ctx.settings.pricing.min_price,
        ctx.settings.currency,
        ctx.settings.pricing_signature,
    )
    logger.info("ReduxShop %s запущен, товаров: %s", __version__, state.products)

    await ctx.notifier.to_admins(
        texts.startup_text(
            ctx.settings,
            version=__version__,
            products=state.products,
            min_price=ctx.settings.pricing.min_price,
            cheap_limit=ctx.settings.pricing.cheap_limit,
            cheap_multiplier=ctx.settings.pricing.cheap_multiplier,
            expensive_multiplier=ctx.settings.pricing.expensive_multiplier,
            auto_payment=ctx.payments.enabled,
        ),
        key="admin",
    )


async def run(settings: Settings) -> None:
    settings.validate()
    logger.info(
        "BOT_TOKEN: bot_id=%s, длина=%s, источник=%s",
        settings.bot_id,
        len(settings.bot_token),
        settings.bot_token_source,
    )
    db = Database(settings.db_path)
    await db.connect()

    config_service = ConfigService(settings, db)
    runtime = await config_service.load()

    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    bot = Bot(token=settings.bot_token, session=session)
    ctx = AppContext.build(runtime, db, bot, config_service)
    dp = build_dispatcher(ctx)

    try:
        try:
            await _before_polling(ctx)
            await dp.start_polling(bot)
        except TelegramUnauthorizedError as exc:
            raise ConfigurationError(
                "Telegram отклонил BOT_TOKEN (401 Unauthorized). "
                f"Bot ID: {settings.bot_id}, длина токена: "
                f"{len(settings.bot_token)}, источник: "
                f"{settings.bot_token_source}. "
                "Токен отозван, бот удалён или указан неверно. "
                "Получи новый токен у @BotFather и обнови BOT_TOKEN на Bothost."
            ) from exc
    finally:
        await ctx.smsfast.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
        asyncio.run(run(settings))
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
