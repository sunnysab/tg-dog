import asyncio
from typing import Any, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.client_manager import ClientManager, safe_disconnect
from core.config import resolve_profile
from core.executor import ActionError, execute_action


action_map = {
    "send_msg",
    "send",
    "interactive_send",
    "download",
    "list",
    "list_dialogs",
    "export",
    "plugin",
    "plugin_cli",
}


async def _run_task(task: Dict[str, Any], config: Dict[str, Any], logger, pool=None) -> None:
    profile_name = task.get("profile")
    action_type = task.get("action_type")
    if action_type not in action_map:
        logger.error("Unknown action_type '%s'", action_type)
        return
    payload = task.get("payload") or {}
    target = task.get("target")
    mode = payload.get("mode", "code")
    args = payload.get("args")

    if pool is not None:
        try:
            await pool.run_action(profile_name, action_type, target, payload, args=args, mode=mode)
        except Exception as exc:
            logger.error("Task failed: %s", exc)
        return

    profile_key, profile = resolve_profile(config, profile_name)
    manager = ClientManager(
        api_id=int(profile["api_id"]),
        api_hash=profile["api_hash"],
        phone_number=profile["phone_number"],
        proxy_url=profile.get("proxy"),
    )
    await manager.connect(profile_key)
    try:
        authorized = await manager.ensure_authorized(interactive=False)
        if not authorized:
            logger.error("Profile '%s' is not authorized; run auth first", profile_key)
            return
        await execute_action(
            action_type,
            manager.client,
            target,
            payload,
            config,
            profile_key,
            profile,
            logger,
            args=args,
            mode=mode,
            loop=asyncio.get_running_loop(),
            session_dir=str(manager.session_dir) if hasattr(manager, "session_dir") else "sessions",
        )
    except ActionError as exc:
        logger.error("Task failed: %s", exc)
    finally:
        await safe_disconnect(manager)


def build_scheduler(config: Dict[str, Any], logger, pool=None) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    tasks = config.get("tasks") or []
    for index, task in enumerate(tasks, start=1):
        trigger_time = task.get("trigger_time")
        if not trigger_time:
            logger.error("Task %s missing trigger_time", index)
            continue
        try:
            trigger = CronTrigger.from_crontab(trigger_time)
        except ValueError:
            logger.exception("Invalid cron expression for task %s: %s", index, trigger_time)
            continue

        scheduler.add_job(
            _run_task,
            trigger=trigger,
            args=[task, config, logger, pool],
            id=f"task_{index}",
            max_instances=1,
            coalesce=True,
        )
    return scheduler


async def run_scheduler_until_stopped(scheduler: AsyncIOScheduler, logger) -> None:
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
