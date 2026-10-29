"""Real-time Telegram message listener with asyncio queue output."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Annotated

from pydantic import ConfigDict, Field, validate_call

from telethon import TelegramClient, events
from telethon.tl import functions
from telethon.tl.custom.message import Message

from ._models import TelegramChannel, TelegramMessage
from ._processing import MessageProcessor

logger = logging.getLogger(__name__)


class TelegramListener:
    """Stream configured channels into an ``asyncio.Queue``."""

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    def __init__(
        self,
        client: TelegramClient,
        channels: Annotated[Sequence[TelegramChannel], Field(min_length=1)],
        *,
        translation_timeout: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)] = 3.0,
        translation_max_concurrency: Annotated[int, Field(gt=0, strict=True)] = 2,
        media_timeout: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)] = 30.0,
        media_max_concurrency: Annotated[int, Field(gt=0, strict=True)] = 2,
        media_max_bytes: Annotated[int, Field(gt=0, strict=True)] = 20 * 1024 * 1024,
        queue_maxsize: Annotated[int, Field(ge=0, strict=True)] = 0,
    ) -> None:
        channels = tuple(channels)
        if len({channel.username.casefold() for channel in channels}) != len(channels):
            raise ValueError("channels cannot contain duplicate usernames")

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
