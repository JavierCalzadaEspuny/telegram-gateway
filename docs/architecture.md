# Architecture

```text
telegram-login --directory PATH -> credentials.json + account.session

TelegramSession -> connected, authorized TelegramClient
TelegramChannel -> fixed options for one monitored channel
TelegramListener borrows client
    ├── NewMessage / Album -> MessageProcessor -> TelegramMessage | None
    │                              └── TelegramMedia metadata + optional bytes
    └── queue -> asyncio.Queue[TelegramMessage | None]
```

Login owns preparation, interactive authorization, and its temporary client.
`TelegramSession` owns runtime configuration loading, client creation,
connection, authorization checks, and disconnection. Applications choose when
to connect, disconnect, store messages, or restart. Runtime never invokes login.

## Modules

- `_listener.py`: fixed configuration validation, event handlers, queue pressure,
  task ownership, and shutdown.
- `_processing.py`: fixed rules bound to resolved peer IDs, message/album mapping,
  cached channel metadata, attachment classification, optional downloads,
  and optional English translation.
- `_models.py`: immutable `TelegramChannel`, `TelegramMessage`, `TelegramMedia`,
  derived text/media properties, and deterministic IDs.
- `_session.py`: explicit directory, validated runtime credentials, and managed clients.
- `login.py`: interactive authorization and private credential persistence.
- `__init__.py`: public listener, session, channel, and packet types.

## Packet construction

The processor packages source values without text cleanup or application policy.
Every attachment keeps its original message ID and caption even if its bytes
are absent. Albums use the smallest source ID for identity and select the first
nonempty caption for the convenient original-text and translation fields.
Caption provenance remains in each media record.

The output has one media tuple; `has_media` returns `bool(media)`.
`searchable_text` selects translation, then original text, without changing either.
Output dataclasses have no field validators or serialization methods; the
processor constructs their values. Configuration is validated at construction,
while Telegram owns username acceptance. Each channel's boolean `translate`
enables English translation. Capturing attachment
metadata needs no download. Optional downloads and translation each
have a semaphore and timeout; downloads also have a per-attachment byte limit.
External enrichment requests and their responses fail open without Gateway
retries. Mapping and request-preparation errors reach the listener's error
handler rather than being treated as enrichment failures. Startup connection,
authorization, and channel-resolution errors propagate. Event-processing errors
are logged without stopping the listener.

## Ownership

Telethon owns native album assembly, entity caching, transport retries,
reconnection, and media decoding. Listener waits on the public disconnection
future without owning the client. A read of Telethon 1.45's private
`_updates_error` preserves fatal update errors that its public future does not
expose. Review this use of a private attribute when upgrading Telethon.

Listener owns its handlers, processing tasks, and output queue. A full bounded
queue drops an incoming completed packet; shutdown cancels owned enrichment
and enqueues `None`, discarding one buffered packet if necessary.

The package has no history retrieval, message persistence, JSON writer,
database, OCR, workers, notifications, or application-policy layer. Login and
runtime sessions use an explicit caller-owned directory with no account profiles, global paths,
automatic authorization, or application restart policy.
