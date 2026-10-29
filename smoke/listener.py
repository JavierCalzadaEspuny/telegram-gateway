"""Run the real TelegramListener smoke test with local configuration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon.errors import AuthKeyError, UnauthorizedError

from telegram_gateway import (
    TelegramChannel,
    TelegramListener,
    TelegramMessage,
    TelegramSession,
    TelegramSessionError,
)

SESSION_DIRECTORY = Path.home() / ".local/share/telegram-osint/auth/telegram"

CHANNELS = (
    TelegramChannel(
        "testosint01",
        translate=True,
        download_photos=True,
        download_videos=False,
    ),
)
TRANSLATION_TIMEOUT = 3.0
TRANSLATION_MAX_CONCURRENCY = 2
MEDIA_TIMEOUT = 30.0
MEDIA_MAX_CONCURRENCY = 2
MEDIA_MAX_BYTES = 20 * 1024 * 1024
QUEUE_MAXSIZE = 1000

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def consume(queue: asyncio.Queue[TelegramMessage | None]) -> None:
    while True:
        message = await queue.get()
        try:
            if message is None:
                break
            print()
            print(message)
        finally:
            queue.task_done()


async def main() -> None:
    if not CHANNELS:
        raise RuntimeError("Set CHANNELS at the top of smoke/listener.py")

    try:
        async with TelegramSession(SESSION_DIRECTORY) as client:
            listener = TelegramListener(
                client=client,
                channels=CHANNELS,
                translation_timeout=TRANSLATION_TIMEOUT,
                translation_max_concurrency=TRANSLATION_MAX_CONCURRENCY,
                media_timeout=MEDIA_TIMEOUT,
                media_max_concurrency=MEDIA_MAX_CONCURRENCY,
                media_max_bytes=MEDIA_MAX_BYTES,
                queue_maxsize=QUEUE_MAXSIZE,
            )
            consumer = asyncio.create_task(consume(listener.queue))
            try:
                await listener.start()
            finally:
                await consumer
    except TelegramSessionError as exc:
        logger.error("%s", exc)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (AuthKeyError, UnauthorizedError) as exc:
        logger.error(
            "Telegram session unavailable: %s No interactive login was started.",
            exc,
        )
    except KeyboardInterrupt:
        logger.info("Stopped.")
