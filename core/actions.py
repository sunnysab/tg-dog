import asyncio
import pathlib
from typing import AsyncIterator, Optional

from telethon.errors import FloodWaitError
from telethon.tl.types import (
    InputMessagesFilterPhotos,
    InputMessagesFilterVideo,
    InputMessagesFilterDocument,
    InputMessagesFilterAudio,
)
from tqdm import tqdm


async def _sleep_on_floodwait(exc: FloodWaitError, logger) -> None:
    wait_seconds = max(int(getattr(exc, "seconds", 0)), 1)
    logger.warning("FloodWaitError: sleeping for %s seconds", wait_seconds)
    await asyncio.sleep(wait_seconds)


async def _call_with_floodwait(coro_factory, logger, max_retries: Optional[int] = None):
    attempts = 0
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as exc:
            await _sleep_on_floodwait(exc, logger)
            attempts += 1
            if max_retries is not None and attempts > max_retries:
                raise


def _resolve_media_filter(media_type: str):
    if media_type == "photo":
        return InputMessagesFilterPhotos
    if media_type == "video":
        return InputMessagesFilterVideo
    if media_type == "document":
        return InputMessagesFilterDocument
    if media_type == "audio":
        return InputMessagesFilterAudio
    return None


async def send_message(client, target: str, text: str, logger) -> None:
    await _call_with_floodwait(lambda: client.send_message(target, text), logger)


async def interactive_send(client, target: str, text: str, logger, timeout: int = 30):
    async def _send_and_wait():
        async with client.conversation(target, timeout=timeout) as conv:
            await conv.send_message(text)
            return await conv.get_response(timeout=timeout)

    try:
        response = await _call_with_floodwait(_send_and_wait, logger)
        return response
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for response from %s", target)
        return None
    except FloodWaitError as exc:
        await _sleep_on_floodwait(exc, logger)
        return None


async def _iter_messages_with_floodwait(client, target: str, logger, **kwargs) -> AsyncIterator:
    iterator = client.iter_messages(target, **kwargs)
    while True:
        try:
            message = await iterator.__anext__()
        except StopAsyncIteration:
            break
        except FloodWaitError as exc:
            await _sleep_on_floodwait(exc, logger)
            continue
        else:
            yield message


async def list_messages(client, target: str, limit: int, logger):
    results = []
    async for message in _iter_messages_with_floodwait(client, target, logger, limit=limit):
        snippet = (message.text or "").strip().replace("\n", " ")
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        results.append(
            {
                "id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "sender_id": message.sender_id,
                "snippet": snippet,
            }
        )
    return results


async def download_media(
    client,
    target: str,
    limit: int,
    logger,
    media_type: str = "any",
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    output_dir: str = "downloads",
):
    output_path = pathlib.Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    message_filter = _resolve_media_filter(media_type)

    downloaded = 0
    async for message in _iter_messages_with_floodwait(
        client,
        target,
        logger,
        limit=limit,
        filter=message_filter,
    ):
        if not message.media or not message.file:
            continue
        file_size = message.file.size or 0
        if min_size is not None and file_size < min_size:
            continue
        if max_size is not None and file_size > max_size:
            continue

        filename = message.file.name or f"{message.id}"
        destination = output_path / filename

        with tqdm(total=file_size, unit="B", unit_scale=True, desc=filename) as bar:
            def _progress(current, total):
                bar.total = total or bar.total
                bar.update(current - bar.n)

            try:
                await _call_with_floodwait(
                    lambda: message.download_media(file=destination, progress_callback=_progress),
                    logger,
                )
            except Exception:
                logger.exception("Failed to download media for message %s", message.id)
                continue
        downloaded += 1
    return downloaded
