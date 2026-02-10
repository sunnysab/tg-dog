import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import typer

from core.action_types import normalize_action_type
from core.client_manager import safe_disconnect
from core.executor import execute_action
from core.ipc import IpcError, send_request


@dataclass(slots=True)
class LocalRunContext:
    profile_key: str
    profile_data: dict[str, Any]
    session_dir: str
    cfg: dict[str, Any]
    logger: Any
    with_client: Any


def try_daemon_request(socket_path: str, request: dict[str, Any], logger):
    async def _send():
        return await send_request(socket_path, request)

    try:
        return asyncio.run(_send())
    except (FileNotFoundError, ConnectionError, IpcError, OSError):
        return None
    except Exception as exc:
        logger.error('Daemon request failed: %s', exc)
        return None


def run_action_local(
    local_ctx: LocalRunContext,
    action_type: str,
    target: Optional[str],
    payload: dict[str, Any],
):
    normalized = normalize_action_type(action_type)

    async def _run():
        manager = await local_ctx.with_client(
            local_ctx.profile_key,
            local_ctx.profile_data,
            local_ctx.session_dir,
            False,
            local_ctx.logger,
        )
        try:
            return await execute_action(
                normalized,
                manager.client,
                target,
                payload,
                local_ctx.cfg,
                local_ctx.profile_key,
                local_ctx.profile_data,
                local_ctx.logger,
                loop=asyncio.get_running_loop(),
                session_dir=local_ctx.session_dir,
            )
        finally:
            await safe_disconnect(manager)

    return asyncio.run(_run())


def run_action_with_optional_daemon(
    *,
    action_type: str,
    target: Optional[str],
    payload: dict[str, Any],
    profile_name: Optional[str],
    socket_path: str,
    no_daemon: bool,
    logger,
    local_ctx: LocalRunContext,
):
    normalized = normalize_action_type(action_type)
    if not no_daemon:
        response = try_daemon_request(
            socket_path,
            {
                'action': normalized,
                'profile': profile_name,
                'target': target,
                'payload': payload,
            },
            logger,
        )
        if response is not None:
            if not response.get('ok'):
                typer.echo(response.get('error', 'Daemon request failed'), err=True)
                raise typer.Exit(code=1)
            return response.get('result') or {}
    return run_action_local(local_ctx, normalized, target, payload)

