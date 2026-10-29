# TelegramGateway contributor guide

## Scope

TelegramGateway is a small Telethon wrapper for live channel messages:

- `telegram-login` authorizes a saved session in an explicit directory.
- `TelegramSession` loads that session and owns one connected runtime client.
- `TelegramListener` sends configured live channels to
  `asyncio.Queue[TelegramMessage | None]`.

Keep explicit persistent login, attachment metadata, optional photo/video downloads,
albums, optional translation, deterministic IDs, and listener backpressure.
Do not add message persistence, JSON output, databases, OCR, workers,
notifications, or application policy.

Maintain only the current public API. Do not add legacy aliases, deprecated
arguments, migration layers, or backward-compatibility paths.

## Ownership

The login command owns interactive authorization, credentials.json and account.session
inside a caller-supplied directory. Save API credentials only after authorization;
never persist phone input, login codes or 2FA passwords in credential metadata.

`TelegramSession` loads the same explicit directory and owns its client lifecycle.
Runtime never starts interactive login. The listener only borrows its client.
Do not add global application paths, account managers, profiles or compatibility layers.

Channel enrichment options belong to immutable `TelegramChannel` objects.
The `translate` boolean enables English translation; there is no language option.
Use `download_photos` and `download_videos` for optional attachment downloads.
Fixed channels and processing limits are validated when a listener is
created. Do not add mutable setters. Use `ValueError` for invalid arguments and
`RuntimeError` for invalid runtime state.

TelegramMedia and TelegramMessage are plain frozen dataclasses built by the processor.
TelegramChannel uses a frozen Pydantic dataclass; listener inputs use validate_call.
TelegramMessage.searchable_text prefers translation without storing a duplicate field.
Keep `media` as the single attachment collection and `has_media` as a computed
property. Do not add output field validators, duplicate image/video views,
serialization methods, or custom JSON representations. Telegram owns username
format acceptance; Gateway validates local configuration only.

Media downloads and translation are optional enrichment; external requests and
responses fail open. Keep mapping and request preparation outside their catches
so programming errors reach the listener's event-error handler. Always
preserve attachment records and original captions independently of downloads.
Keep original and translated text unchanged; cleanup belongs to callers.
Connection, authorization, and channel-resolution errors propagate. Listener translation
has bounded concurrency and no retry. Photo/video downloads have bounded
concurrency, a timeout, and a configurable per-attachment byte limit.

## Layout

```text
src/telegram_gateway/
    __init__.py
    _listener.py
    _processing.py
    _models.py
    _session.py
    login.py
smoke/
    listener.py
docs/
    architecture.md
    session.md
    listener.md
    login.md
    testing.md
```

Keep control flow direct. Do not add facades, services, repositories, adapters,
configuration frameworks, or dependencies without a demonstrated need.
Smoke workflow settings belong as constants in their scripts; do not add a
second environment file or smoke-specific configuration layer.

## Verification

Do not add permanent tests. Use exact disposable paths under `/private/tmp`,
then remove them. Do not run real Telegram calls during routine review.

```bash
.venv/bin/python -m compileall -q src smoke/listener.py
uv lock --check
uv build --wheel
git diff --check
```

Remove generated build and cache artifacts. Confirm that no credentials,
sessions, `.env`, tests, or generated data are tracked.

Do not commit, push, merge, or create a pull request unless explicitly asked.
