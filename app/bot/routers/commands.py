import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.routers.workflow import dashboard_keyboard
from app.config import Settings
from app.database.advisory_lock import AdvisoryLockUnavailableError
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)
router = Router(name="commands")


@router.message(Command("start"))
async def start_command(message: Message, settings: Settings) -> None:
    if message.from_user is None or message.from_user.id not in settings.admin_id_set:
        await message.answer(
            "Telegram News Bot 2.0 — multi-source news intelligence. "
            "Administrator access is required for editorial controls."
        )
        return
    await message.answer(
        "🛰️ <b>NEWS OPS // CONTROL DECK</b>\n"
        "Select a stage. Operate the editorial pipeline with inline controls.\n\n"
        "🧠 AI drafts · 🧪 human review · 🛡️ approval · 🚀 explicit publishing",
        reply_markup=dashboard_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message, settings: Settings) -> None:
    if message.from_user is not None and message.from_user.id in settings.admin_id_set:
        await message.answer(
            "🛠️ <b>Control deck guide</b>\n"
            "Use inline buttons to browse incoming stories, generate drafts, edit copy, approve or reject "
            "versions, translate approved Russian stories, and preview/confirm each channel publication.\n\n"
            "Commands remain available as fallback: /load, /sources, /drafts, /draft, /review, /edit, "
            "/regenerate, /approve, /reject, /translate, /publish and /history.",
            reply_markup=dashboard_keyboard(),
        )
    else:
        await message.answer("Telegram News Bot 2.0 — multi-source news intelligence.")


@router.message(Command("load"))
async def load_command(message: Message, settings: Settings, ingestion_service: IngestionService) -> None:
    if message.from_user is None or message.from_user.id not in settings.admin_id_set:
        await message.answer("This command is available to configured administrators only.")
        return
    await message.answer("Checking configured news sources…")
    try:
        result = await ingestion_service.ingest(limit=settings.source_fetch_limit)
    except AdvisoryLockUnavailableError:
        await message.answer("Another bot instance is already scanning the feeds. Please wait for it to finish.")
        return
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
