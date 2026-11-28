"""Keyset pagination primitives for bounded, stable queue reads."""

import base64
import struct
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

T = TypeVar("T")
_CURSOR_BYTES = 24


@dataclass(slots=True, frozen=True)
class CursorPage(Generic[T]):
    items: list[T]
    previous_cursor: str | None
    next_cursor: str | None


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """Encode a UTC timestamp and UUID into a compact Telegram-safe cursor."""
    normalized = created_at.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    timestamp_us = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    payload = struct.pack(">q", timestamp_us) + row_id.bytes
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if value is None:
        return None
    try:
        payload = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if len(payload) != _CURSOR_BYTES:
            raise ValueError
        timestamp_us = struct.unpack(">q", payload[:8])[0]
        seconds, micros = divmod(timestamp_us, 1_000_000)
        return datetime.fromtimestamp(seconds, UTC).replace(microsecond=micros), uuid.UUID(
            bytes=payload[8:]
        )
    except (ValueError, TypeError, struct.error, OverflowError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
