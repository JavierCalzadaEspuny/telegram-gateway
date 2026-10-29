# Manual smoke check

Authorize first, then run the real listener only when explicitly requested:

```sh
uv run telegram-login --directory ~/.local/share/telegram-osint/auth/telegram
uv run python smoke/listener.py
```

The smoke script owns SESSION_DIRECTORY and channel settings. It connects to
Telegram, prints native messages, and stops on Ctrl+C. Its consumer always calls
task_done(). Keep credentials and session files private.

Routine checks use fake clients and disposable directories without Telegram calls.
Do not commit test scripts or runtime data.
