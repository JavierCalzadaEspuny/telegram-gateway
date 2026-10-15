# Architecture

```text
telegram-login -> .telegram/.env + .telegram/sessions/<phone>.session

TelegramSession -> connected, authorized TelegramClient
TelegramListener borrows client
    ├── NewMessage / Album -> MessageProcessor -> TelegramMessage | None
    └── queue -> asyncio.Queue[TelegramMessage | None]
```

The explicit login command owns preparation, interactive authorization, and
the temporary client it creates. `TelegramSession` owns runtime configuration
loading, client creation, connection, authorization checks, and disconnection.
Applications decide when to connect and disconnect, which Telethon options to
use, and how to store messages or restart. No runtime component invokes
interactive login.

## Modules

- `_listener.py`: Telethon events, queue backpressure, and shutdown.
- `_processing.py`: listener validation, text cleanup, channel metadata, media
  and reply metadata, images, and translation.
- `_models.py`: immutable `TelegramMessage` and deterministic IDs.
- `_session.py`: project-local paths, runtime credentials, and managed clients.
- `login.py`: project-local credential preparation and interactive login.
- `__init__.py`: the public listener, session, and message types.

The listener validates its fixed configuration once, then processes each new
message or native album through one normalization and enrichment path. The
processor builds a single immutable message after optional image download and
translation. Translation uses a semaphore and a timeout that includes waiting
for that semaphore; it adds no retries. Images and translation fail open.
Connection, authorization, and startup channel-resolution errors propagate;
individual event-processing failures are logged without stopping the listener.

Telethon owns native album assembly, entity caching, transport
retries, reconnection, and media decoding. Listener waits on its public
disconnection future without taking ownership of the client. A single read of
Telethon 1.45's private `_updates_error` preserves fatal update-error
propagation, which its public future does not expose. Review that compatibility
point when upgrading Telethon.

The listener owns its event handlers, processing tasks, and output queue. It
never disconnects the supplied client. A full bounded queue drops the incoming
message. Shutdown cancels pending enrichment and always enqueues `None`,
discarding one buffered message if necessary to make room.

Login deliberately remains a standalone command. `TelegramSession` reuses its
project-local layout but never prompts, mutates credentials, or authorizes a
missing session. There are no global paths, account profiles, automatic login,
or application restart policy. The package has no message persistence, JSON
writer, database, OCR, worker, notification, or application-policy layer.
