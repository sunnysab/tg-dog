import argparse
import asyncio
import json
import pathlib
import random
from datetime import datetime, time, timedelta

import click
import typer
from telethon.errors import FloodWaitError

app = typer.Typer(help="随机时间每日发送消息")


def _parse_window(value: str) -> tuple[time, time]:
    if "-" not in value:
        raise ValueError("window must be like HH:MM-HH:MM")
    start_str, end_str = value.split("-", 1)
    start = datetime.strptime(start_str, "%H:%M").time()
    end = datetime.strptime(end_str, "%H:%M").time()
    if end <= start:
        raise ValueError("window end must be later than start")
    return start, end


def _load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _pick_planned_time(now: datetime, start_t: time, end_t: time, earliest_ts: float) -> tuple[float, str]:
    day = now.date()
    tz = now.tzinfo
    while True:
        start_dt = datetime.combine(day, start_t, tzinfo=tz)
        end_dt = datetime.combine(day, end_t, tzinfo=tz)
        end_ts = end_dt.timestamp()
        if earliest_ts <= end_ts:
            start_ts = max(earliest_ts, start_dt.timestamp())
            planned_ts = random.uniform(start_ts, end_ts)
            return planned_ts, day.isoformat()
        day = day + timedelta(days=1)


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--window", default="09:00-23:00")
    parser.add_argument("--min-interval-hours", type=int, default=24)
    parser.add_argument("--expect-text")
    parser.add_argument("--expect-keyword")
    parser.add_argument("--expect-timeout", type=int, default=10)
    parser.add_argument("--state", default="data/random_daily_sender.json")
    return parser.parse_args(args)


def _normalize_target(target: str):
    value = target.strip()
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    return value


async def _run(context, target: str, text: str, window: str, min_interval_hours: int, state_path: str):
    logger = context["logger"]
    client = context["client"]
    expect_text = context.get("expect_text")
    expect_keyword = context.get("expect_keyword")
    expect_timeout = context.get("expect_timeout", 10)

    now = datetime.now().astimezone()
    today_str = now.date().isoformat()
    start_t, end_t = _parse_window(window)

    state_file = pathlib.Path(state_path)
    state = _load_state(state_file)
    last_sent_ts = state.get("last_sent_ts")
    last_sent_date = state.get("last_sent_date")
    planned_ts = state.get("planned_ts")
    planned_date = state.get("planned_date")

    if last_sent_date == today_str:
        logger.info("Already sent today for %s", target)
        return {"status": "already_sent"}

    min_interval = max(min_interval_hours, 0) * 3600
    earliest_ts = (last_sent_ts + min_interval) if last_sent_ts else now.timestamp()

    if planned_ts and planned_date:
        try:
            planned_day = datetime.fromisoformat(planned_date).date()
        except ValueError:
            planned_day = None
        if planned_day and planned_day > now.date():
            logger.info("Next send planned at %s", datetime.fromtimestamp(planned_ts, tz=now.tzinfo))
            return {"status": "planned", "planned": planned_ts}
        if planned_day == now.date() and now.timestamp() < planned_ts:
            logger.info("Planned send at %s", datetime.fromtimestamp(planned_ts, tz=now.tzinfo))
            return {"status": "scheduled", "planned": planned_ts}

    if not planned_ts or planned_date != today_str:
        planned_ts, planned_date = _pick_planned_time(now, start_t, end_t, earliest_ts)
        state["planned_ts"] = planned_ts
        state["planned_date"] = planned_date
        _save_state(state_file, state)
        if planned_date != today_str:
            logger.info("Next send planned at %s", datetime.fromtimestamp(planned_ts, tz=now.tzinfo))
            return {"status": "planned", "planned": planned_ts}

    send_target = _normalize_target(target)
    if expect_text or expect_keyword:
        result = await _send_and_expect(
            client,
            send_target,
            text,
            expect_text=expect_text,
            expect_keyword=expect_keyword,
            timeout=expect_timeout,
            logger=logger,
        )
        state["last_expect_result"] = result.get("status")
        state["last_reply_text"] = result.get("reply_text")
        state["last_reply_ts"] = result.get("reply_ts")
    else:
        await _send_with_floodwait(lambda: client.send_message(send_target, text), logger)
    state["last_sent_ts"] = now.timestamp()
    state["last_sent_date"] = today_str
    state["planned_ts"] = None
    state["planned_date"] = None
    _save_state(state_file, state)
    logger.info("Sent daily message to %s", target)
    return {"status": "sent", "expect": state.get("last_expect_result")}


async def _send_with_floodwait(coro_factory, logger):
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, "seconds", 0)), 1)
            logger.warning("FloodWaitError: sleeping for %s seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _get_response_with_floodwait(conv, timeout: int, logger):
    while True:
        try:
            return await conv.get_response(timeout=timeout)
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, "seconds", 0)), 1)
            logger.warning("FloodWaitError: sleeping for %s seconds", wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _send_and_expect(client, target, text, expect_text, expect_keyword, timeout, logger):
    status = "unknown"
    reply_text = None
    reply_ts = None
    try:
        async with client.conversation(target, timeout=timeout) as conv:
            await _send_with_floodwait(lambda: conv.send_message(text), logger)
            response = await _get_response_with_floodwait(conv, timeout, logger)
            reply_text = (response.text or "").strip()
            reply_ts = response.date.isoformat() if response.date else None
            matched = True
            if expect_text is not None:
                matched = matched and reply_text == expect_text
            if expect_keyword is not None:
                matched = matched and (expect_keyword in reply_text)
            status = "success" if matched else "failed"
    except asyncio.TimeoutError:
        status = "timeout"
    return {"status": status, "reply_text": reply_text, "reply_ts": reply_ts}


async def run(context, args):
    options = _parse_args(args)
    context = dict(context)
    context["expect_text"] = options.expect_text
    context["expect_keyword"] = options.expect_keyword
    context["expect_timeout"] = options.expect_timeout
    return await _run(
        context,
        target=options.target,
        text=options.text,
        window=options.window,
        min_interval_hours=options.min_interval_hours,
        state_path=options.state,
    )


@app.command()
def execute(
    target: str = typer.Option(..., "--target"),
    text: str = typer.Option(..., "--text"),
    window: str = typer.Option("09:00-23:00", "--window"),
    min_interval_hours: int = typer.Option(24, "--min-interval-hours"),
    expect_text: str = typer.Option(None, "--expect-text"),
    expect_keyword: str = typer.Option(None, "--expect-keyword"),
    expect_timeout: int = typer.Option(10, "--expect-timeout"),
    state: str = typer.Option("data/random_daily_sender.json", "--state"),
):
    ctx = click.get_current_context()
    context = ctx.obj or {}
    call = context.get("call")
    if call is None:
        raise RuntimeError("context.call is required for CLI mode")
    context = dict(context)
    context["expect_text"] = expect_text
    context["expect_keyword"] = expect_keyword
    context["expect_timeout"] = expect_timeout
    call(
        _run(
            context,
            target=target,
            text=text,
            window=window,
            min_interval_hours=min_interval_hours,
            state_path=state,
        )
    )
