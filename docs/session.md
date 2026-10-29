# Runtime session

```python
from pathlib import Path
from telegram_gateway import TelegramSession

async with TelegramSession(Path("/data/auth/telegram"), receive_updates=True) as client:
    ...
```

The explicit directory contains `credentials.json` and `account.session`.
The session owns its client; the listener only borrows it.

`connect()` loads credentials, requires the existing session, connects and checks
authorization. Missing or revoked sessions raise `TelegramSessionError` without
interactive login. Failed connections disconnect before propagating errors.

`disconnect()` closes the owned client. Calling `connect()` twice is an error.
Use `session.client` only while connected. Client options, retry policy, storage
location and restarts belong to the caller. Telethon owns transport reconnection.
