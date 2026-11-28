import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile

from app.config import Settings
from app.webhook import build_webhook_application, build_webhook_certificate


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


def test_webhook_certificate_is_wrapped_as_uploadable_input_file(tmp_path):
    certificate = tmp_path / "telegram-webhook-public.pem"
    certificate.write_text("public certificate", encoding="utf-8")
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_transport="webhook",
        webhook_base_url="https://203.0.113.10",
        webhook_secret_token="secret_token-123",
        webhook_certificate_path=str(certificate),
    )

    upload = build_webhook_certificate(settings)

    assert isinstance(upload, FSInputFile)
    assert upload.path == certificate
