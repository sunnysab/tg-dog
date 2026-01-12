import argparse
import asyncio
import mimetypes
import pathlib

import typer
from telethon.errors import FloodWaitError

app = typer.Typer(help="搜索 VmomoVBot 并下载歌曲")


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--query", required=True)
    parser.add_argument("--target", default="@VmomoVBot")
    parser.add_argument("--choice", type=int, default=1)
    parser.add_argument("--keyword")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--max-wait", type=int, default=5)
    parser.add_argument("--output", default="downloads/vmomo")
    parser.add_argument("--filename")
    return parser.parse_args(args)


def _normalize_target(target: str):
    value = target.strip()
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


def _collect_buttons(message):
    buttons = []
    if not message.buttons:
        return buttons
    for row_index, row in enumerate(message.buttons):
        for col_index, btn in enumerate(row):
            text = getattr(btn, "text", "")
            buttons.append({"text": text, "row": row_index, "col": col_index})
    return buttons


def _select_button(buttons: list[dict], choice: int, keyword: str | None):
    if not buttons:
        return None
    if keyword:
        for btn in buttons:
            if keyword in btn.get("text", ""):
                return btn
    index = max(choice, 1) - 1
    if index >= len(buttons):
        return buttons[0]
    return buttons[index]


def _guess_filename(message, override: str | None) -> str:
    if override:
        return override
    if message.file and message.file.name:
        return message.file.name
    ext = ""
    if message.file and message.file.ext:
        ext = message.file.ext
    elif message.file and message.file.mime_type:
        ext = mimetypes.guess_extension(message.file.mime_type) or ""
    return f"{message.id}{ext or ''}"


async def _call_with_floodwait(coro_factory, logger):
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, "seconds", 0)), 1)
            logger.warning("FloodWaitError: sleeping for %s seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _search_and_download(
    context,
    query: str,
    target: str,
    choice: int,
    keyword: str | None,
    timeout: int,
    max_wait: int,
    output: str,
    filename: str | None,
):
    logger = context["logger"]
    client = context["client"]
    target_entity = _normalize_target(target)

    output_dir = pathlib.Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with client.conversation(target_entity, timeout=timeout) as conv:
        await _call_with_floodwait(lambda: conv.send_message(query), logger)
        response = await _call_with_floodwait(lambda: conv.get_response(timeout=timeout), logger)

        buttons = _collect_buttons(response)
        if not buttons:
            raise RuntimeError("No candidates returned from bot")
        for index, btn in enumerate(buttons, start=1):
            logger.info("[%s] %s", index, btn.get("text"))

        selected = _select_button(buttons, choice, keyword)
        if not selected:
            raise RuntimeError("No button selected")
        await _call_with_floodwait(
            lambda: response.click(row=selected["row"], col=selected["col"]),
            logger,
        )

        media_message = None
        for _ in range(max_wait):
            message = await _call_with_floodwait(lambda: conv.get_response(timeout=timeout), logger)
            if message.media or message.file:
                media_message = message
                break
        if not media_message:
            raise RuntimeError("No media message received from bot")

        file_name = _guess_filename(media_message, filename)
        destination = output_dir / file_name
        await _call_with_floodwait(lambda: media_message.download_media(file=destination), logger)
        logger.info("Downloaded to %s", destination)
        return {"file": str(destination)}


async def run(context, args):
    options = _parse_args(args)
    return await _search_and_download(
        context,
        query=options.query,
        target=options.target,
        choice=options.choice,
        keyword=options.keyword,
        timeout=options.timeout,
        max_wait=options.max_wait,
        output=options.output,
        filename=options.filename,
    )


@app.command()
def search(
    query: str = typer.Option(..., "--query"),
    target: str = typer.Option("@VmomoVBot", "--target"),
    choice: int = typer.Option(1, "--choice"),
    keyword: str = typer.Option(None, "--keyword"),
    timeout: int = typer.Option(15, "--timeout"),
    max_wait: int = typer.Option(5, "--max-wait"),
    output: str = typer.Option("downloads/vmomo", "--output"),
    filename: str = typer.Option(None, "--filename"),
):
    ctx = typer.get_current_context()
    context = ctx.obj or {}
    call = context.get("call")
    if call is None:
        raise RuntimeError("context.call is required for CLI mode")
    call(
        _search_and_download(
            context,
            query=query,
            target=target,
            choice=choice,
            keyword=keyword,
            timeout=timeout,
            max_wait=max_wait,
            output=output,
            filename=filename,
        )
    )
