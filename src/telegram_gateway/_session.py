"""Connect a runtime client using an explicitly located Telegram login."""

from __future__ import annotations

from dataclasses import field
from pathlib import Path
from types import TracebackType
from typing import Annotated

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, validate_call
from pydantic.dataclasses import dataclass
from telethon import TelegramClient


class TelegramSessionError(RuntimeError):
    """The saved Telegram credentials or session are unusable."""


@dataclass(frozen=True, slots=True, config=ConfigDict(extra="forbid", hide_input_in_errors=True))
class _TelegramCredentials:
    api_id: Annotated[int, Field(gt=0, strict=True)]
    api_hash: Annotated[str, Field(pattern=r"\S", strict=True)] = field(repr=False)


def _load_credentials(directory: Path) -> _TelegramCredentials:
    try:
        return TypeAdapter(_TelegramCredentials).validate_json((directory / "credentials.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TelegramSessionError(f"Run telegram-login --directory {directory} first") from None
    except (ValidationError, UnicodeError):
        raise TelegramSessionError(f"Invalid Telegram credentials; run telegram-login --directory {directory}") from None


class TelegramSession:
    """Own one client backed by credentials.json and account.session."""

    @validate_call
    def __init__(self, directory: Path, **client_options: object) -> None:
        self._directory = directory.expanduser().resolve()
        self._client_options = client_options
        self._client: TelegramClient | None = None

    @property
    def client(self) -> TelegramClient:
        """Return the owned connected client."""
        if self._client is None:
            raise RuntimeError("Telegram session is not connected")
        return self._client

    async def connect(self) -> TelegramClient:
        """Connect an existing authorized session without interactive login."""
        if self._client is not None:
            raise RuntimeError("Telegram session is already connected")
        credentials = _load_credentials(self._directory)
        session = self._directory / "account.session"
        if not session.is_file():
            raise TelegramSessionError(f"Run telegram-login --directory {self._directory} first")
        client = TelegramClient(str(session), credentials.api_id, credentials.api_hash, **self._client_options)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramSessionError(f"Telegram session is not authorized; run telegram-login --directory {self._directory}")
        except BaseException:
            await client.disconnect()
            raise
        self._client = client
        return client

    async def disconnect(self) -> None:
        """Disconnect the owned client, if connected."""
        if self._client is None:
            return
        await self._client.disconnect()
        self._client = None

    async def __aenter__(self) -> TelegramClient:
        return await self.connect()

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        await self.disconnect()
