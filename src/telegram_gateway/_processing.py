"""Package original Telegram messages and apply optional bounded enrichment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace

from telethon import TelegramClient, utils
from telethon.tl import functions, types
from telethon.tl.custom.message import Message

from ._models import MediaKind, TelegramChannel, TelegramMedia, TelegramMessage

logger = logging.getLogger(__name__)


def _describe_media(message: Message) -> tuple[TelegramMedia, ...]:
    """Describe actual attachments, without downloading or including link previews."""
    native = message.media
    if native is None or isinstance(
        native, (types.MessageMediaEmpty, types.MessageMediaWebPage)
    ):
        return ()

    kind: MediaKind
    if isinstance(native, types.MessageMediaPhoto):
        kind = "photo"
    elif isinstance(native, types.MessageMediaDocument):
        attributes = getattr(native.document, "attributes", ())
        is_video = any(isinstance(item, types.DocumentAttributeVideo) for item in attributes)
        is_animation = any(
            isinstance(item, types.DocumentAttributeAnimated) for item in attributes
        )
        kind = "video" if is_video and not is_animation else "document"
    else:
        kind = "other"

    item = TelegramMedia(
        message_id=message.id,
        kind=kind,
        caption=message.raw_text or None,
    )
    if isinstance(native, types.MessageMediaPhoto) and isinstance(native.video, types.Document):
        return item, replace(item, kind="video")
    return (item,)


def _largest_photo_size(photo: types.Photo) -> types.TypePhotoSize | None:
    return max(
        (
            size
            for size in photo.sizes
            if isinstance(
                size,
                (
                    types.PhotoSize,
                    types.PhotoCachedSize,
                    types.PhotoSizeProgressive,
                    types.PhotoStrippedSize,
                ),
            )
        ),
        key=lambda size: getattr(size, "w", 0) * getattr(size, "h", 0),
        default=None,
    )


def _photo_size_bytes(size: types.TypePhotoSize) -> int:
    if isinstance(size, types.PhotoSize):
        return size.size
    if isinstance(size, (types.PhotoCachedSize, types.PhotoStrippedSize)):
        return len(size.bytes)
    if isinstance(size, types.PhotoSizeProgressive):
        return max(size.sizes, default=0)
    return 0


class MessageProcessor:
    """Map a live message or album to values, preserving every attachment."""

    def __init__(
        self,
        *,
        client: TelegramClient,
        channels: Sequence[TelegramChannel],
        translation_timeout: float,
        translation_max_concurrency: int,
        media_timeout: float,
        media_max_concurrency: int,
        media_max_bytes: int,
    ) -> None:
        self._client = client
        self._channel_options = tuple(channels)
        self._channels_by_id: dict[int, TelegramChannel] | None = None
        self._channel_lock = asyncio.Lock()
        self._translation_timeout = translation_timeout
        self._translation_semaphore = asyncio.Semaphore(translation_max_concurrency)
        self._media_timeout = media_timeout
        self._media_semaphore = asyncio.Semaphore(media_max_concurrency)
        self._media_max_bytes = media_max_bytes
        self._chat_meta: dict[int, tuple[str, str | None]] = {}

    async def resolve_channels(self) -> dict[int, TelegramChannel]:
        """Bind fixed options to peer IDs once, including secondary usernames."""
        if self._channels_by_id is not None:
            return self._channels_by_id
        async with self._channel_lock:
            if self._channels_by_id is None:
                resolved: dict[int, TelegramChannel] = {}
                for channel in self._channel_options:
                    peer = await self._client.get_input_entity(channel.username)
                    channel_id = utils.get_peer_id(peer)
                    if channel_id in resolved:
                        raise ValueError(
                            "Each Telegram channel must have one configuration; "
                            f"{channel.username!r} resolves to an already configured channel."
                        )
                    resolved[channel_id] = channel
                self._channels_by_id = resolved
        return self._channels_by_id

    async def process(self, messages: Sequence[Message]) -> TelegramMessage | None:
        if not messages:
            return None

        ordered = sorted(messages, key=lambda message: message.id)
        base = ordered[0]
        channels_by_id = await self.resolve_channels()
        channel_id, channel_title, channel_username = await self._resolve_chat_meta(base)
        channel = channels_by_id[channel_id]
        caption_source = next((message for message in ordered if message.raw_text), None)
        raw_text = caption_source.raw_text if caption_source is not None else None

        media: list[TelegramMedia] = []
        for source in ordered:
            for item in _describe_media(source):
                should_download = (
                    (item.kind == "photo" and channel.download_photos)
                    or (item.kind == "video" and channel.download_videos)
                )
                if should_download:
                    data = await self._download_media(source, item)
                    if data is not None:
                        item = replace(item, data=data)
                media.append(item)

        if raw_text is None and not media:
            return None

        translated_text = await self._translate(caption_source, channel, channel_title)
        return TelegramMessage(
            message_id=base.id,
            timestamp=int(base.date.timestamp()),
            channel_title=channel_title,
            channel_username=channel_username,
            channel_id=channel_id,
            raw_text=raw_text,
            media=tuple(media),
            translated_text=translated_text,
            reply_to_message_id=next(
                (message.reply_to_msg_id for message in ordered if message.reply_to_msg_id is not None),
                None,
            ),
        )

    async def _resolve_chat_meta(self, message: Message) -> tuple[int, str, str | None]:
        chat_id = message.chat_id
        if chat_id not in self._chat_meta:
            chat = await message.get_chat()
            self._chat_meta[chat_id] = (
                getattr(chat, "title", str(chat_id)),
                getattr(chat, "username", None),
            )
        title, username = self._chat_meta[chat_id]
        return chat_id, title, username

    async def _download_media(self, source: Message, item: TelegramMedia) -> bytes | None:
        """Prepare the attachment and fail open only around the download."""
        native = source.media
        thumb = None
        if item.kind == "photo":
            asset = native.photo
            if not isinstance(asset, types.Photo):
                return None
            size = _largest_photo_size(asset)
            if size is None:
                return None
            expected_size = _photo_size_bytes(size)
            thumb = size.type
        else:
            asset = (
                native.video
                if isinstance(native, types.MessageMediaPhoto)
                else native.document
            )
            if not isinstance(asset, types.Document):
                return None
            expected_size = asset.size

        if expected_size <= 0 or expected_size > self._media_max_bytes:
            logger.warning(
                "Skipping %s download for chat_id=%s message_id=%s: "
                "size %s is unknown or exceeds media_max_bytes=%s.",
                item.kind, source.chat_id, source.id,
                expected_size, self._media_max_bytes,
            )
            return None

        try:
            return await asyncio.wait_for(
                self._download_bytes(asset, thumb=thumb), timeout=self._media_timeout
            )
        except Exception as exc:
            logger.warning(
                "Could not download %s for chat_id=%s message_id=%s: %s",
                item.kind, source.chat_id, source.id, exc,
            )
            return None

    async def _download_bytes(
        self, asset: types.Photo | types.Document, *, thumb: str | None
    ) -> bytes:
        async with self._media_semaphore:
            payload = await self._client.download_media(asset, file=bytes, thumb=thumb)
        if not isinstance(payload, bytes):
            raise RuntimeError("Telegram returned no media bytes.")
        if len(payload) > self._media_max_bytes:
            raise RuntimeError("Downloaded content exceeds media_max_bytes.")
        return payload

    async def _translate(
        self,
        source: Message | None,
        channel: TelegramChannel,
        channel_title: str,
    ) -> str | None:
        if source is None or not channel.translate:
            return None

        request = functions.messages.TranslateTextRequest(
            text=[types.TextWithEntities(
                text=source.raw_text,
                entities=list(source.entities or ()),
            )],
            to_lang="en",
        )

        try:
            result = await asyncio.wait_for(
                self._send_translation_request(request),
                timeout=self._translation_timeout,
            )
            if not result.result or not result.result[0].text:
                raise RuntimeError("Telegram returned no translated text.")
            return result.result[0].text
        except Exception as exc:
            logger.warning(
                "Translation failed for channel %r: %s. Emitting the original message.",
                channel_title, exc,
            )
            return None

    async def _send_translation_request(
        self, request: functions.messages.TranslateTextRequest
    ) -> types.messages.TranslateResult:
        async with self._translation_semaphore:
            return await self._client(request)
