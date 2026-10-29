# TelegramGateway

TelegramGateway streams new Telegram channel messages into an `asyncio.Queue`
through `TelegramListener`. It is a small async wrapper around Telethon:

- `telegram-login` authorizes a saved Telegram session.
- `TelegramSession` opens and owns the authorized runtime client.
- `TelegramListener` sends new channel messages to an `asyncio.Queue`.

The listener packages each new message or album into an immutable
`TelegramMessage`. `searchable_text` prefers translation without changing either text field.
Original text, attachment kinds, captions, and source IDs
remain available without downloading files. Photo/video downloads and
translation are explicit per-channel options. Stable 26-character IDs
identify the original Telegram source.

The login command is the only interactive component. Runtime applications give
`TelegramSession` an explicit directory; it loads credentials and the saved
session, connects, verifies authorization, and disconnects its client.

## Install

```bash
pip install git+https://github.com/JavierCalzadaEspuny/telegram-gateway.git
```

With uv:

```bash
uv add git+https://github.com/JavierCalzadaEspuny/telegram-gateway.git
```

The distribution is named `telegram-gateway`; Python imports use
`telegram_gateway`. The package includes the empty `py.typed` marker defined
by [PEP 561](https://peps.python.org/pep-0561/), so type checkers can use its
inline annotations. This marker has no runtime behavior.

## Login

```sh
telegram-login --directory ~/.local/share/telegram-osint/auth/telegram
```

The command creates the directory, asks for missing API credentials and authorizes
Telegram. It saves `credentials.json` and Telethon's `account.session` with private
permissions. Phone input, login codes and 2FA passwords are not persisted by the
login command. Existing authorized sessions are reused without prompts.
See [Login](docs/login.md).

## Runtime session

```python
from pathlib import Path
from telegram_gateway import TelegramSession

session_directory = Path.home() / ".local/share/telegram-osint/auth/telegram"
async with TelegramSession(session_directory) as client:
    ...
```

The caller chooses the directory. Additional keyword arguments go to Telethon.
Missing or revoked sessions raise `TelegramSessionError`; runtime never prompts.
See [Runtime session](docs/session.md).

## Listener

```python
import asyncio
from pathlib import Path

from telegram_gateway import TelegramChannel, TelegramListener, TelegramSession

session_directory = Path.home() / ".local/share/telegram-osint/auth/telegram"

async with TelegramSession(session_directory) as client:
    listener = TelegramListener(
        client,
        [
            TelegramChannel("AjaNews", download_photos=True),
            TelegramChannel("almayadeen", translate=True),
            TelegramChannel("another_channel", download_videos=True),
        ],
        queue_maxsize=1000,
    )

    async def consume() -> None:
        while True:
            message = await listener.queue.get()
            try:
                if message is None:
                    return
                print(message)
            finally:
                listener.queue.task_done()

    consumer = asyncio.create_task(consume())
    try:
        await listener.start()
    finally:
        await consumer
```

`start()` runs until the client disconnects. A full bounded queue drops the
incoming message rather than blocking Telethon. `None` marks shutdown. See
[docs/listener.md](docs/listener.md).

Channels and processing options are fixed per listener. Create another
`TelegramListener` with the same connected client when those options change.

Each channel has one immutable configuration. `translate=False`,
`download_photos=False`, and `download_videos=False` disable enrichment by
default. `translate=True` requests English translation. Usernames accept an
optional leading `@`; matching ignores case,
and duplicate usernames are rejected. Listener requires update reception to
be enabled.
Startup binds options to resolved channel IDs, including secondary usernames,
and rejects configuring the same channel through multiple aliases.

Translation and downloads have separate timeouts and concurrency limits.
Downloads default to 30 seconds, two concurrent requests, and 20 MiB per
attachment, configured by `media_timeout`, `media_max_concurrency`, and
`media_max_bytes`. Missing, oversized, or failed content leaves `data=None`
and preserves the attachment record. Translation defaults to 3 seconds and
two concurrent requests, configured by `translation_timeout` and
`translation_max_concurrency`. Neither enrichment adds retries;
Telethon request options remain caller-owned. See [docs/session.md](docs/session.md).

## Message

| Field | Value |
| --- | --- |
| `id` | Stable 26-character ID derived from timestamp, channel ID, and message ID. |
| `channel_id` | Telegram channel ID. |
| `channel_username` | Public username or `None`. |
| `channel_title` | Channel display title. |
| `message_id` | Telegram message ID within the channel. |
| `reply_to_message_id` | ID of the replied-to message, or `None`; its text is not fetched. |
| `timestamp` | Unix seconds. |
| `raw_text` | First nonempty original text/caption in message-ID order, or `None`. No cleanup or Markdown conversion. |
| `translated_text` | Optional English translation of `raw_text`, unchanged as returned by Telegram. |
| `media` | Tuple of `TelegramMedia` records, whether downloaded or not. |

`has_media` is a property equivalent to `bool(message.media)`. It is not a
stored field. Check attachment kinds directly when selecting photos or videos.

Each `TelegramMedia` has `message_id`, `kind` (`photo`, `video`, `document`,
or `other`), its original `caption`, and optional `data: bytes | None`.
Albums keep every attachment's ID and caption. The smallest message ID anchors
the publication's identity; its first nonempty caption supplies `raw_text` and
the optional translation. Additional captions remain in `media`.

```python
if message.media:
    for item in message.media:
        if item.kind == "video":
            print(item.message_id, item.caption, item.data is not None)
```

Native Telegram photos are `photo`; videos are identified from Telegram
document attributes. Animated documents, including GIF-like MP4 files, stay
`document`. Images sent as files also stay `document`. Other attachments
remain visible as `other`; link previews are excluded. Only native photos and
videos have an optional downloader.
Native live photos can expose photo and video records with the same source ID.

Output objects are typed, frozen dataclasses built by the processor.
Consumers choose how to serialize or store fields. If a Python dictionary is
needed, the standard `dataclasses.asdict(message)` includes stored fields only
and retains media bytes. The default representation omits byte payloads.

## Repository checks

The manual script `smoke/listener.py` uses `TelegramSession` with the
persistent login. Set channels and enrichment options directly in its
constants; see [docs/testing.md](docs/testing.md). Architecture and ownership
boundaries are in [docs/architecture.md](docs/architecture.md).
