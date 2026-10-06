# Architecture

```text
telegram-login -> .telegram/.env + .telegram/sessions/<phone>.session

TelegramSession -> connected, authorized TelegramClient
    ├── TelegramListener -> asyncio.Queue[TelegramMessage | None]
    └── TelegramHistory  -> list[TelegramMessage]
                  \-> MessageProcessor
```

The explicit login command owns preparation, interactive authorization, and
the temporary client it creates. `TelegramSession` owns runtime configuration
loading, client creation, connection, authorization checks, and disconnection.
Applications decide when to connect and disconnect, which Telethon options to
use, and how to store messages or restart. No runtime component invokes
interactive login.

## Modules

- `_listener.py`: Telethon events, queue backpressure, and shutdown.
- `_history.py`: bounded sequential pagination, album grouping, sorting, and
  optional progress.
- `_processing.py`: shared validation, text cleanup, channel metadata, media
  and reply metadata, images, and translation.
- `_models.py`: immutable `TelegramMessage` and deterministic IDs.
- `_session.py`: project-local paths, runtime credentials, and managed clients.
- `login.py`: project-local credential preparation and interactive login.
- `__init__.py`: the public session, retrieval, and message types.

Both workflows use the same processing rules but different latency policies.
Listener translates individual live messages, is concurrency-limited, and
never adds Gateway retries. History translates bounded batches per channel
and may retry known transient translation failures. Images and translation fail open;
retrieval errors do not.

Telethon owns pagination, native album assembly, entity caching, transport
retries, reconnection, and media decoding. Listener waits on its public
disconnection future without taking ownership of the client. A single read of
Telethon 1.45's private `_updates_error` preserves fatal update-error
propagation, which its public future does not expose. Review that compatibility
point when upgrading Telethon.

Login deliberately remains a standalone command. `TelegramSession` reuses its
project-local layout but never prompts, mutates credentials, or authorizes a
missing session. There are no global paths, account profiles, automatic login,
or application restart policy. The package has no message persistence, JSON
writer, database, OCR, worker, notification, or application-policy layer.
