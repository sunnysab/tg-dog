import asyncio
import json
import pathlib
from typing import Any, Awaitable, Callable, Dict


class IpcError(RuntimeError):
    pass


def _ensure_parent(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _encode(obj: Dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


async def send_request(socket_path: str, request: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(_encode(request))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            raise IpcError("No response from daemon")
        return _decode(line)
    finally:
        writer.close()
        await writer.wait_closed()


async def start_server(
    socket_path: str,
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
    logger,
) -> asyncio.AbstractServer:
    path = pathlib.Path(socket_path)
    _ensure_parent(path)
    if path.exists():
        path.unlink()

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            request = _decode(line)
            response = await handler(request)
        except Exception as exc:
            logger.exception("IPC handler error: %s", exc)
            response = {"ok": False, "error": str(exc)}
        writer.write(_encode(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_unix_server(_handle, path=str(path))
