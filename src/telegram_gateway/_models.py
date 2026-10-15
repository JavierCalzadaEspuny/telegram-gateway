"""Immutable channel options and live message packets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

import ulid

MediaKind = Literal["photo", "video", "document", "other"]


def _message_ulid(timestamp: int, channel_id: int, message_id: int) -> str:
    """Return a stable ULID for a Telegram message source."""
    timestamp_bytes = (timestamp * 1000).to_bytes(6, byteorder="big")
    source_bytes = f"{channel_id}:{message_id}".encode()
    entropy = hashlib.sha256(source_bytes).digest()[:10]
    return str(ulid.ULID.from_bytes(timestamp_bytes + entropy))


@dataclass(frozen=True, slots=True)
class TelegramChannel:
    """A monitored username and its explicit, optional enrichment settings."""

    username: str
    translate: bool = False
    download_photos: bool = False
    download_videos: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.username, str):
            raise ValueError("username must be a Telegram username.")
        username = self.username.strip().removeprefix("@")
        if not username:
            raise ValueError("username must be a Telegram username, optionally with @.")
        object.__setattr__(self, "username", username)

        if not isinstance(self.translate, bool):
            raise ValueError("translate must be a boolean.")
        if not isinstance(self.download_photos, bool):
            raise ValueError("download_photos must be a boolean.")
        if not isinstance(self.download_videos, bool):
            raise ValueError("download_videos must be a boolean.")


@dataclass(frozen=True, slots=True)
class TelegramMedia:
    """An original attachment, whether or not its content was downloaded."""

    message_id: int
    kind: MediaKind
    caption: str | None = None
    data: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    """One live message or album, with original text and optional enrichment."""

    id: str = field(init=False)
    message_id: int
    timestamp: int
    channel_title: str
    channel_username: str | None
    channel_id: int
    raw_text: str | None
    media: tuple[TelegramMedia, ...] = ()
    translated_text: str | None = None
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

    @property
    def has_media(self) -> bool:
        """Whether any attachment is present, independently of downloaded bytes."""
        return bool(self.media)
