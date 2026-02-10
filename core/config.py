import pathlib
from typing import Any, Dict

import yaml


class ConfigError(RuntimeError):
    pass


def _ensure_optional_string(value: Any, key: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ConfigError(f"'{key}' must be a string")


def _ensure_profile_schema(profile_name: str, profile: Any) -> None:
    if not isinstance(profile, dict):
        raise ConfigError(f"Profile '{profile_name}' must be a mapping")
    if 'proxy' in profile and profile['proxy'] is not None and not isinstance(profile['proxy'], str):
        raise ConfigError(f"Profile '{profile_name}' proxy must be a string URL if provided")


def _ensure_task_or_listener_items(items: list[Any], key: str) -> None:
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"'{key}[{index}]' must be a mapping")


def _ensure_profile_values(profile_name: str, profile: Dict[str, Any]) -> None:
    api_id = profile.get('api_id')
    api_hash = profile.get('api_hash')
    phone_number = profile.get('phone_number')

    try:
        int(api_id)
    except (TypeError, ValueError):
        raise ConfigError(f"Profile '{profile_name}' has invalid 'api_id'") from None

    if not isinstance(api_hash, str) or not api_hash.strip():
        raise ConfigError(f"Profile '{profile_name}' has invalid 'api_hash'")
    if not isinstance(phone_number, str) or not phone_number.strip():
        raise ConfigError(f"Profile '{profile_name}' has invalid 'phone_number'")


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    config_path = pathlib.Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "profiles" not in data or not isinstance(data["profiles"], dict) or not data["profiles"]:
        raise ConfigError("Config must contain a non-empty 'profiles' mapping")
    if 'tasks' in data and data['tasks'] is not None and not isinstance(data['tasks'], list):
        raise ConfigError("'tasks' must be a list if provided")
    if 'listeners' in data and data['listeners'] is not None and not isinstance(data['listeners'], list):
        raise ConfigError("'listeners' must be a list if provided")
    if 'api_id' in data and data['api_id'] is None:
        raise ConfigError("'api_id' cannot be null if provided")
    if 'api_hash' in data and data['api_hash'] is None:
        raise ConfigError("'api_hash' cannot be null if provided")
    _ensure_optional_string(data.get('proxy'), 'proxy')
    _ensure_optional_string(data.get('daemon_socket'), 'daemon_socket')

    if data.get('tasks') is not None:
        _ensure_task_or_listener_items(data['tasks'], 'tasks')
    if data.get('listeners') is not None:
        _ensure_task_or_listener_items(data['listeners'], 'listeners')

    profiles = data['profiles']
    for profile_name, profile in profiles.items():
        _ensure_profile_schema(profile_name, profile)
    return data


def resolve_profile(config: Dict[str, Any], profile_name: str | None) -> tuple[str, Dict[str, Any]]:
    profiles = config["profiles"]
    if profile_name:
        if profile_name not in profiles:
            raise ConfigError(f"Profile '{profile_name}' not found in config")
        profile = profiles[profile_name]
        return profile_name, _merge_profile(config, profile_name, profile)
    default_profile = config.get("default_profile")
    if default_profile:
        if default_profile not in profiles:
            raise ConfigError("'default_profile' does not match any profile in config")
        profile = profiles[default_profile]
        return default_profile, _merge_profile(config, default_profile, profile)
    first_name = next(iter(profiles))
    return first_name, _merge_profile(config, first_name, profiles[first_name])


def _merge_profile(config: Dict[str, Any], profile_name: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(profile)
    if 'proxy' in merged and merged['proxy'] is not None and not isinstance(merged['proxy'], str):
        raise ConfigError("Profile 'proxy' must be a string URL if provided")
    if 'api_id' not in merged and 'api_id' in config:
        merged['api_id'] = config['api_id']
    if 'api_hash' not in merged and 'api_hash' in config:
        merged['api_hash'] = config['api_hash']
    if 'proxy' not in merged and 'proxy' in config:
        merged['proxy'] = config['proxy']
    missing = [key for key in ('api_id', 'api_hash', 'phone_number') if key not in merged]
    if missing:
        raise ConfigError(f"Profile missing required keys: {', '.join(missing)}")

    _ensure_profile_values(profile_name, merged)
    return merged
