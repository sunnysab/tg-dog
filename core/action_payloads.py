from dataclasses import dataclass
from typing import Any, Optional

from core.action_types import normalize_action_type


@dataclass(slots=True)
class RunPayloadOptions:
    text: Optional[str] = None
    limit: int = 5
    media_type: str = 'any'
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    output_dir: str = 'downloads'
    timeout: int = 30
    mark_read: bool = False
    export_output: str = 'exports'
    export_mode: str = 'single'
    attachments_dir: Optional[str] = None
    from_user: Optional[str] = None
    message_ids: Optional[list[int]] = None


def build_list_payload(limit: int, mark_read: bool = False) -> dict[str, Any]:
    return {
        'limit': limit,
        'mark_read': mark_read,
    }


def build_export_payload(
    output: str,
    mode: str,
    attachments_dir: Optional[str],
    limit: Optional[int],
    from_user: Optional[str],
    message_ids: Optional[list[int]],
    mark_read: bool,
) -> dict[str, Any]:
    return {
        'output': output,
        'mode': mode,
        'attachments_dir': attachments_dir,
        'limit': limit,
        'from_user': from_user,
        'message_ids': message_ids,
        'mark_read': mark_read,
    }


def build_plugin_payload(plugin: str, args: list[str], mode: str = 'cli') -> dict[str, Any]:
    return {
        'plugin': plugin,
        'args': list(args),
        'mode': mode,
    }


def build_run_payload(action_type: str, options: RunPayloadOptions) -> dict[str, Any]:
    normalized = normalize_action_type(action_type)
    payload: dict[str, Any] = {}
    if normalized in {'send', 'interactive_send'}:
        if not options.text:
            raise ValueError('--text is required for send/interactive_send')
        payload['text'] = options.text
        if normalized == 'interactive_send':
            payload['timeout'] = options.timeout
        return payload
    if normalized == 'download':
        payload.update(
            {
                'limit': options.limit,
                'media_type': options.media_type,
                'min_size': options.min_size,
                'max_size': options.max_size,
                'output_dir': options.output_dir,
            }
        )
        return payload
    if normalized == 'export':
        payload.update(
            {
                'output': options.export_output,
                'mode': options.export_mode,
                'attachments_dir': options.attachments_dir,
                'limit': options.limit,
                'from_user': options.from_user,
                'message_ids': options.message_ids,
                'mark_read': options.mark_read,
            }
        )
        return payload
    return payload

