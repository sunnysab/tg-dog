import pathlib
from typing import Any, Dict

import yaml


class ConfigError(RuntimeError):
    pass


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    config_path = pathlib.Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "profiles" not in data or not isinstance(data["profiles"], dict) or not data["profiles"]:
        raise ConfigError("Config must contain a non-empty 'profiles' mapping")
    if "tasks" in data and data["tasks"] is not None and not isinstance(data["tasks"], list):
        raise ConfigError("'tasks' must be a list if provided")
    if "api_id" in data and data["api_id"] is None:
        raise ConfigError("'api_id' cannot be null if provided")
    if "api_hash" in data and data["api_hash"] is None:
        raise ConfigError("'api_hash' cannot be null if provided")
    if "proxy" in data and data["proxy"] is not None and not isinstance(data["proxy"], str):
        raise ConfigError("'proxy' must be a string URL if provided")
    if "daemon_socket" in data and data["daemon_socket"] is not None and not isinstance(data["daemon_socket"], str):
        raise ConfigError("'daemon_socket' must be a string path if provided")
    return data


def resolve_profile(config: Dict[str, Any], profile_name: str | None) -> tuple[str, Dict[str, Any]]:
    profiles = config["profiles"]
    if profile_name:
        if profile_name not in profiles:
            raise ConfigError(f"Profile '{profile_name}' not found in config")
        profile = profiles[profile_name]
        return profile_name, _merge_profile(config, profile)
    default_profile = config.get("default_profile")
    if default_profile:
        if default_profile not in profiles:
            raise ConfigError("'default_profile' does not match any profile in config")
        profile = profiles[default_profile]
        return default_profile, _merge_profile(config, profile)
    first_name = next(iter(profiles))
    return first_name, _merge_profile(config, profiles[first_name])


def _merge_profile(config: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(profile)
    if "proxy" in merged and merged["proxy"] is not None and not isinstance(merged["proxy"], str):
        raise ConfigError("Profile 'proxy' must be a string URL if provided")
    if "api_id" not in merged:
        if "api_id" in config:
            merged["api_id"] = config["api_id"]
    if "api_hash" not in merged:
        if "api_hash" in config:
            merged["api_hash"] = config["api_hash"]
    if "proxy" not in merged:
        if "proxy" in config:
            merged["proxy"] = config["proxy"]
    missing = [key for key in ("api_id", "api_hash", "phone_number") if key not in merged]
    if missing:
        raise ConfigError(f"Profile missing required keys: {', '.join(missing)}")
    return merged
