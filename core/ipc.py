import asyncio
import json
import pathlib
import struct
from typing import Any, Awaitable, Callable, Dict


class IpcError(RuntimeError):
    pass


def _ensure_parent(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


_LENGTH_STRUCT = struct.Struct(">I")


def _encode(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _decode(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


def _frame_message(obj: Dict[str, Any]) -> bytes:
    payload = _encode(obj)
    return _LENGTH_STRUCT.pack(len(payload)) + payload


async def _read_message(reader: asyncio.StreamReader, timeout: int | None = None) -> Dict[str, Any]:
    try:
        if timeout is None:
            header = await reader.readexactly(_LENGTH_STRUCT.size)
        else:
            header = await asyncio.wait_for(reader.readexactly(_LENGTH_STRUCT.size), timeout=timeout)
    except asyncio.IncompleteReadError as exc:
        raise IpcError("No response from daemon") from exc
    length = _LENGTH_STRUCT.unpack(header)[0]
    if length == 0:
        return {}
    try:
        if timeout is None:
            payload = await reader.readexactly(length)
        else:
            payload = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    except asyncio.IncompleteReadError as exc:
        raise IpcError("Incomplete response from daemon") from exc
    return _decode(payload)


async def send_request(socket_path: str, request: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(_frame_message(request))
        await writer.drain()
        return await _read_message(reader, timeout=timeout)
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
            request = await _read_message(reader)
            response = await handler(request)
        except Exception as exc:
            logger.exception("IPC handler error: %s", exc)
            response = {"ok": False, "error": str(exc)}
        writer.write(_frame_message(response))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_unix_server(_handle, path=str(path))
