import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)
router = Router(name="commands")


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    await message.answer(
        "<b>Telegram News Bot 2.0</b>\n"
        "Multi-source news ingestion and AI-assisted editorial workflow.\n\n"
        "Commands: /help, /load, /sources, /drafts, /draft, /review, /history, /publish"
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "<b>Available commands</b>\n"
        "/start — show bot information\n"
        "/help — show this help\n"
        "/load — fetch new articles from configured sources (administrators only)\n"
        "/sources — show source health (administrators only)\n"
        "/drafts — list new articles awaiting AI drafts (administrators only)\n"
        "/draft ARTICLE_UUID — prepare a structured AI draft (administrators only)\n"
        "/review [ARTICLE_UUID] — list drafts or open a moderation preview\n"
        "/edit ARTICLE_UUID TEXT — replace the Telegram variant with plain text\n"
        "/regenerate ARTICLE_UUID — create a new AI draft and supersede the previous one\n"
        "/approve ARTICLE_UUID — approve the latest draft after blocking checks pass\n"
        "/reject ARTICLE_UUID [REASON] — reject a draft and record the reason\n"
        "/history ARTICLE_UUID — show the append-only editorial action history\n"
        "/publish ARTICLE_UUID — send an approved draft to PUBLISH_CHANNEL_ID"
    )


@router.message(Command("load"))
async def load_command(message: Message, settings: Settings, ingestion_service: IngestionService) -> None:
    if message.from_user is None or message.from_user.id not in settings.admin_id_set:
        await message.answer("This command is available to configured administrators only.")
        return
    await message.answer("Checking configured news sources…")
    try:
        result = await ingestion_service.ingest(limit=settings.source_fetch_limit)
    except Exception:
        logger.exception("Manual ingestion failed")
        await message.answer("News ingestion failed. The error has been logged for investigation.")
        return
    await message.answer(
        "Ingestion finished.\n"
        f"Sources checked: <b>{result.sources_checked}</b>\n"
        f"Articles discovered: <b>{result.discovered}</b>\n"
        f"New articles saved: <b>{result.created}</b>\n"
        f"Duplicate candidates for review: <b>{result.duplicates}</b>\n"
        f"Source failures: <b>{result.failures}</b>"
    )
