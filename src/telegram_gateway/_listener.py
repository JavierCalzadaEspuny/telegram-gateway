"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from telethon import TelegramClient, events
from telethon.tl import functions
from telethon.tl.custom.message import Message

from ._models import TelegramMessage
from ._processing import (
    MessageProcessor,
    ProcessingPolicy,
    _normalize_target_language,
    _validate_channels,
    _validate_channel_subset,
    _validate_non_negative_integer,
    _validate_positive_number,
)

logger = logging.getLogger(__name__)


class TelegramListener:
    """Stream configured channels into an ``asyncio.Queue``."""

    def __init__(
        self,
        client: TelegramClient,
        channels: Sequence[str],
        *,
        image_channels: Sequence[str] = (),
        translation_channels: Sequence[str] = (),
        translation_target_language: str = "en",
        translation_timeout: float = 3.0,
        translation_max_concurrency: int = 2,
        queue_maxsize: int = 0,
    ) -> None:
        monitored_channels = _validate_channels(
            channels,
            parameter="channels",
            allow_empty=False,
        )
        downloaded_image_channels = _validate_channel_subset(
            image_channels,
            monitored_channels,
            parameter="image_channels",
        )
        translated_channels = _validate_channel_subset(
            translation_channels,
            monitored_channels,
            parameter="translation_channels",
        )
        normalized_timeout = _validate_positive_number(
            translation_timeout,
            parameter="translation_timeout",
        )
        normalized_concurrency = _validate_non_negative_integer(
            translation_max_concurrency,
            parameter="translation_max_concurrency",
        )
        if normalized_concurrency == 0:
            raise ValueError("translation_max_concurrency must be greater than zero.")
        normalized_queue_size = _validate_non_negative_integer(
            queue_maxsize,
            parameter="queue_maxsize",
        )

        self._client = client
        self._channels = monitored_channels
        self._processor = MessageProcessor(
            client=client,
            image_channels=downloaded_image_channels,
            translation_channels=translated_channels,
            translation_target_language=_normalize_target_language(
                translation_target_language
            ),
            policy=ProcessingPolicy(
                translation_timeout=normalized_timeout,
                translation_max_concurrency=normalized_concurrency,
                translation_retries=0,
                retry_flood_waits=False,
            ),
        )
        self._started = False
        self._stopping = False
        self._processing_tasks: set[asyncio.Task[TelegramMessage | None]] = set()
        self.queue: asyncio.Queue[TelegramMessage | None] = asyncio.Queue(
            maxsize=normalized_queue_size
        )

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

            new_messages = events.NewMessage(chats=self._channels)
            albums = events.Album(chats=self._channels)
            client.add_event_handler(self._on_new_message, new_messages)
            client.add_event_handler(self._on_album, albums)
            await new_messages.resolve(client)
            await albums.resolve(client)
            await client(functions.updates.GetStateRequest())
            logger.info(
                "Listener started. Monitoring %d channel(s).",
                len(self._channels),
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
