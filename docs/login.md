# Login

Run `telegram-login --directory /path/to/auth/telegram`.
The command creates the directory and authorizes one account.

- `credentials.json`: API ID and API hash, saved after successful authorization.
- `account.session`: native Telethon session.
- Directories use mode 700; credential and session files use mode 600.

The phone, code and 2FA password are requested only when needed and are not
persisted by the login command. Existing valid sessions require no prompts.
No `.env`, preparation command or current-directory convention is required.

`telegram_gateway.login.login(directory: Path)` exposes the same async flow to
applications. The caller owns the directory; no application-wide path is chosen
by the library. Keep one running client per session file.
