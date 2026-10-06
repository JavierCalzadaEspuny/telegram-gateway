"""Data models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import ulid


def _message_ulid(timestamp: int, channel_id: int, message_id: int) -> str:
    """Return a stable ULID for a Telegram message source."""
    if message_id < 0:
        raise ValueError("message_id must be non-negative.")

    timestamp_ms = timestamp * 1000
    if not 0 <= timestamp_ms <= (1 << 48) - 1:
        raise ValueError("timestamp is outside the ULID timestamp range.")

    timestamp_bytes = timestamp_ms.to_bytes(6, byteorder="big")
    source_bytes = f"{channel_id}:{message_id}".encode()
    entropy = hashlib.sha256(source_bytes).digest()[:10]
    return str(ulid.ULID.from_bytes(timestamp_bytes + entropy))


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    """An immutable, normalized Telegram message."""

    id: str = field(init=False)
    message_id: int
    timestamp: int
    channel_title: str
    channel_username: str | None
    channel_id: int
    text: str | None
    images: tuple[bytes, ...] = ()
    translated_text: str | None = None
    translation_language: str | None = None
    has_media: bool = False
    reply_to_message_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _message_ulid(
                timestamp=self.timestamp,
                channel_id=self.channel_id,
                message_id=self.message_id,
            ),
        )
        images = tuple(self.images)
        object.__setattr__(self, "images", images)
        if images:
            object.__setattr__(self, "has_media", True)

    def to_dict(self) -> dict[str, object]:
        """Return identity, channel, message, text, and media fields in order."""
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "channel_username": self.channel_username,
            "channel_title": self.channel_title,
            "message_id": self.message_id,
            "reply_to_message_id": self.reply_to_message_id,
            "timestamp": self.timestamp,
            "text": self.text,
            "translated_text": self.translated_text,
            "translation_language": self.translation_language,
            "has_media": self.has_media,
            "images": self.images,
        }

    def __str__(self) -> str:
        data = self.to_dict()
        data["images"] = f"{len(self.images)}"
        return json.dumps(data, ensure_ascii=False, indent=2)
