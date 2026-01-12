import asyncio
import mimetypes
import pathlib
from typing import AsyncIterator, Optional

from telethon.errors import FloodWaitError
from telethon.tl.types import (
    InputMessagesFilterPhotos,
    InputMessagesFilterVideo,
    InputMessagesFilterDocument,
    InputMessagesFilterMusic,
    InputMessagesFilterVoice,
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
        return InputMessagesFilterMusic
    if media_type == "voice":
        return InputMessagesFilterVoice
    return None


async def _resolve_target(client, target: str, logger):
    if not isinstance(target, str):
        return target
    value = target.strip()
    if not value:
        raise ValueError("Target is empty")
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        numeric = int(value)
        try:
            return await client.get_input_entity(numeric)
        except Exception:
            logger.debug("Failed to resolve numeric target %s via cache", value)
            return numeric
    return value


async def send_message(client, target: str, text: str, logger) -> None:
    entity = await _resolve_target(client, target, logger)
    await _call_with_floodwait(lambda: client.send_message(entity, text), logger)


async def interactive_send(client, target: str, text: str, logger, timeout: int = 30):
    async def _send_and_wait():
        entity = await _resolve_target(client, target, logger)
        async with client.conversation(entity, timeout=timeout) as conv:
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


async def _iter_dialogs_with_floodwait(client, logger, limit: int) -> AsyncIterator:
    iterator = client.iter_dialogs(limit=limit)
    while True:
        try:
            dialog = await iterator.__anext__()
        except StopAsyncIteration:
            break
        except FloodWaitError as exc:
            await _sleep_on_floodwait(exc, logger)
            continue
        else:
            yield dialog


async def list_messages(client, target: str, limit: int, logger):
    results = []
    entity = await _resolve_target(client, target, logger)
    async for message in _iter_messages_with_floodwait(client, entity, logger, limit=limit):
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


def _dialog_kind(entity) -> str:
    name = entity.__class__.__name__.lower()
    if getattr(entity, "bot", False):
        return "bot"
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False) or name == "chat":
        return "group"
    if name == "user":
        return "user"
    return name


def _dialog_target(entity) -> str | None:
    entity_id = getattr(entity, "id", None)
    if entity_id is None:
        return None
    is_channel = bool(getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False))
    if is_channel:
        return f"-100{entity_id}"
    return str(entity_id)


async def list_dialogs(client, limit: int, logger):
    results = []
    async for dialog in _iter_dialogs_with_floodwait(client, logger, limit=limit):
        entity = dialog.entity
        results.append(
            {
                "id": getattr(entity, "id", None),
                "name": dialog.name,
                "username": getattr(entity, "username", None),
                "kind": _dialog_kind(entity),
                "target": _dialog_target(entity),
            }
        )
    return results


def _safe_filename(value: str) -> str:
    safe = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_"):
            safe.append(ch)
        else:
            safe.append("_")
    name = "".join(safe).strip("_")
    return name or "export"


def _format_message_markdown(message, attachments: list[str]) -> str:
    date = message.date.isoformat() if message.date else ""
    sender = message.sender_id
    header = f"### {date} | id={message.id} | from={sender}\n\n"
    text = (message.text or "").strip()
    if not text:
        text = "_(no text)_"
    body = f"{text}\n\n"
    if attachments:
        lines = ["Attachments:"]
        for item in attachments:
            if item.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                lines.append(f"- ![]({item})")
            else:
                lines.append(f"- [{item}]({item})")
        body += "\n".join(lines) + "\n\n"
    return header + body


async def export_messages(
    client,
    target: str,
    logger,
    output: str,
    mode: str = "single",
    attachments_dir: Optional[str] = None,
    limit: Optional[int] = None,
    from_user: Optional[str] = None,
    message_ids: Optional[list[int]] = None,
):
    entity = await _resolve_target(client, target, logger)
    mode = mode.lower()
    output_path = pathlib.Path(output)

    if mode not in {"single", "per_message"}:
        raise ValueError("mode must be 'single' or 'per_message'")

    if mode == "single":
        if output_path.suffix.lower() == ".md":
            output_file = output_path
            output_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / f"{_safe_filename(str(target))}.md"
        base_dir = output_file.parent
    else:
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = None
        base_dir = output_path

    attachments_base = pathlib.Path(attachments_dir) if attachments_dir else base_dir / "attachments"
    attachments_base.mkdir(parents=True, exist_ok=True)

    resolved_from_user = None
    if from_user:
        resolved_from_user = await _resolve_target(client, from_user, logger)

    if message_ids:
        messages = await client.get_messages(entity, ids=message_ids)
        if not isinstance(messages, list):
            messages = [messages]
        messages = [msg for msg in messages if msg is not None]
        messages.sort(key=lambda msg: msg.date or 0)
        iterator = iter(messages)
    else:
        iterator = _iter_messages_with_floodwait(
            client,
            entity,
            logger,
            limit=limit,
            reverse=True,
            from_user=resolved_from_user,
        )

    exported = 0
    writer = None
    if output_file:
        writer = output_file.open("w", encoding="utf-8")

    async def _process(message):
        nonlocal exported
        attachments = []
        if message.file:
            ext = message.file.ext or ""
            if not ext and message.file.mime_type:
                ext = mimetypes.guess_extension(message.file.mime_type) or ""
            name = message.file.name or f"{message.id}{ext}"
            filename = f"{message.id}_{name}"
            destination = attachments_base / filename
            try:
                await _call_with_floodwait(
                    lambda: message.download_media(file=destination),
                    logger,
                )
                relpath = pathlib.Path(destination).relative_to(base_dir)
                attachments.append(relpath.as_posix())
            except Exception:
                logger.exception("Failed to download attachment for message %s", message.id)

        content = _format_message_markdown(message, attachments)
        if mode == "single":
            writer.write(content)
        else:
            message_file = base_dir / f"{message.id}.md"
            message_file.write_text(content, encoding="utf-8")
        exported += 1

    try:
        if message_ids:
            for message in messages:
                await _process(message)
        else:
            async for message in iterator:
                await _process(message)
    finally:
        if writer:
            writer.close()

    return {"exported": exported, "output": str(output_file or base_dir)}


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
    entity = await _resolve_target(client, target, logger)

    downloaded = 0
    async for message in _iter_messages_with_floodwait(
        client,
        entity,
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
