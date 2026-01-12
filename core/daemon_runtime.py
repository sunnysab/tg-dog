import asyncio
from typing import Any, Dict, Optional

from core.client_manager import ClientManager, safe_disconnect
from core.config import resolve_profile
from core.executor import ActionError, execute_action
from core.ipc import start_server
from core.scheduler import build_scheduler


class DaemonError(RuntimeError):
    pass


class ClientPool:
    def __init__(self, config: Dict[str, Any], session_dir: str, logger) -> None:
        self.config = config
        self.session_dir = session_dir
        self.logger = logger
        self._clients: Dict[str, ClientManager] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def _ensure_client(self, profile_name: Optional[str]):
        profile_key, profile = resolve_profile(self.config, profile_name)
        manager = self._clients.get(profile_key)
        if manager is None:
            manager = ClientManager(
                api_id=int(profile["api_id"]),
                api_hash=profile["api_hash"],
                phone_number=profile["phone_number"],
                session_dir=self.session_dir,
                proxy_url=profile.get("proxy"),
            )
            await manager.connect(profile_key)
            authorized = await manager.ensure_authorized(interactive=False)
            if not authorized:
                raise DaemonError(f"Profile '{profile_key}' is not authorized")
            self._clients[profile_key] = manager
            self._locks[profile_key] = asyncio.Lock()
        else:
            if not manager.client.is_connected():
                await manager.client.connect()
        return manager, profile_key, profile, self._locks[profile_key]

    async def run_action(
        self,
        profile_name: Optional[str],
        action_type: str,
        target: Optional[str],
        payload: Dict[str, Any],
        args=None,
        mode: str = "code",
    ) -> Dict[str, Any]:
        manager, profile_key, profile, lock = await self._ensure_client(profile_name)
        async with lock:
            return await execute_action(
                action_type,
                manager.client,
                target,
                payload,
                self.config,
                profile_key,
                profile,
                self.logger,
                args=args,
                mode=mode,
                loop=asyncio.get_running_loop(),
                session_dir=self.session_dir,
            )

    async def close(self) -> None:
        for manager in list(self._clients.values()):
            await safe_disconnect(manager)
        self._clients.clear()
        self._locks.clear()


async def run_daemon(
    config: Dict[str, Any],
    logger,
    socket_path: str,
    session_dir: str = "sessions",
) -> None:
    pool = ClientPool(config, session_dir, logger)

    async def _handle(request: Dict[str, Any]) -> Dict[str, Any]:
        action = request.get("action")
        if action == "ping":
            return {"ok": True}
        try:
            result = await pool.run_action(
                profile_name=request.get("profile"),
                action_type=action,
                target=request.get("target"),
                payload=request.get("payload") or {},
                args=request.get("args"),
                mode=request.get("mode", "code"),
            )
            return {"ok": True, "result": result}
        except (ActionError, DaemonError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("Daemon action failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    scheduler = build_scheduler(config, logger, pool=pool)
    server = await start_server(socket_path, _handle, logger)

    stop_event = asyncio.Event()

    def _stop():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(__import__("signal"), sig), _stop)
        except (NotImplementedError, RuntimeError):
            pass

    scheduler.start()
    await stop_event.wait()

    scheduler.shutdown(wait=False)
    server.close()
    await server.wait_closed()
    await pool.close()
    try:
        import pathlib

        path = pathlib.Path(socket_path)
        if path.exists():
            path.unlink()
    except Exception:
        logger.warning("Failed to remove socket file %s", socket_path)
