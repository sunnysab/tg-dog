import argparse
import asyncio
from dataclasses import dataclass
import hashlib
import json
import pathlib
import random
from contextlib import contextmanager
from datetime import datetime, time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None

import click
import typer
import yaml
from telethon.errors import FloodWaitError

app = typer.Typer(help='Randomized daily sender with planning')

MAX_INLINE_WAIT_SECONDS = 300
MAX_RETRIES_PER_DAY = 3
RETRY_MIN_DELAY_SECONDS = 120

DEFAULT_WINDOW = '09:00-23:00'
DEFAULT_MIN_INTERVAL_HOURS = 24
DEFAULT_EXPECT_TIMEOUT = 10
DEFAULT_STATE_PATH = 'data/state.yaml'


@dataclass(slots=True)
class SenderOptions:
    target: str
    text: str
    window: str = DEFAULT_WINDOW
    min_interval_hours: int = DEFAULT_MIN_INTERVAL_HOURS
    expect_text: str | None = None
    expect_keyword: str | None = None
    expect_timeout: int = DEFAULT_EXPECT_TIMEOUT
    state: str = DEFAULT_STATE_PATH


def _parse_window(value: str) -> tuple[time, time]:
    if '-' not in value:
        raise ValueError('window must be like HH:MM-HH:MM')
    start_str, end_str = value.split('-', 1)
    start = datetime.strptime(start_str, '%H:%M').time()
    end = datetime.strptime(end_str, '%H:%M').time()
    if end <= start:
        raise ValueError('window end must be later than start')
    return start, end


def _window_bounds(day, window: str, tzinfo) -> tuple[float, float]:
    start_t, end_t = _parse_window(window)
    start_dt = datetime.combine(day, start_t, tzinfo=tzinfo)
    end_dt = datetime.combine(day, end_t, tzinfo=tzinfo)
    return start_dt.timestamp(), end_dt.timestamp()


def _is_yaml(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {'.yml', '.yaml'}


def _load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as file:
        if _is_yaml(path):
            data = yaml.safe_load(file)
            return data if isinstance(data, dict) else {}
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def _save_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as file:
        if _is_yaml(path):
            yaml.safe_dump(state, file, allow_unicode=True, default_flow_style=False, sort_keys=True)
            return
        json.dump(state, file, ensure_ascii=False, indent=2)


@contextmanager
def _state_lock(path: pathlib.Path, logger):
    lock_path = path.with_suffix(path.suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open('a+', encoding='utf-8')
    locked = False
    try:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                logger.info('State file locked, skip this run')
                yield None
                return
        elif msvcrt is not None:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                logger.info('State file locked, skip this run')
                yield None
                return
        yield lock_file
    finally:
        if locked:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                lock_file.close()
        else:
            lock_file.close()


def _parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--target', required=True)
    parser.add_argument('--text', required=True)
    parser.add_argument('--window', default=DEFAULT_WINDOW)
    parser.add_argument('--min-interval-hours', type=int, default=DEFAULT_MIN_INTERVAL_HOURS)
    parser.add_argument('--expect-text')
    parser.add_argument('--expect-keyword')
    parser.add_argument('--expect-timeout', type=int, default=DEFAULT_EXPECT_TIMEOUT)
    parser.add_argument('--state', default=DEFAULT_STATE_PATH)
    return parser.parse_args(args)


def _options_from_namespace(options: argparse.Namespace) -> SenderOptions:
    return SenderOptions(
        target=options.target,
        text=options.text,
        window=options.window,
        min_interval_hours=options.min_interval_hours,
        expect_text=options.expect_text,
        expect_keyword=options.expect_keyword,
        expect_timeout=options.expect_timeout,
        state=options.state,
    )


def _normalize_target(target: str):
    value = target.strip()
    if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
        return int(value)
    return value


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_account_spec(
    context: dict,
    target: str,
    text: str,
    window: str,
    min_interval_hours: int,
) -> dict:
    return {
        'profile_name': context.get('profile_name'),
        'target': target,
        'text': text,
        'window': window,
        'min_interval_hours': max(_as_int(min_interval_hours), 0),
        'expect_text': context.get('expect_text'),
        'expect_keyword': context.get('expect_keyword'),
        'expect_timeout': max(_as_int(context.get('expect_timeout'), 10), 1),
    }


def _account_key(spec: dict) -> str:
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def _normalize_state(state: dict) -> dict:
    normalized = state if isinstance(state, dict) else {}
    normalized['version'] = 2
    accounts = normalized.get('accounts')
    history = normalized.get('history')
    daily_plan = normalized.get('daily_plan')
    normalized['accounts'] = accounts if isinstance(accounts, dict) else {}
    normalized['history'] = history if isinstance(history, dict) else {}
    if not isinstance(daily_plan, dict):
        daily_plan = {}
    items = daily_plan.get('items')
    daily_plan['date'] = daily_plan.get('date')
    daily_plan['items'] = items if isinstance(items, dict) else {}
    normalized['daily_plan'] = daily_plan
    return normalized


def _plan_item(now: datetime, account_spec: dict, history_entry: dict) -> dict:
    start_ts, end_ts = _window_bounds(now.date(), account_spec['window'], now.tzinfo)
    min_interval_seconds = max(_as_int(account_spec.get('min_interval_hours')), 0) * 3600
    earliest_ts = start_ts
    last_success_ts = _as_float(history_entry.get('last_success_ts'))
    if last_success_ts is not None:
        earliest_ts = max(earliest_ts, last_success_ts + min_interval_seconds)

    if earliest_ts > end_ts:
        return {
            'planned_ts': None,
            'status': 'deferred',
            'attempts': 0,
            'reason': 'window_exhausted',
            'inflight_until': None,
            'last_error': None,
        }

    return {
        'planned_ts': random.uniform(earliest_ts, end_ts),
        'status': 'planned',
        'attempts': 0,
        'reason': None,
        'inflight_until': None,
        'last_error': None,
    }


def _rebuild_daily_plan(state: dict, now: datetime) -> dict:
    items = {}
    for account_id, account_spec in state['accounts'].items():
        history_entry = state['history'].get(account_id) or {}
        items[account_id] = _plan_item(now, account_spec, history_entry)
    state['daily_plan'] = {
        'date': now.date().isoformat(),
        'items': items,
    }
    return state['daily_plan']


def _ensure_today_plan(state: dict, now: datetime) -> dict:
    daily_plan = state['daily_plan']
    today = now.date().isoformat()
    if daily_plan.get('date') != today:
        return _rebuild_daily_plan(state, now)
    return daily_plan


def _ensure_today_item(state: dict, account_id: str, account_spec: dict, now: datetime) -> dict:
    daily_plan = _ensure_today_plan(state, now)
    items = daily_plan['items']
    item = items.get(account_id)
    if isinstance(item, dict):
        return item
    history_entry = state['history'].get(account_id) or {}
    item = _plan_item(now, account_spec, history_entry)
    items[account_id] = item
    return item


def _schedule_retry(now: datetime, account_spec: dict, item: dict) -> dict:
    end_ts = _window_bounds(now.date(), account_spec['window'], now.tzinfo)[1]
    attempts = _as_int(item.get('attempts'))
    retry_from = now.timestamp() + RETRY_MIN_DELAY_SECONDS
    if attempts < MAX_RETRIES_PER_DAY and retry_from < end_ts:
        item['planned_ts'] = random.uniform(retry_from, end_ts)
        item['status'] = 'planned'
        return item
    item['planned_ts'] = None
    item['status'] = 'failed_today'
    return item


async def _send_with_floodwait(coro_factory, logger):
    while True:
        try:
            return await coro_factory()
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, 'seconds', 0)), 1)
            logger.warning('FloodWaitError: sleeping for %s seconds', wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _mark_read(client, target, message, logger):
    await _send_with_floodwait(
        lambda: client.send_read_acknowledge(target, message=message),
        logger,
    )


async def _get_response_with_floodwait(conv, timeout: int, logger):
    while True:
        try:
            return await conv.get_response(timeout=timeout)
        except FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, 'seconds', 0)), 1)
            logger.warning('FloodWaitError: sleeping for %s seconds', wait_seconds)
            await asyncio.sleep(wait_seconds)


async def _send_and_expect(client, target, text, expect_text, expect_keyword, timeout, logger):
    status = 'unknown'
    reply_text = None
    reply_ts = None
    try:
        async with client.conversation(target, timeout=timeout) as conv:
            await _send_with_floodwait(lambda: conv.send_message(text), logger)
            response = await _get_response_with_floodwait(conv, timeout, logger)
            await _mark_read(client, target, response, logger)
            reply_text = (response.text or '').strip()
            reply_ts = response.date.isoformat() if response.date else None
            matched = True
            if expect_text is not None:
                matched = matched and reply_text == expect_text
            if expect_keyword is not None:
                matched = matched and (expect_keyword in reply_text)
            status = 'success' if matched else 'failed'
    except asyncio.TimeoutError:
        status = 'timeout'
    return {'status': status, 'reply_text': reply_text, 'reply_ts': reply_ts}


async def _execute_send(client, account_spec: dict, logger) -> dict:
    send_target = _normalize_target(account_spec['target'])
    expect_text = account_spec.get('expect_text')
    expect_keyword = account_spec.get('expect_keyword')
    expect_timeout = _as_int(account_spec.get('expect_timeout'), 10)

    if expect_text or expect_keyword:
        result = await _send_and_expect(
            client,
            send_target,
            account_spec['text'],
            expect_text=expect_text,
            expect_keyword=expect_keyword,
            timeout=expect_timeout,
            logger=logger,
        )
        status = result.get('status')
        return {
            'ok': status == 'success',
            'status': status,
            'reply_text': result.get('reply_text'),
            'reply_ts': result.get('reply_ts'),
            'error': None,
        }

    await _send_with_floodwait(lambda: client.send_message(send_target, account_spec['text']), logger)
    return {
        'ok': True,
        'status': 'success',
        'reply_text': None,
        'reply_ts': None,
        'error': None,
    }


async def _run(context, target: str, text: str, window: str, min_interval_hours: int, state_path: str):
    logger = context['logger']
    client = context['client']

    account_spec = _build_account_spec(context, target, text, window, min_interval_hours)
    account_id = _account_key(account_spec)
    state_file = pathlib.Path(state_path)

    now = datetime.now().astimezone()
    today = now.date().isoformat()
    wait_seconds = 0.0
    planned_ts = None

    with _state_lock(state_file, logger) as lock:
        if lock is None:
            return {'status': 'locked'}

        state = _normalize_state(_load_state(state_file))
        state['accounts'][account_id] = account_spec
        history_entry = state['history'].setdefault(account_id, {})
        item = _ensure_today_item(state, account_id, account_spec, now)

        if history_entry.get('last_success_date') == today:
            item['status'] = 'done'
            item['inflight_until'] = None
            _save_state(state_file, state)
            return {'status': 'already_sent'}

        status = item.get('status')
        planned_ts = _as_float(item.get('planned_ts'))

        if status in {'deferred', 'failed_today', 'done'} or planned_ts is None:
            _save_state(state_file, state)
            return {'status': status, 'planned': planned_ts}

        now_ts = now.timestamp()
        inflight_until = _as_float(item.get('inflight_until'))
        if inflight_until is not None and inflight_until > now_ts:
            return {'status': 'inflight', 'planned': planned_ts}

        if planned_ts > now_ts + MAX_INLINE_WAIT_SECONDS:
            return {'status': 'scheduled', 'planned': planned_ts}

        wait_seconds = max(planned_ts - now_ts, 0.0)
        item['inflight_until'] = now_ts + MAX_INLINE_WAIT_SECONDS + 120
        _save_state(state_file, state)

    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)

    try:
        send_result = await _execute_send(client, account_spec, logger)
    except Exception as exc:
        logger.exception('Daily sender execution failed: %s', exc)
        send_result = {
            'ok': False,
            'status': 'error',
            'reply_text': None,
            'reply_ts': None,
            'error': str(exc),
        }

    now = datetime.now().astimezone()
    with _state_lock(state_file, logger) as lock:
        if lock is None:
            return {'status': 'locked_after_send', 'result': send_result.get('status')}

        state = _normalize_state(_load_state(state_file))
        daily_plan = _ensure_today_plan(state, now)
        if daily_plan.get('date') != now.date().isoformat():
            return {'status': 'plan_rotated'}

        history_entry = state['history'].setdefault(account_id, {})
        item = daily_plan['items'].setdefault(account_id, _plan_item(now, account_spec, history_entry))

        item['inflight_until'] = None
        item['attempts'] = _as_int(item.get('attempts')) + 1

        history_entry['last_attempt_ts'] = now.timestamp()
        history_entry['last_result'] = send_result.get('status')

        if send_result.get('reply_text') is not None:
            history_entry['last_reply_text'] = send_result.get('reply_text')
        if send_result.get('reply_ts') is not None:
            history_entry['last_reply_ts'] = send_result.get('reply_ts')

        if send_result.get('ok'):
            history_entry['last_success_ts'] = now.timestamp()
            history_entry['last_success_date'] = now.date().isoformat()
            item['status'] = 'done'
            item['last_error'] = None
            _save_state(state_file, state)
            logger.info('Sent daily message to %s', target)
            return {
                'status': 'sent',
                'planned': planned_ts,
                'attempts': item['attempts'],
            }

        item['last_error'] = send_result.get('error') or send_result.get('status')
        item = _schedule_retry(now, account_spec, item)
        _save_state(state_file, state)

        logger.warning('Send check failed for %s, status=%s', target, send_result.get('status'))
        return {
            'status': item.get('status'),
            'planned': item.get('planned_ts'),
            'attempts': item.get('attempts'),
            'error': item.get('last_error'),
        }


async def _run_with_options(context: dict, options: SenderOptions):
    normalized_context = dict(context)
    normalized_context['expect_text'] = options.expect_text
    normalized_context['expect_keyword'] = options.expect_keyword
    normalized_context['expect_timeout'] = options.expect_timeout
    return await _run(
        normalized_context,
        target=options.target,
        text=options.text,
        window=options.window,
        min_interval_hours=options.min_interval_hours,
        state_path=options.state,
    )


async def run(context, args):
    parsed = _parse_args(args)
    options = _options_from_namespace(parsed)
    return await _run_with_options(context, options)


@app.command()
def execute(
    target: str = typer.Option(..., '--target'),
    text: str = typer.Option(..., '--text'),
    window: str = typer.Option(DEFAULT_WINDOW, '--window'),
    min_interval_hours: int = typer.Option(DEFAULT_MIN_INTERVAL_HOURS, '--min-interval-hours'),
    expect_text: str = typer.Option(None, '--expect-text'),
    expect_keyword: str = typer.Option(None, '--expect-keyword'),
    expect_timeout: int = typer.Option(DEFAULT_EXPECT_TIMEOUT, '--expect-timeout'),
    state: str = typer.Option(DEFAULT_STATE_PATH, '--state'),
):
    ctx = click.get_current_context()
    context = ctx.obj or {}
    call = context.get('call')
    if call is None:
        raise RuntimeError('context.call is required for CLI mode')
    options = SenderOptions(
        target=target,
        text=text,
        window=window,
        min_interval_hours=min_interval_hours,
        expect_text=expect_text,
        expect_keyword=expect_keyword,
        expect_timeout=expect_timeout,
        state=state,
    )
    call(_run_with_options(context, options))
