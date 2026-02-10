import argparse
import asyncio
from dataclasses import dataclass
import mimetypes
import pathlib

import click
import typer
from telethon import events
from telethon.errors import FloodWaitError

from core.actions import _safe_destination, _safe_output_name


DEFAULT_TARGET = '@VmomoVBot'
DEFAULT_CHOICE = 1
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_WAIT = 5
DEFAULT_MAX_PAGES = 5
DEFAULT_OUTPUT = 'downloads/vmomo'


@dataclass(slots=True)
class SearchOptions:
    query: str
    target: str = DEFAULT_TARGET
    choice: int = DEFAULT_CHOICE
    keyword: str | None = None
    timeout: int = DEFAULT_TIMEOUT
    max_wait: int = DEFAULT_MAX_WAIT
    max_pages: int = DEFAULT_MAX_PAGES
    list_only: bool = False
    output: str = DEFAULT_OUTPUT
    filename: str | None = None


app = typer.Typer(help='Search @VmomoVBot and download media')


@app.callback()
def _callback():
    return None


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--query', required=True)
    parser.add_argument('--target', default=DEFAULT_TARGET)
    parser.add_argument('--choice', type=int, default=DEFAULT_CHOICE)
    parser.add_argument('--keyword')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument('--max-wait', type=int, default=DEFAULT_MAX_WAIT)
    parser.add_argument('--max-pages', type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument('--list-only', action='store_true')
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    parser.add_argument('--filename')
    return parser.parse_args(args)


def _options_from_namespace(options: argparse.Namespace) -> SearchOptions:
    return SearchOptions(
        query=options.query,
        target=options.target,
        choice=options.choice,
        keyword=options.keyword,
        timeout=options.timeout,
        max_wait=options.max_wait,
        max_pages=options.max_pages,
        list_only=options.list_only,
        output=options.output,
        filename=options.filename,
    )


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
            buttons.append({"text": text, "i": row_index, "j": col_index})
    return buttons


def _find_next_button(buttons: list[dict]):
    keywords = ("下一页", "下页", "next", "more", ">", "»", "→", "➡")
    for btn in buttons:
        text = (btn.get("text") or "").strip().lower()
        if any(key in text for key in keywords):
            return btn
    return None


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


def _safe_media_destination(output_dir: pathlib.Path, message, override: str | None) -> pathlib.Path:
    ext = ''
    if message.file and message.file.ext:
        ext = message.file.ext
    elif message.file and message.file.mime_type:
        ext = mimetypes.guess_extension(message.file.mime_type) or ''
    guessed = _guess_filename(message, override)
    safe_name = _safe_output_name(guessed, fallback=f'{message.id}{ext}')
    return _safe_destination(output_dir, safe_name)


async def _call_with_floodwait(coro_factory, logger):
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, "seconds", 0)), 1)
            logger.warning("FloodWaitError: sleeping for %s seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _mark_read(client, target, message, logger):
    await _call_with_floodwait(
        lambda: client.send_read_acknowledge(target, message=message),
        logger,
    )


async def _wait_for_page_update(conv, target_entity, last_message_id: int, timeout: int):
    edit_filter = events.MessageEdited(
        chats=target_entity,
        func=lambda e: e.message.id == last_message_id,
    )
    new_task = asyncio.create_task(conv.get_response(timeout=timeout))
    edit_task = asyncio.create_task(conv.wait_event(edit_filter))
    try:
        done, pending = await asyncio.wait(
            {new_task, edit_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            raise asyncio.TimeoutError()
        for task in pending:
            task.cancel()
        if new_task in done:
            return new_task.result()
        event = edit_task.result()
        return event.message
    finally:
        for task in (new_task, edit_task):
            if not task.done():
                task.cancel()


async def _search_and_download(
    context,
    options: SearchOptions,
):
    logger = context['logger']
    client = context['client']
    target_entity = _normalize_target(options.target)

    output_dir = pathlib.Path(options.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with client.conversation(target_entity, timeout=options.timeout) as conv:
        await _call_with_floodwait(lambda: conv.send_message(options.query), logger)
        response = await _call_with_floodwait(lambda: conv.get_response(timeout=options.timeout), logger)
        await _mark_read(client, target_entity, response, logger)

        page = 1
        remaining_choice = max(options.choice, 1)
        all_candidates = []

        while True:
            buttons = _collect_buttons(response)
            if not buttons:
                raise RuntimeError("No candidates returned from bot")
            for btn in buttons:
                all_candidates.append(btn)
            logger.info("Page %s candidates:", page)
            for index, btn in enumerate(buttons, start=1):
                logger.info("  [%s] %s", index, btn.get("text"))

            if options.list_only:
                next_btn = _find_next_button(buttons)
                if next_btn and page < options.max_pages:
                    await _call_with_floodwait(
                        lambda: response.click(i=next_btn['i'], j=next_btn['j']),
                        logger,
                    )
                    response = await _call_with_floodwait(
                        lambda: _wait_for_page_update(conv, target_entity, response.id, options.timeout),
                        logger,
                    )
                    await _mark_read(client, target_entity, response, logger)
                    page += 1
                    continue
                return {"candidates": [btn.get("text") for btn in all_candidates]}

            selected = None
            if options.keyword:
                for btn in buttons:
                    if options.keyword in (btn.get('text') or ''):
                        selected = btn
                        break
            else:
                if remaining_choice <= len(buttons):
                    selected = buttons[remaining_choice - 1]
                else:
                    remaining_choice -= len(buttons)

            if selected:
                await _call_with_floodwait(
                    lambda: response.click(i=selected['i'], j=selected['j']),
                    logger,
                )
                break

            next_btn = _find_next_button(buttons)
            if not next_btn or page >= options.max_pages:
                raise RuntimeError('No matching candidate found')
            await _call_with_floodwait(
                lambda: response.click(i=next_btn['i'], j=next_btn['j']),
                logger,
            )
            response = await _call_with_floodwait(
                lambda: _wait_for_page_update(conv, target_entity, response.id, options.timeout),
                logger,
            )
            await _mark_read(client, target_entity, response, logger)
            page += 1

        media_message = None
        for _ in range(options.max_wait):
            message = await _call_with_floodwait(lambda: conv.get_response(timeout=options.timeout), logger)
            await _mark_read(client, target_entity, message, logger)
            if message.media or message.file:
                media_message = message
                break
        if not media_message:
            raise RuntimeError("No media message received from bot")

        destination = _safe_media_destination(output_dir, media_message, options.filename)
        await _call_with_floodwait(lambda: media_message.download_media(file=destination), logger)
        logger.info('Downloaded to %s', destination)
        return {'file': str(destination)}


async def _run_with_options(context, options: SearchOptions):
    return await _search_and_download(context, options)


async def run(context, args):
    parsed = _parse_args(args)
    options = _options_from_namespace(parsed)
    return await _run_with_options(context, options)


@app.command()
def search(
    query: str = typer.Option(..., '--query'),
    target: str = typer.Option(DEFAULT_TARGET, '--target'),
    choice: int = typer.Option(DEFAULT_CHOICE, '--choice'),
    keyword: str | None = typer.Option(None, '--keyword'),
    timeout: int = typer.Option(DEFAULT_TIMEOUT, '--timeout'),
    max_wait: int = typer.Option(DEFAULT_MAX_WAIT, '--max-wait'),
    max_pages: int = typer.Option(DEFAULT_MAX_PAGES, '--max-pages'),
    list_only: bool = typer.Option(False, '--list-only'),
    output: str = typer.Option(DEFAULT_OUTPUT, '--output'),
    filename: str | None = typer.Option(None, '--filename'),
):
    ctx = click.get_current_context()
    context = ctx.obj or {}
    call = context.get('call')
    if call is None:
        raise RuntimeError('context.call is required for CLI mode')
    options = SearchOptions(
        query=query,
        target=target,
        choice=choice,
        keyword=keyword,
        timeout=timeout,
        max_wait=max_wait,
        max_pages=max_pages,
        list_only=list_only,
        output=output,
        filename=filename,
    )
    call(_run_with_options(context, options))
