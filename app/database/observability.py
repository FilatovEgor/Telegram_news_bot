import logging
import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def install_slow_query_logging(engine: Any, threshold_ms: int = 250) -> None:
    """Log slow SQL timings without logging SQL text, bind values, or article content."""
    if threshold_ms < 0:
        raise ValueError("Slow-query threshold must not be negative")

    sync_engine: Engine = getattr(engine, "sync_engine", engine)

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if context is not None:
            context._newsbot_query_started_at = time.perf_counter()
            context._newsbot_query_operation = statement.lstrip().split(None, 1)[0].upper()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if context is None:
            return
        started_at = getattr(context, "_newsbot_query_started_at", None)
        if started_at is None:
            return
        duration_ms = (time.perf_counter() - started_at) * 1000
        if duration_ms >= threshold_ms:
            logger.warning(
                "Slow database query operation=%s duration_ms=%.1f executemany=%s",
                getattr(context, "_newsbot_query_operation", "UNKNOWN"),
                duration_ms,
                executemany,
            )
