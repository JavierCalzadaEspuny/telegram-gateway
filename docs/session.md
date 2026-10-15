# Runtime session

`TelegramSession` owns one Telethon client backed by the project-local login:

```python
from telegram_gateway import TelegramSession

async with TelegramSession() as client:
    # The client is connected and authorized here.
    ...
```

The project root defaults to the current working directory. Pass it explicitly
when the application can start elsewhere:

```python
session = TelegramSession(project_root, receive_updates=True)
client = await session.connect()
try:
    ...
finally:
    await session.disconnect()
```

Keyword arguments after `project_root` are forwarded to Telethon's
`TelegramClient`. TelegramGateway always supplies the session path, API ID, and
API hash from the project-local login.

## Request policy

Telethon owns transport retries and reconnection. The listener adds no
translation retries. Keep update reception enabled for the listener. For
example, a caller can choose:

```python
session = TelegramSession(
    receive_updates=True,
    raise_last_call_error=True,
    flood_sleep_threshold=0,
)
```

`raise_last_call_error=True` preserves the last RPC exception instead of
Telethon's generic error after exhausted retries. `flood_sleep_threshold=0`
exposes FloodWaits immediately, so the listener's translator can emit the
original text. These settings also apply to startup and other RPCs, whose
errors propagate to the caller.

Reducing `request_retries` can reduce hidden waits but weakens transport
recovery; zero retries can prevent a migrated request from being resent. Choose
these options on `TelegramSession` or the supplied client. The listener does
not mutate client request settings. Its translation timeout includes waiting
for a concurrency slot and Telethon's request handling.

## Lifecycle

`connect()` reads `.telegram/.env`, derives the session name from the digits in
`TELEGRAM_PHONE`, requires the corresponding `.session` file, connects the
client, and checks authorization. It returns that connected client. The same
client is available through `session.client` until `disconnect()` succeeds.

Calling `connect()` twice or reading `client` before connecting is an invalid
runtime state. `disconnect()` is safe when already disconnected. Connection or
authorization failures disconnect the temporary client before propagating.

`TelegramSessionError` reports missing or malformed login configuration,
missing session files, and sessions that are no longer authorized. Run
`uv run telegram-login` from the same project root to create or renew the
login. Runtime session opening is deliberately non-interactive.

## Ownership

The `TelegramSession` instance owns and disconnects the client it creates.
`TelegramListener` borrows that connected client and never disconnects it.
The application still decides when the runtime starts and ends,
which client options it needs, and whether or how to restart after failure.
