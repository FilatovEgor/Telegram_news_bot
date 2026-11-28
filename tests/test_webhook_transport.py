import pytest
from aiogram import Bot, Dispatcher

from app.config import Settings
from app.webhook import build_webhook_application


@pytest.mark.asyncio
async def test_webhook_application_registers_health_and_authenticated_update_routes():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com",
        webhook_secret_token="secret_token-123",
    )
    bot = Bot(token="123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    dispatcher = Dispatcher()

    try:
        app = build_webhook_application(dispatcher, bot, settings)

        paths = {resource.canonical for resource in app.router.resources()}
        assert "/healthz" in paths
        assert settings.webhook_path in paths
    finally:
        await bot.session.close()
