"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence

from telethon import TelegramClient, events
from telethon.tl import functions
from telethon.tl.custom.message import Message

from ._models import TelegramChannel, TelegramMessage
from ._processing import MessageProcessor

logger = logging.getLogger(__name__)


def _validate_channels(channels: Sequence[TelegramChannel]) -> tuple[TelegramChannel, ...]:
    """Snapshot fixed channel options and reject duplicate usernames."""
    if isinstance(channels, (str, bytes)):
        raise ValueError("channels must be a sequence of TelegramChannel objects.")
    try:
        validated = tuple(channels)
    except TypeError as exc:
        raise ValueError("channels must be a sequence of TelegramChannel objects.") from exc
    if not validated:
        raise ValueError("channels cannot be empty.")
    if any(not isinstance(channel, TelegramChannel) for channel in validated):
        raise ValueError("channels must contain only TelegramChannel objects.")
    keys = [channel.username.casefold() for channel in validated]
    if len(set(keys)) != len(keys):
        raise ValueError("channels cannot contain duplicate usernames.")
    return validated


def _validate_timeout(value: object, parameter: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{parameter} must be finite and greater than zero.")
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{parameter} must be finite and greater than zero.")


class TelegramListener:
    """Stream configured channels into an ``asyncio.Queue``."""

    def __init__(
        self,
        client: TelegramClient,
        channels: Sequence[TelegramChannel],
        *,
        translation_timeout: float = 3.0,
        translation_max_concurrency: int = 2,
        media_timeout: float = 30.0,
        media_max_concurrency: int = 2,
        media_max_bytes: int = 20 * 1024 * 1024,
        queue_maxsize: int = 0,
    ) -> None:
        channels = _validate_channels(channels)
        for name, value in (
            ("translation_timeout", translation_timeout),
            ("media_timeout", media_timeout),
        ):
            _validate_timeout(value, name)
        for name, value, minimum in (
            ("translation_max_concurrency", translation_max_concurrency, 1),
            ("media_max_concurrency", media_max_concurrency, 1),
            ("media_max_bytes", media_max_bytes, 1),
            ("queue_maxsize", queue_maxsize, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}.")

        self._client = client
        self._channel_usernames = tuple(channel.username for channel in channels)
        self._processor = MessageProcessor(
            client=client,
            channels=channels,
            translation_timeout=translation_timeout,
            translation_max_concurrency=translation_max_concurrency,
            media_timeout=media_timeout,
            media_max_concurrency=media_max_concurrency,
            media_max_bytes=media_max_bytes,
        )
        self._started = False
        self._stopping = False
        self._processing_tasks: set[asyncio.Task[TelegramMessage | None]] = set()
        self.queue: asyncio.Queue[TelegramMessage | None] = asyncio.Queue(maxsize=queue_maxsize)

    async def start(self) -> None:
        """Start the listener and block until the supplied client disconnects."""
        if self._started:
            raise RuntimeError("TelegramListener has already been started.")
        self._started = True

        client = self._client
        try:
            if not client.is_connected():
                raise RuntimeError(
                    "TelegramListener requires a connected TelegramClient."
                )

            new_messages = events.NewMessage(chats=self._channel_usernames)
            albums = events.Album(chats=self._channel_usernames)
            client.add_event_handler(self._on_new_message, new_messages)
            client.add_event_handler(self._on_album, albums)
            await self._processor.resolve_channels()
            await new_messages.resolve(client)
            await albums.resolve(client)
            await client(functions.updates.GetStateRequest())
            logger.info(
                "Listener started. Monitoring %d channel(s).",
                len(self._channel_usernames),
            )
            await client.disconnected
            # Telethon 1.45 exposes fatal update errors only through its owning
            # run_until_disconnected wrapper, which also disconnects on cancel.
            updates_error = getattr(client, "_updates_error", None)
            if updates_error is not None:
                raise updates_error
        finally:
            self._stopping = True
            client.remove_event_handler(self._on_new_message)
            client.remove_event_handler(self._on_album)
            try:
                pending = tuple(self._processing_tasks)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            finally:
                self._signal_shutdown()

    def _signal_shutdown(self) -> None:
        """End the queue without blocking, even when its buffer is full."""
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            self.queue.get_nowait()
            self.queue.task_done()
            self.queue.put_nowait(None)
            logger.warning("Queue full during shutdown; dropped one buffered message.")

    def _enqueue_message(self, message: TelegramMessage) -> None:
        """Safely enqueue one processed message without blocking updates."""
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "Queue full (maxsize=%d) — dropping message from %r.",
                self.queue.maxsize,
                message.channel_title,
            )

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        if event.message.grouped_id is None:
            await self._process_messages((event.message,))

    async def _on_album(self, event: events.Album.Event) -> None:
        await self._process_messages(event.messages)

    async def _process_messages(self, messages: Sequence[Message]) -> None:
        """Own enrichment tasks without cancelling Telethon's other handlers."""
        if self._stopping or not messages:
            return
        task = asyncio.create_task(self._processor.process(messages))
        self._processing_tasks.add(task)
        try:
            message = await task
            if message is not None and not self._stopping:
                self._enqueue_message(message)
        except asyncio.CancelledError:
            if not self._stopping:
                raise
        except Exception:
            logger.exception(
                "Unhandled error processing message from chat_id=%s.",
                messages[0].chat_id,
            )
        finally:
            self._processing_tasks.discard(task)
