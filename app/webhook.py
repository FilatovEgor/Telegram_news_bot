"""Webhook ingress for horizontally scaled Telegram bot replicas."""

import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.config import Settings

logger = logging.getLogger(__name__)


def build_webhook_certificate(settings: Settings) -> FSInputFile | None:
    """Build the multipart upload for a configured self-signed webhook certificate."""
    if settings.webhook_certificate_path is None:
        return None
    return FSInputFile(settings.webhook_certificate_path)


def build_webhook_application(
    dispatcher: Dispatcher,
    bot: Bot,
    settings: Settings,
) -> web.Application:
    """Build the aiohttp application with authenticated Telegram webhook routing."""
    app = web.Application()

    async def healthcheck(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/healthz", healthcheck)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret_value,
        handle_in_background=True,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)
    return app


async def serve_webhook(
    dispatcher: Dispatcher,
    bot: Bot,
    settings: Settings,
) -> None:
    """Serve webhook requests until SIGINT/SIGTERM, preserving webhook configuration."""
    webhook_url = settings.webhook_url
    secret_token = settings.webhook_secret_value
    if webhook_url is None or secret_token is None:
        raise ValueError("Webhook URL and secret token must be configured")

    app = build_webhook_application(dispatcher, bot, settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.webhook_host, port=settings.webhook_port)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals: list[signal.Signals] = []
    try:
        await site.start()
        certificate = build_webhook_certificate(settings)
        webhook_options = {
            "url": webhook_url,
            "secret_token": secret_token,
            "drop_pending_updates": False,
            "allowed_updates": dispatcher.resolve_used_update_types(),
        }
        if certificate is not None:
            webhook_options["certificate"] = certificate
        await bot.set_webhook(**webhook_options)
        logger.info("Telegram webhook listening on %s:%d at %s", settings.webhook_host, settings.webhook_port, settings.webhook_path)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
                handled_signals.append(sig)
            except NotImplementedError:
                logger.warning("Signal handler unavailable for %s", sig.name)
        await stop_event.wait()
    finally:
        for sig in handled_signals:
            loop.remove_signal_handler(sig)
        await runner.cleanup()
