import asyncio
from typing import Any, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.actions import download_media, interactive_send, list_messages, send_message
from core.client_manager import ClientManager, safe_disconnect
from core.config import resolve_profile


action_map = {
    "send_msg": send_message,
    "send": send_message,
    "interactive_send": interactive_send,
    "download": download_media,
    "list": list_messages,
}


async def _run_task(task: Dict[str, Any], config: Dict[str, Any], logger) -> None:
    profile_name = task.get("profile")
    profile_key, profile = resolve_profile(config, profile_name)

    manager = ClientManager(
        api_id=int(profile["api_id"]),
        api_hash=profile["api_hash"],
        phone_number=profile["phone_number"],
    )
    await manager.connect(profile_key)
    try:
        authorized = await manager.ensure_authorized(interactive=False)
        if not authorized:
            logger.error("Profile '%s' is not authorized; run auth first", profile_key)
            return
        client = manager.client
        action_type = task.get("action_type")
        if action_type not in action_map:
            logger.error("Unknown action_type '%s'", action_type)
            return
        target = task.get("target")
        if not target:
            logger.error("Task missing 'target'")
            return
        payload = task.get("payload") or {}

        if action_type in {"send_msg", "send"}:
            text = payload.get("text") or payload.get("message")
            if not text:
                logger.error("send action requires payload.text")
                return
            await send_message(client, target, text, logger)
        elif action_type == "interactive_send":
            text = payload.get("text") or payload.get("message")
            if not text:
                logger.error("interactive_send requires payload.text")
                return
            await interactive_send(client, target, text, logger, timeout=int(payload.get("timeout", 30)))
        elif action_type == "download":
            await download_media(
                client,
                target,
                limit=int(payload.get("limit", 5)),
                logger=logger,
                media_type=payload.get("media_type", "any"),
                min_size=payload.get("min_size"),
                max_size=payload.get("max_size"),
                output_dir=payload.get("output_dir", "downloads"),
            )
        elif action_type == "list":
            messages = await list_messages(client, target, int(payload.get("limit", 10)), logger)
            logger.info("Listed %s messages for %s", len(messages), target)
    finally:
        await safe_disconnect(manager)


def build_scheduler(config: Dict[str, Any], logger) -> AsyncIOScheduler:
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
            args=[task, config, logger],
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
