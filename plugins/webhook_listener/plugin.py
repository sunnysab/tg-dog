import argparse
import asyncio
import json
import urllib.request

from telethon import events


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--method", default="POST")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--header", action="append", default=[])
    return parser.parse_args(args)


def _normalize_target(target: str):
    value = target.strip()
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


def _headers_from_args(headers: list[str]) -> dict:
    result = {"Content-Type": "application/json"}
    for item in headers:
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _post(url: str, method: str, payload: dict, headers: dict, timeout: int) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


async def setup(context, args):
    logger = context["logger"]
    client = context["client"]
    options = _parse_args(args)
    headers = _headers_from_args(options.header)
    target = _normalize_target(options.target)

    try:
        entity = await client.get_input_entity(target)
    except Exception:
        entity = target
        logger.info("Using raw target for listener: %s", target)

    async def _handle(event):
        payload = {
            "chat_id": event.chat_id,
            "message_id": event.id,
            "text": event.raw_text,
            "date": event.date.isoformat() if event.date else None,
            "sender_id": event.sender_id,
        }
        await asyncio.to_thread(
            _post,
            options.url,
            options.method,
            payload,
            headers,
            options.timeout,
        )

    client.add_event_handler(_handle, events.NewMessage(chats=entity))
    logger.info("Webhook listener registered for %s", options.target)
