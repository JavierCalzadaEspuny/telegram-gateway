# Listener

`TelegramListener` converts Telethon events into
`asyncio.Queue[TelegramMessage | None]`.

```python
from telegram_gateway import TelegramListener, TelegramSession

async with TelegramSession() as client:
    listener = TelegramListener(
        client,
        channels,
        image_channels=(),
        translation_channels=(),
        translation_target_language="en",
        translation_timeout=3.0,
        translation_max_concurrency=2,
        queue_maxsize=0,
    )
    await listener.start()
```

The client must already be connected and authorized, with update reception
enabled (`receive_updates=True`). Applications may connect with reception
disabled and enable it with `client.set_receive_updates(True)` after handler
registration. `TelegramSession` is the standard owner, though any compatible
connected client can be supplied. The
listener never logs in or disconnects it. A listener is single-use; create a
new instance after `start()` finishes or when its fixed configuration changes.

## Queue and lifecycle

`start()` registers handlers for new messages and albums before its first
await, resolves their channel filters, requests the update state, then waits
for the client's disconnection future. Channel-resolution failures propagate
from `start()`. On shutdown it removes its handlers, cancels only its own
enrichment tasks, and adds `None` to `queue`. Cancelling the listener leaves the
supplied client connected; its owner decides when to disconnect it.

`queue_maxsize=0` is unbounded. When a bounded queue is full, the incoming
message is dropped and a warning is logged so Telegram's update loop is not
blocked. If the queue is full during shutdown, one buffered message is removed
to make room for `None`.

Telethon owns transport reconnection. Errors from the client lifecycle reach
the caller. An error processing one event is logged and does not stop later
events.

The queue size bounds completed messages, not every incoming Telethon event or
image download. Translation concurrency is bounded separately. Native album
assembly also adds a short delay before an album is delivered.

## Messages, albums, media, images, replies, and translation

A normal event becomes one `TelegramMessage`. Telegram album events are sorted
by Telegram message ID and become one message; the first item supplies identity
and text.

`has_media` is true when a message or any album item contains a photo, document,
or paid-media attachment. Telegram represents video attachments as documents,
so videos set this flag too. Detection uses message metadata and does not
download the media.

`reply_to_message_id` contains the ID of the message being replied to, or
`None`. It preserves the relationship without fetching the referenced message
or changing the original text. For albums, the first reply ID in message-ID
order is retained.

Photos are downloaded only when the channel username is in `image_channels`.
The downloader selects the largest still-photo dimensions explicitly, so
preview documents and animated-photo video sizes cannot enter `images`.
Download failures are logged and preserve the logical message. Photo-only and
video-only messages therefore remain available even when media download is
disabled or fails; video bytes are not downloaded.

Text is Unicode-repaired and emoji-stripped. Translation runs only for
`translation_channels`, is limited by `translation_timeout` and
`translation_max_concurrency`, and has no Gateway retries.
The timeout includes waiting for translation concurrency and Telethon's own
request handling, but does not bound image downloads. Telethon's retry and
FloodWait options remain caller-owned; see [session.md](session.md).
Translation failure preserves the original text and leaves the translation
fields empty.
