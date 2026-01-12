import asyncio
import logging
import pathlib
import sys
from typing import Optional

import typer

from core.actions import download_media, interactive_send, list_messages, send_message
from core.client_manager import ClientManager, safe_disconnect
from core.config import ConfigError, load_config, resolve_profile
from core.scheduler import build_scheduler, run_scheduler_until_stopped
from core.plugins import PluginError, list_plugins, run_plugin

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

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            client = manager.client
            if action_lower == "send":
                if not text:
                    raise ValueError("--text is required for send")
                await send_message(client, target, text, logger)
            elif action_lower == "interactive_send":
                if not text:
                    raise ValueError("--text is required for interactive_send")
                response = await interactive_send(client, target, text, logger, timeout=timeout)
                if response is not None:
                    typer.echo(response.text or "")
            elif action_lower == "download":
                await download_media(
                    client,
                    target,
                    limit=limit,
                    logger=logger,
                    media_type=media_type,
                    min_size=min_size,
                    max_size=max_size,
                    output_dir=output_dir,
                )
            else:
                raise ValueError("Unsupported action; use send | interactive_send | download")
        finally:
            await safe_disconnect(manager)

    try:
        asyncio.run(_run())
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
):
    """List recent messages."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            messages = await list_messages(manager.client, target, limit, logger)
            for item in messages:
                typer.echo(f"[{item['date']}] {item['id']} {item['sender_id']}: {item['snippet']}")
        finally:
            await safe_disconnect(manager)

    try:
        asyncio.run(_run())
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
):
    """Alias for list-msgs."""
    list_msgs(target=target, limit=limit, profile=profile, config=config, session_dir=session_dir)


@app.command()
def daemon(
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    log_file: str = typer.Option("logs/daemon.log", "--log-file", help="Daemon log file"),
):
    """Run scheduled tasks as a daemon."""
    _redirect_std_streams(log_file)
    logger = _setup_logger(log_file=log_file)
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        logger.error("Config error: %s", exc)
        raise typer.Exit(code=1)

    async def _run():
        scheduler = build_scheduler(cfg, logger)
        await run_scheduler_until_stopped(scheduler, logger)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.exception("Daemon failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(name="plugin")
def plugin_cmd(
    name: str = typer.Argument(..., help="Plugin name under plugins/"),
    args: list[str] = typer.Argument(None, help="Arguments passed to plugin"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name in config"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    session_dir: str = typer.Option("sessions", "--session-dir", help="Session storage dir"),
):
    """Run a plugin with raw arguments."""
    logger = _setup_logger()
    try:
        cfg = load_config(config)
        profile_key, profile_data = resolve_profile(cfg, profile)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    async def _run():
        manager = await _with_client(profile_key, profile_data, session_dir, False, logger)
        try:
            await run_plugin(
                name,
                {
                    "config": cfg,
                    "profile_name": profile_key,
                    "profile": profile_data,
                    "client": manager.client,
                    "logger": logger,
                    "session_dir": session_dir,
                },
                args or [],
                logger,
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
