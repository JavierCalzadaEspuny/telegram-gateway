"""Authorize Telegram once and save credentials beside the native session."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Sequence

from pydantic import TypeAdapter, validate_call
from telethon import TelegramClient

from ._session import _load_credentials, _TelegramCredentials, TelegramSessionError


@validate_call
async def login(directory: Path) -> Path:
    """Authorize an account; never save its phone, code or 2FA password."""
    directory = directory.expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    credentials_file = directory / "credentials.json"
    try:
        credentials = _load_credentials(directory)
    except TelegramSessionError:
        credentials = _TelegramCredentials(
            api_id=int(input("Telegram API ID: ")), api_hash=getpass("Telegram API hash: ").strip(),
        )
    session = directory / "account.session"
    client = TelegramClient(str(session), credentials.api_id, credentials.api_hash)
    try:
        await client.start(
            phone=lambda: input("Telegram phone: ").strip(),
            code_callback=lambda: input("Telegram code: ").strip(),
            password=lambda: getpass("Telegram 2FA password: "),
        )
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram did not authorize the session")
        with NamedTemporaryFile(dir=directory, delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(TypeAdapter(_TelegramCredentials).dump_json(credentials))
                file.close()
                os.replace(temporary, credentials_file)
            finally:
                temporary.unlink(missing_ok=True)
    finally:
        await client.disconnect()
        if session.exists():
            session.chmod(0o600)
    return session


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="telegram-login", description="Authorize a saved Telegram session")
    parser.add_argument("--directory", type=Path, required=True, help="Persistent directory for credentials and session")
    arguments = parser.parse_args(argv)
    print(f"Telegram session ready at {asyncio.run(login(arguments.directory))}")


if __name__ == "__main__":
    main()
