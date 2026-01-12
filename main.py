import asyncio
import logging
import pathlib
import sys
from typing import Optional

import typer

from core.client_manager import ClientManager, safe_disconnect
from core.config import ConfigError, load_config, resolve_profile
from core.daemon_runtime import run_daemon
from core.executor import ActionError, execute_action
from core.ipc import IpcError, send_request
from core.plugins import PluginError, list_plugins, run_plugin_cli

app = typer.Typer(help="Telegram userbot CLI (Telethon + APScheduler)")


def _setup_logger(name: str = "tg-dog", log_file: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    if log_file:
        path = pathlib.Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def _redirect_std_streams(log_file: str) -> None:
    path = pathlib.Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream


def _daemon_socket(config: dict) -> str:
    return str(config.get("daemon_socket", "logs/daemon.sock"))


def _try_daemon_request(socket_path: str, request: dict, logger):
    async def _send():
        return await send_request(socket_path, request)

    try:
        return asyncio.run(_send())
    except (FileNotFoundError, ConnectionError, IpcError, OSError):
        return None
    except Exception as exc:
        logger.error("Daemon request failed: %s", exc)
        return None


async def _with_client(profile_key: str, profile: dict, session_dir: str, interactive: bool, logger):
    manager = ClientManager(
        api_id=int(profile["api_id"]),
        api_hash=profile["api_hash"],
        phone_number=profile["phone_number"],
        session_dir=session_dir,
        proxy_url=profile.get("proxy"),
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


@app.command()
def auth(
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
):
    """Authenticate and create a session file."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, True, logger)
        await safe_disconnect(manager)

    try:
        asyncio.run(_run())
        typer.echo(f"Profile '{profile_key}' authenticated")
    except Exception as exc:
        logger.exception("Authentication failed: %s", exc)
        raise typer.Exit(code=1)


@app.command()
def run(
    action: str = typer.Option(..., "--action", help="send | interactive_send | download"),
    target: str = typer.Option(..., "--target", help="Target username/channel"),
    text: Optional[str] = typer.Option(None, "--text", help="Message text"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
    limit: int = typer.Option(5, "--limit", help="Limit for download/list"),
    media_type: str = typer.Option("any", "--media-type", help="photo | video | document | audio | any"),
    min_size: Optional[int] = typer.Option(None, "--min-size", help="Min file size in bytes"),
    max_size: Optional[int] = typer.Option(None, "--max-size", help="Max file size in bytes"),
    output_dir: str = typer.Option("downloads", "--output-dir", help="Download output dir"),
    timeout: int = typer.Option(30, "--timeout", help="Conversation timeout seconds"),
    no_daemon: bool = typer.Option(False, "--no-daemon", help="Do not use daemon if running"),
):
    """Run a single action immediately."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    action_lower = action.lower()
    if action_lower == "send_msg":
        action_lower = "send"

    payload = {}
    if action_lower in {"send", "interactive_send"}:
        if not text:
            typer.echo("--text is required for send/interactive_send", err=True)
            raise typer.Exit(code=1)
        payload["text"] = text
        if action_lower == "interactive_send":
            payload["timeout"] = timeout
    elif action_lower == "download":
        payload.update(
            {
                "limit": limit,
                "media_type": media_type,
                "min_size": min_size,
                "max_size": max_size,
                "output_dir": output_dir,
            }
        )

    if not no_daemon:
        response = _try_daemon_request(
            _daemon_socket(cfg),
            {
                "action": action_lower,
                "profile": profile,
                "target": target,
                "payload": payload,
            },
            logger,
        )
        if response is not None:
            if not response.get("ok"):
                typer.echo(response.get("error", "Daemon request failed"), err=True)
                raise typer.Exit(code=1)
            result = response.get("result") or {}
            if action_lower == "interactive_send":
                typer.echo(result.get("response_text") or "")
            return

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            result = await execute_action(
                action_lower,
                manager.client,
                target,
                payload,
                cfg,
                profile_key,
                profile_data,
                logger,
                loop=asyncio.get_running_loop(),
                session_dir=session_dir,
            )
            if action_lower == "interactive_send":
                typer.echo(result.get("response_text") or "")
        finally:
            await safe_disconnect(manager)

    try:
        asyncio.run(_run())
    except ActionError as exc:
        logger.error("Run failed: %s", exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception("Run failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(name="list-msgs")
def list_msgs(
    target: str = typer.Option(..., "--target", help="Target username/channel"),
    limit: int = typer.Option(10, "--limit", help="Number of messages"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
    no_daemon: bool = typer.Option(False, "--no-daemon", help="Do not use daemon if running"),
):
    """List recent messages."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    if not no_daemon:
        response = _try_daemon_request(
            _daemon_socket(cfg),
            {
                "action": "list",
                "profile": profile,
                "target": target,
                "payload": {"limit": limit},
            },
            logger,
        )
        if response is not None:
            if not response.get("ok"):
                typer.echo(response.get("error", "Daemon request failed"), err=True)
                raise typer.Exit(code=1)
            result = response.get("result") or {}
            for item in result.get("messages") or []:
                typer.echo(f"[{item['date']}] {item['id']} {item['sender_id']}: {item['snippet']}")
            return

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            result = await execute_action(
                "list",
                manager.client,
                target,
                {"limit": limit},
                cfg,
                profile_key,
                profile_data,
                logger,
                loop=asyncio.get_running_loop(),
                session_dir=session_dir,
            )
            messages = result.get("messages") or []
            for item in messages:
                typer.echo(f"[{item['date']}] {item['id']} {item['sender_id']}: {item['snippet']}")
        finally:
            await safe_disconnect(manager)

    try:
        asyncio.run(_run())
    except ActionError as exc:
        logger.error("List failed: %s", exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception("List failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(name="list")
def list_alias(
    target: str = typer.Option(..., "--target", help="Target username/channel"),
    limit: int = typer.Option(10, "--limit", help="Number of messages"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
    no_daemon: bool = typer.Option(False, "--no-daemon", help="Do not use daemon if running"),
):
    """Alias for list-msgs."""
    list_msgs(
        target=target,
        limit=limit,
        profile=profile,
        config=config,
        session_dir=session_dir,
        no_daemon=no_daemon,
    )


@app.command()
def daemon(
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    log_file: str = typer.Option("logs/daemon.log", "--log-file", help="Daemon log file"),
    socket_path: Optional[str] = typer.Option(None, "--socket", help="Daemon IPC socket path"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
):
    """Run scheduled tasks as a daemon."""
    _redirect_std_streams(log_file)
    logger = _setup_logger(log_file=log_file)
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("Config error: %s", exc)
        raise typer.Exit(code=1)

    socket_path = socket_path or _daemon_socket(cfg)
    existing = _try_daemon_request(socket_path, {"action": "ping"}, logger)
    if existing and existing.get("ok"):
        logger.error("Daemon already running at %s", socket_path)
        raise typer.Exit(code=1)

    try:
        asyncio.run(run_daemon(cfg, logger, socket_path, session_dir=session_dir))
    except Exception as exc:
        logger.exception("Daemon failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(name="plugin", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def plugin_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Plugin name under plugins/"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
    no_daemon: bool = typer.Option(False, "--no-daemon", help="Do not use daemon if running"),
):
    """Run a plugin with raw arguments."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    args = list(ctx.args) if ctx else []

    if not no_daemon:
        response = _try_daemon_request(
            _daemon_socket(cfg),
            {
                "action": "plugin_cli",
                "profile": profile,
                "payload": {"plugin": name},
                "args": args,
                "mode": "cli",
            },
            logger,
        )
        if response is not None:
            if not response.get("ok"):
                typer.echo(response.get("error", "Daemon request failed"), err=True)
                raise typer.Exit(code=1)
            return

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            await run_plugin_cli(
                name,
                {
                    "config": cfg,
                    "profile_name": profile_key,
                    "profile": profile_data,
                    "client": manager.client,
                    "logger": logger,
                    "session_dir": session_dir,
                },
                args,
                logger,
                loop=asyncio.get_running_loop(),
            )
        finally:
            await safe_disconnect(manager)

    try:
        asyncio.run(_run())
    except PluginError as exc:
        logger.error("Plugin error: %s", exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception("Plugin failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(name="list-plugins")
def list_plugins_cmd():
    """List available plugins."""
    for name in list_plugins():
        typer.echo(name)


if __name__ == "__main__":
    app()
