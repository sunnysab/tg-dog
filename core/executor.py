import json
from typing import Any, Dict, List, Optional

from core.actions import download_media, export_messages, interactive_send, list_dialogs, list_messages, send_message
from core.plugins import run_plugin_cli, run_plugin_code


class ActionError(RuntimeError):
    pass


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


async def execute_action(
    action_type: str,
    client,
    target: Optional[str],
    payload: Dict[str, Any],
    config: Dict[str, Any],
    profile_key: str,
    profile: Dict[str, Any],
    logger,
    args: Optional[List[str]] = None,
    mode: str = "code",
    loop=None,
    session_dir: str = "sessions",
) -> Dict[str, Any]:
    action_type = (action_type or "").lower()
    if action_type in {"send_msg", "send"}:
        if not target:
            raise ActionError("Missing target")
        text = payload.get("text") or payload.get("message")
        if not text:
            raise ActionError("send action requires payload.text")
        await send_message(client, target, text, logger)
        return {"status": "sent"}
    if action_type == "interactive_send":
        if not target:
            raise ActionError("Missing target")
        text = payload.get("text") or payload.get("message")
        if not text:
            raise ActionError("interactive_send requires payload.text")
        response = await interactive_send(client, target, text, logger, timeout=int(payload.get("timeout", 30)))
        return {"response_text": response.text if response is not None else None}
    if action_type == "download":
        if not target:
            raise ActionError("Missing target")
        downloaded = await download_media(
            client,
            target,
            limit=int(payload.get("limit", 5)),
            logger=logger,
            media_type=payload.get("media_type", "any"),
            min_size=payload.get("min_size"),
            max_size=payload.get("max_size"),
            output_dir=payload.get("output_dir", "downloads"),
        )
        return {"downloaded": downloaded}
    if action_type == "list":
        if not target:
            raise ActionError("Missing target")
        messages = await list_messages(client, target, int(payload.get("limit", 10)), logger)
        return {"messages": messages}
    if action_type in {"list_dialogs", "dialogs"}:
        dialogs = await list_dialogs(client, int(payload.get("limit", 30)), logger)
        return {"dialogs": dialogs}
    if action_type == "export":
        if not target:
            raise ActionError("Missing target")
        output = payload.get("output") or "exports"
        mode = payload.get("mode", "single")
        attachments_dir = payload.get("attachments_dir")
        limit = payload.get("limit")
        from_user = payload.get("from_user")
        message_ids = payload.get("message_ids")
        if isinstance(message_ids, str):
            message_ids = [int(value) for value in message_ids.split(",") if value]
        if isinstance(message_ids, list):
            message_ids = [int(value) for value in message_ids]
        result = await export_messages(
            client,
            target,
            logger,
            output=output,
            mode=mode,
            attachments_dir=attachments_dir,
            limit=limit,
            from_user=from_user,
            message_ids=message_ids,
        )
        return result
    if action_type in {"plugin", "plugin_cli"}:
        plugin_name = payload.get("plugin") or payload.get("name")
        if not plugin_name:
            raise ActionError("plugin action requires payload.plugin")
        args = args or payload.get("args") or []
        if isinstance(args, str):
            args = [args]
        if mode == "cli" or action_type == "plugin_cli":
            await run_plugin_cli(
                plugin_name,
                {
                    "config": config,
                    "profile_name": profile_key,
                    "profile": profile,
                    "client": client,
                    "logger": logger,
                    "session_dir": session_dir,
                },
                list(args),
                logger,
                loop=loop,
            )
            return {"result": None}
        result = await run_plugin_code(
            plugin_name,
            {
                "config": config,
                "profile_name": profile_key,
                "profile": profile,
                "client": client,
                "logger": logger,
                "session_dir": session_dir,
            },
            list(args),
            logger,
        )
        return {"result": _serialize(result)}

    raise ActionError(f"Unknown action_type '{action_type}'")
