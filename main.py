import asyncio
import logging
import logging.handlers
import pathlib
import sys
from typing import Optional

import typer

from core.action_payloads import (
    RunPayloadOptions,
    build_export_payload,
    build_list_payload,
    build_plugin_payload,
    build_run_payload,
)
from core.action_types import is_supported_action, normalize_action_type
from core.cli_runtime import LocalRunContext, run_action_with_optional_daemon, try_daemon_request
from core.client_manager import ClientManager, safe_disconnect
from core.config import ConfigError, load_config, resolve_profile
from core.daemon_runtime import run_daemon
from core.executor import ActionError
from core.ipc import cleanup_stale_socket
from core.plugins import (
    PluginError,
    get_plugin_cli_help,
    is_plugin_enabled,
    list_plugin_states,
    list_plugins,
    set_plugin_enabled,
)

app = typer.Typer(help='Telegram userbot CLI (Telethon + APScheduler)')


def _setup_logger(
    name: str = 'tg-dog',
    log_file: Optional[str] = None,
    stream_only: bool = False,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    if log_file and not stream_only:
        path = pathlib.Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8',
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def _redirect_std_streams(log_file: str) -> None:
    path = pathlib.Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, 'a', encoding='utf-8', buffering=1)
    sys.stdout = stream
    sys.stderr = stream


def _daemon_socket(config: dict) -> str:
    return str(config.get('daemon_socket', 'logs/daemon.sock'))


def _daemon_token(config: dict) -> Optional[str]:
    token = config.get('daemon_token')
    if token is None:
        return None
    value = str(token).strip()
    return value or None


def _print_dialog_item(item: dict) -> None:
    name = item.get('name') or ''
    username = item.get('username') or ''
    if username:
        username = f'@{username}'
    kind = item.get('kind') or ''
    target = item.get('target') or ''
    dialog_id = item.get('id')
    typer.echo(f'[{kind}] {name} {username} id={dialog_id} target={target}')


def _print_message_item(item: dict) -> None:
    typer.echo(f"[{item['date']}] {item['id']} {item['sender_id']}: {item['snippet']}")


async def _with_client(profile_key: str, profile: dict, session_dir: str, interactive: bool, logger):
    manager = ClientManager(
        api_id=int(profile['api_id']),
        api_hash=profile['api_hash'],
        phone_number=profile['phone_number'],
        session_dir=session_dir,
        proxy_url=profile.get('proxy'),
    )
    await manager.connect(profile_key)
    try:
        authorized = await manager.ensure_authorized(interactive=interactive)
        if not authorized:
            raise RuntimeError(f"Profile '{profile_key}' is not authorized; run auth first")
        return manager
    except Exception:
        await safe_disconnect(manager)
        raise


def _resolve_profile_or_exit(config_path: str, profile: Optional[str]) -> tuple[dict, str, dict]:
    try:
        cfg = load_config(config_path)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    return cfg, profile_key, profile_data


def _build_local_context(
    cfg: dict,
    profile_key: str,
    profile_data: dict,
    session_dir: str,
    logger,
) -> LocalRunContext:
    return LocalRunContext(
        profile_key=profile_key,
        profile_data=profile_data,
        session_dir=session_dir,
        cfg=cfg,
        logger=logger,
        with_client=_with_client,
    )


def _run_action_command(
    *,
    action_type: str,
    target: Optional[str],
    payload: dict,
    profile: Optional[str],
    config_path: str,
    session_dir: str,
    no_daemon: bool,
    logger,
    error_label: str,
):
    cfg, profile_key, profile_data = _resolve_profile_or_exit(config_path, profile)
    local_ctx = _build_local_context(cfg, profile_key, profile_data, session_dir, logger)
    daemon_token = _daemon_token(cfg)

    try:
        return run_action_with_optional_daemon(
            action_type=action_type,
            target=target,
            payload=payload,
            profile_name=profile,
            socket_path=_daemon_socket(cfg),
            daemon_token=daemon_token,
            no_daemon=no_daemon,
            logger=logger,
            local_ctx=local_ctx,
        )
    except (ActionError, PluginError) as exc:
        logger.error('%s failed: %s', error_label, exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception('%s failed: %s', error_label, exc)
        raise typer.Exit(code=1)


@app.command()
def auth(
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
):
    """Authenticate and create a session file."""
    logger = _setup_logger()
    _, profile_key, profile_data = _resolve_profile_or_exit(config, profile)

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, True, logger)
        await safe_disconnect(manager)

    try:
        asyncio.run(_run())
        typer.echo(f"Profile '{profile_key}' authenticated")
    except Exception as exc:
        logger.exception('Authentication failed: %s', exc)
        raise typer.Exit(code=1)


@app.command()
def send(
    target: str = typer.Option(..., '--target', help='Target username/channel'),
    text: str = typer.Option(..., '--text', help='Message text'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """Send a message."""
    logger = _setup_logger()
    _run_action_command(
        action_type='send',
        target=target,
        payload={'text': text},
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='Send',
    )


@app.command()
def run(
    action: str = typer.Option(..., '--action', help='send | interactive_send | download | export'),
    target: str = typer.Option(..., '--target', help='Target username/channel'),
    text: Optional[str] = typer.Option(None, '--text', help='Message text'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    limit: int = typer.Option(5, '--limit', help='Limit for download/list'),
    media_type: str = typer.Option('any', '--media-type', help='photo | video | document | audio | any'),
    min_size: Optional[int] = typer.Option(None, '--min-size', help='Min file size in bytes'),
    max_size: Optional[int] = typer.Option(None, '--max-size', help='Max file size in bytes'),
    output_dir: str = typer.Option('downloads', '--output-dir', help='Download output dir'),
    timeout: int = typer.Option(30, '--timeout', help='Conversation timeout seconds'),
    mark_read: bool = typer.Option(False, '--mark-read', help='Mark messages as read'),
    export_output: str = typer.Option('exports', '--export-output', help='Export output path'),
    export_mode: str = typer.Option('single', '--export-mode', help='single | per_message'),
    attachments_dir: Optional[str] = typer.Option(None, '--attachments-dir', help='Attachments dir'),
    from_user: Optional[str] = typer.Option(None, '--from-user', help='Filter by sender id/username'),
    message_id: Optional[list[int]] = typer.Option(None, '--message-id', help='Message ID(s) to export'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """Run a single action immediately."""
    logger = _setup_logger()
    action_type = normalize_action_type(action)
    allowed_actions = {'send', 'interactive_send', 'download', 'export'}
    if not is_supported_action(action_type) or action_type not in allowed_actions:
        typer.echo(
            "Unsupported --action. Use one of: send, interactive_send, download, export",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        payload = build_run_payload(
            action_type,
            RunPayloadOptions(
                text=text,
                limit=limit,
                media_type=media_type,
                min_size=min_size,
                max_size=max_size,
                output_dir=output_dir,
                timeout=timeout,
                mark_read=mark_read,
                export_output=export_output,
                export_mode=export_mode,
                attachments_dir=attachments_dir,
                from_user=from_user,
                message_ids=message_id,
            ),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    result = _run_action_command(
        action_type=action_type,
        target=target,
        payload=payload,
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='Run',
    )
    if action_type == 'interactive_send':
        typer.echo((result or {}).get('response_text') or '')


@app.command(name='list-msgs')
def list_msgs(
    target: str = typer.Option(..., '--target', help='Target username/channel'),
    limit: int = typer.Option(10, '--limit', help='Number of messages'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    mark_read: bool = typer.Option(False, '--mark-read', help='Mark messages as read'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """List recent messages."""
    logger = _setup_logger()
    result = _run_action_command(
        action_type='list',
        target=target,
        payload=build_list_payload(limit, mark_read),
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='List',
    )
    for item in (result or {}).get('messages') or []:
        _print_message_item(item)


@app.command(name='list')
def list_alias(
    target: str = typer.Option(..., '--target', help='Target username/channel'),
    limit: int = typer.Option(10, '--limit', help='Number of messages'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    mark_read: bool = typer.Option(False, '--mark-read', help='Mark messages as read'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """Alias for list-msgs."""
    list_msgs(
        target=target,
        limit=limit,
        profile=profile,
        config=config,
        session_dir=session_dir,
        mark_read=mark_read,
        no_daemon=no_daemon,
    )


@app.command()
def export(
    target: str = typer.Option(..., '--target', help='Target username/channel'),
    output: str = typer.Option('exports', '--output', help='Export output path'),
    mode: str = typer.Option('single', '--mode', help='single | per_message'),
    attachments_dir: Optional[str] = typer.Option(None, '--attachments-dir', help='Attachments dir'),
    limit: int = typer.Option(0, '--limit', help='Limit number of messages (0 = all)'),
    from_user: Optional[str] = typer.Option(None, '--from-user', help='Filter by sender id/username'),
    message_id: Optional[list[int]] = typer.Option(None, '--message-id', help='Message ID(s) to export'),
    mark_read: bool = typer.Option(False, '--mark-read', help='Mark messages as read'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """Export messages to markdown."""
    logger = _setup_logger()
    result = _run_action_command(
        action_type='export',
        target=target,
        payload=build_export_payload(
            output=output,
            mode=mode,
            attachments_dir=attachments_dir,
            limit=None if limit == 0 else limit,
            from_user=from_user,
            message_ids=message_id,
            mark_read=mark_read,
        ),
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='Export',
    )
    typer.echo(f"Exported {result.get('exported', 0)} messages to {result.get('output')}")


@app.command()
def daemon(
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    log_file: str = typer.Option('logs/daemon.log', '--log-file', help='Daemon log file'),
    socket_path: Optional[str] = typer.Option(None, '--socket', help='Daemon IPC socket path'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
):
    """Run scheduled tasks as a daemon."""
    _redirect_std_streams(log_file)
    logger = _setup_logger(log_file=log_file, stream_only=True)
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error('Config error: %s', exc)
        raise typer.Exit(code=1)

    socket_path = socket_path or _daemon_socket(cfg)
    cleanup_stale_socket(socket_path, logger)
    existing_request = {'action': 'ping'}
    daemon_token = _daemon_token(cfg)
    if daemon_token:
        existing_request['token'] = daemon_token
    existing = try_daemon_request(socket_path, existing_request, logger)
    if existing and existing.get('ok'):
        logger.error('Daemon already running at %s', socket_path)
        raise typer.Exit(code=1)

    try:
        asyncio.run(run_daemon(cfg, logger, socket_path, session_dir=session_dir))
    except Exception as exc:
        logger.exception('Daemon failed: %s', exc)
        raise typer.Exit(code=1)


@app.command(name='plugin', context_settings={'allow_extra_args': True, 'ignore_unknown_options': True})
def plugin_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help='Plugin name under plugins/'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """Run a plugin with raw arguments."""
    logger = _setup_logger()
    if name in {'enable', 'disable', 'status', 'list'}:
        if name == 'list':
            for item in list_plugins():
                status = 'enabled' if is_plugin_enabled(item) else 'disabled'
                typer.echo(f'{item}\t{status}')
            return
        if name == 'status':
            states = list_plugin_states()
            for item in list_plugins():
                status = 'enabled' if states.get(item, True) else 'disabled'
                typer.echo(f'{item}\t{status}')
            return
        if not ctx.args:
            typer.echo('Plugin name required', err=True)
            raise typer.Exit(code=1)
        target_name = ctx.args[0]
        enabled = name == 'enable'
        set_plugin_enabled(target_name, enabled)
        typer.echo(f"{target_name}\t{'enabled' if enabled else 'disabled'}")
        return

    args = list(ctx.args) if ctx else []
    _run_action_command(
        action_type='plugin_cli',
        target=None,
        payload=build_plugin_payload(name, args, mode='cli'),
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='Plugin',
    )


@app.command(name='list-plugins')
def list_plugins_cmd():
    """List available plugins."""
    for name in list_plugins():
        typer.echo(name)


@app.command(name='plugin-help')
def plugin_help_cmd(
    name: str = typer.Argument(..., help='Plugin name under plugins/'),
):
    """Show plugin subcommand help without running it."""
    try:
        help_text = get_plugin_cli_help(name)
        typer.echo(help_text)
    except PluginError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)


@app.command(name='list-dialogs')
def list_dialogs_cmd(
    limit: int = typer.Option(30, '--limit', help='Number of dialogs'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Profile name in config'),
    config: str = typer.Option('config.yaml', '--config', help='Path to config.yaml'),
    session_dir: str = typer.Option('sessions', '--session-dir', help='Session storage dir'),
    no_daemon: bool = typer.Option(False, '--no-daemon', help='Do not use daemon if running'),
):
    """List dialogs with target hints."""
    logger = _setup_logger()
    result = _run_action_command(
        action_type='list_dialogs',
        target=None,
        payload={'limit': limit},
        profile=profile,
        config_path=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
        logger=logger,
        error_label='List dialogs',
    )
    for item in (result or {}).get('dialogs') or []:
        _print_dialog_item(item)


if __name__ == '__main__':
    app()
