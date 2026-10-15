# Listener

`TelegramListener` packages Telethon events into
`asyncio.Queue[TelegramMessage | None]`.

```python
from telegram_gateway import TelegramChannel, TelegramListener, TelegramSession

async with TelegramSession() as client:
    listener = TelegramListener(
        client,
        channels=[
            TelegramChannel("news", translate=True, download_photos=True),
            TelegramChannel("clips", download_videos=True),
            TelegramChannel("headlines"),
        ],
        translation_timeout=3.0,
        translation_max_concurrency=2,
        media_timeout=30.0,
        media_max_concurrency=2,
        media_max_bytes=20 * 1024 * 1024,
        queue_maxsize=0,
    )
    await listener.start()
```

The client must already be connected and authorized, with update reception
enabled (`receive_updates=True`). Applications may connect with reception
disabled and enable it with `client.set_receive_updates(True)` after handler
registration. The listener borrows the client and never logs in or disconnects
it. A listener is single-use; create a new instance after `start()` finishes
or when its fixed configuration changes.

## Channel rules

Each immutable `TelegramChannel` combines one username with its options:

- `translate=False`: no translation; `True` requests English translation.
- `download_photos=False`: native photo metadata only; `True` requests photo bytes.
- `download_videos=False`: video metadata only; `True` requests video bytes.

All channels are monitored regardless of enrichment. Usernames accept an
optional `@` and surrounding whitespace. Matching ignores case; the listener
rejects duplicate normalized usernames. Empty channels, non-channel values,
non-boolean enrichment flags, and invalid resource limits raise `ValueError`.
Telegram resolves usernames; Gateway does not replicate its username format
rules. Startup binds options to resolved Telegram peer IDs, so secondary
usernames work as well. Distinct usernames resolving to the same
channel raise `ValueError` at startup; configure each channel once.
Configuration has no mutable setters.

## Queue and lifecycle

`start()` registers new-message and album handlers before its first await,
resolves channel identities and their filters, requests the update state, then
waits for the client's disconnection future. Startup channel-resolution failures propagate.
Shutdown removes these handlers, cancels only the listener's enrichment tasks,
and adds `None` to the queue. Cancelling the listener leaves the client connected.

`queue_maxsize=0` is unbounded. A full bounded queue drops the incoming completed
message and logs a warning. A full queue during shutdown drops one buffered
message to make room for `None`. Consumers must pair each `get()` with
`task_done()`, including the sentinel.

Telethon owns transport reconnection and native album assembly. Fatal client
errors propagate; an individual event-processing failure is logged without
stopping later events. Each event requires a resolved channel configuration;
a missing configuration is logged as an event-processing error rather than
silently disabling enrichment. Album assembly introduces a short delivery delay.

## Message and album mapping

One event or native album becomes one immutable `TelegramMessage`. Sources are
sorted by message ID. The smallest ID and its original date anchor the stable
ULID. The first nonempty original text is `raw_text`; a caption on a later item
can therefore supply it. Empty text means absent; whitespace-only content,
emoji, Unicode characters, and line breaks are preserved exactly.

Every attachment creates a `TelegramMedia` record before download is considered.
Its `message_id` and `caption` retain that item's original source. Additional
album captions remain available even though `raw_text` and its translation
represent one selected caption. No captions are concatenated or rewritten.

`reply_to_message_id` retains the first reply ID in source message-ID order.
It does not fetch the referenced text, a cross-chat peer, or a thread root.

## Media metadata and optional content

Each media record has:

| Field | Meaning |
| --- | --- |
| `message_id` | Original Telegram message ID within the source channel. |
| `kind` | `photo`, `video`, `document`, or `other`. |
| `caption` | Original text of that source item, or `None`. |
| `data` | Downloaded bytes, or `None` if disabled, unavailable, skipped, or failed. |

Native photos are `photo`. Video document attributes identify `video`, including
round video notes; animated documents remain `document`, even if their container
is MP4. Other documents, including images sent as files, stay `document`. Other
attachment types, including paid media, stay visible as `other`. Link previews
are excluded from attachments and are not downloaded.

A native live photo with a motion document creates both photo and video
records sharing the original message ID and caption. Photo video-size previews
are still excluded from downloads.

`media` is the only attachment collection. `has_media` is a computed property
equivalent to `bool(message.media)`; no presence flags are stored. Select types
with `item.kind`:

```python
has_images = any(item.kind == "photo" for item in message.media)
for item in message.media:
    if item.kind == "video" and item.data is not None:
        process_video(item.data)
```

A media-only message survives when downloading is disabled or fails. Attachment
presence does not imply downloaded bytes.

Photo downloads select the largest still-photo size explicitly; animated-photo
video sizes cannot enter photo data. Video downloads target the actual document
without a thumbnail. Documents and other attachment types have no downloader.

Photo and video downloads share `media_max_concurrency`. Each download's
`media_timeout` includes semaphore wait and the request. `media_max_bytes` is a
per-attachment limit: unknown or oversized metadata skips the download, and
oversized returned content is discarded. It is not a streaming or queue memory
limit; the client downloads bytes in memory. Failed external download requests
or invalid byte responses log a warning and preserve metadata. Attachment
preparation errors reach the listener's event-error handler. There are no
Gateway download retries.

## Optional translation

Translation uses the selected original caption and its native text entities,
without modifying `raw_text` or exposing formatting entities in the output.
The channel's `translate` flag enables translation, always targeting English
(`en`). Successful response text is stored unchanged in `translated_text`.
Other album captions remain original and untranslated. No language field is
included in the output because the target is fixed.

Translation has separate bounded concurrency and a timeout that includes waiting
for that concurrency. Request or response failures preserve the message and
leave `translated_text=None`. Request preparation errors reach the listener's
event-error handler. There are no Gateway translation retries. Telethon retries
and FloodWait handling remain caller choices; see [session.md](session.md).

## Output and memory

The processor returns typed, frozen dataclasses and creates the media tuple
directly. Output objects do not repeat field validation or define serialization
methods. The only computed values are the deterministic ID and the `has_media`
property. Consumers choose whether to use original or translated text, clean
it, and serialize or store fields. The standard `dataclasses.asdict(message)`
is available when needed: it retains media bytes and includes no computed
properties. The default object representation omits byte payloads.

The output queue bounds completed messages, not every incoming event or pending
enrichment task. Downloaded bytes remain alive while their packets remain
referenced. An album can contain several downloads up to the per-item cap.
Choose channel download options, concurrency, byte limits, and queue size for
the caller's workload.
