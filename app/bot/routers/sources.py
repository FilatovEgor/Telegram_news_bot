from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.services.ingestion import IngestionService

router = Router(name="source-health")


@router.message(Command("sources"))
async def sources_command(
    message: Message,
    settings: Settings,
    ingestion_service: IngestionService,
) -> None:
    if message.from_user is None or message.from_user.id not in settings.admin_id_set:
        await message.answer("This command is available to configured administrators only.")
        return

    try:
        sources = await ingestion_service.source_health()
    except Exception:
        await message.answer("Could not read source health. Check the application logs.")
        return

    if not sources:
        await message.answer("No source health records yet. Run /load to start ingestion.")
        return

    lines = ["<b>News source health</b>"]
    for source in sources:
        status = escape(source.status or "NOT RUN")
        name = escape(source.name)
        attempts = source.last_attempt_at.strftime("%Y-%m-%d %H:%M UTC") if source.last_attempt_at else "never"
        line = (
            f"\\n<b>{name}</b> — {status}"
            f"\\nLast attempt: {attempts}; fetched: {source.last_fetched_count}"
            f"; failures in a row: {source.consecutive_failures}"
        )
        if source.last_duration_ms is not None:
            line += f"; duration: {source.last_duration_ms} ms"
        if source.last_error:
            line += f"\\nNote: {escape(source.last_error[:300])}"
        lines.append(line)
    await message.answer("\\n".join(lines))
