import asyncio
import pathlib
from typing import Optional

from telethon import TelegramClient


class ClientManager:
    def __init__(self, api_id: int, api_hash: str, phone_number: str, session_dir: str = "sessions") -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone_number = phone_number
        self.session_dir = pathlib.Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._client: Optional[TelegramClient] = None

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise RuntimeError("Client not initialized")
        return self._client

    def _build_client(self, session_name: str) -> TelegramClient:
        session_path = self.session_dir / f"{session_name}.session"
        return TelegramClient(str(session_path), self.api_id, self.api_hash)

    async def connect(self, session_name: str) -> TelegramClient:
        self._client = self._build_client(session_name)
        await self._client.connect()
        return self._client

    async def ensure_authorized(self, interactive: bool = True) -> bool:
        if self._client is None:
            raise RuntimeError("Client not connected")
        if await self._client.is_user_authorized():
            return True
        if not interactive:
            return False
        # Telethon handles interactive login (code, 2FA) in start()
        await self._client.start(phone=self.phone_number)
        return True

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None


async def safe_disconnect(manager: "ClientManager") -> None:
    try:
        await manager.disconnect()
    except asyncio.CancelledError:
        raise
    except Exception:
        # Best-effort disconnect
        return
