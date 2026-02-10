from typing import Optional


ACTION_ALIASES = {
    'send_msg': 'send',
    'dialogs': 'list_dialogs',
}


ACTION_TYPES = {
    'send',
    'interactive_send',
    'download',
    'list',
    'list_dialogs',
    'export',
    'plugin',
    'plugin_cli',
}


def normalize_action_type(action_type: Optional[str]) -> str:
    value = (action_type or '').strip().lower()
    if not value:
        return ''
    return ACTION_ALIASES.get(value, value)


def is_supported_action(action_type: Optional[str]) -> bool:
    return normalize_action_type(action_type) in ACTION_TYPES

