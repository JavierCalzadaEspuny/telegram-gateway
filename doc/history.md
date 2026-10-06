# History

`TelegramHistory` retrieves a finite range from configured channels:

```python
from telegram_gateway import TelegramHistory, TelegramSession

async with TelegramSession() as client:
    history = TelegramHistory(
        client,
        channels,
        image_channels=(),
        translation_channels=(),
        translation_target_language="en",
        translation_timeout=30.0,
        translation_retries=2,
        history_wait_time=1.0,
    )
    messages = await history.fetch(start=..., end=..., show_progress=False)
```

The client must already be connected and authorized. `TelegramSession` is the
standard owner, though any compatible connected client can be supplied.
History never logs in or disconnects it. Create a new instance when its fixed
channels or processing options change.

## Range and retrieval

`start` and `end` are non-negative Unix seconds. The range is half-open:
`start <= timestamp < end`. Both values must fit the timestamp portion of the
deterministic message ID, and `start` must be earlier than `end`.

Channels are fetched sequentially with Telethon pagination and
`history_wait_time`. Retrieval starts at the exclusive end and stops after
reaching a message older than the start. The complete result is sorted by
timestamp, channel ID, and Telegram message ID.

Channel resolution uses Telethon's `get_input_entity()`, reusing its session
cache when possible instead of requesting fresh full channel details.

`show_progress=True` displays one `tqdm` bar. Its total is the requested time
interval multiplied by the number of channels. It estimates temporal coverage,
not message count. The default is silent.

## Messages, albums, media, images, replies, and translation

Adjacent items with the same Telegram album ID become one `TelegramMessage`.
The first item by message ID supplies identity and text; configured photos are
downloaded in message-ID order. `has_media` is true when any album item has a
photo, document, or paid-media attachment. Telegram represents video
attachments as documents, so videos set this flag without being downloaded.
The flag is based on Telegram metadata and does not trigger another request.
With `image_channels=()`, no photo bytes are downloaded; photo-only and
video-only messages are still included.

`reply_to_message_id` stores the first reply ID found in album message-ID order.
For a normal message, it is the ID of the message it replies to; otherwise it is
`None`. The referenced message is not fetched, and the original `text` is left
unchanged. The field preserves the message ID only, not a cross-chat peer or
thread root.

Image failures are logged and preserve the logical message. Translation runs
only for `translation_channels`; successful output is stored separately from
the original text.

History normalizes the channel stream sequentially and translates eligible
messages in batches of up to 20 using `messages.translateText(peer=..., id=[...])`.
Messages without translatable text do not consume translation batch capacity.
Each batch stays within 25,000 UTF-16 code units of original Telegram text.
A single message exceeding that size is attempted alone.
These are local batching policies based on the
[official Android client](https://github.com/DrKLO/Telegram/blob/master/TMessagesProj/src/main/java/org/telegram/messenger/TranslateController.java),
not published server limits.

Translations are assigned in request order only when the response contains
exactly one result per requested ID. Incomplete or oversized result vectors
leave the whole batch untranslated; an empty translation leaves only its
corresponding message untranslated. Stored original and translated text are
Unicode-repaired and emoji-stripped.

History retries translation timeouts, transient Telegram server failures, and
`TRANSLATE_REQ_QUOTA_EXCEEDED` up to `translation_retries`. It also waits for
Telegram `FloodWait` durations before retrying. Other transient retries use
exponential backoff starting at one second, capped at 30 seconds per wait,
including quota, timeout, and server failures. Other translation
failures are logged without a retry. Any translation failure preserves the
original message, and a failed batch does not prevent later batches.

These are Gateway retries in addition to any retries configured on the
supplied Telethon client. `raise_last_call_error=True` preserves the last RPC
error for classification; `flood_sleep_threshold=0` lets Gateway handle
translation FloodWaits directly. Both options affect the whole client and
remain caller choices; see [session.md](session.md).

Translation is optional and fails open. Before using a dataset for a translated
backtest, the application should count missing translations among configured
messages with text and decide whether to stop or accept that coverage.

Channel resolution, authorization, and history retrieval failures propagate to
the caller.

## Memory

`fetch()` returns one complete list, including downloaded image bytes. Memory
therefore grows with range size, channel volume, and image size. Choose bounded
ranges and persist or batch results in the calling application.
