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
    return data


def resolve_profile(config: Dict[str, Any], profile_name: str | None) -> tuple[str, Dict[str, Any]]:
    profiles = config["profiles"]
    if profile_name:
        if profile_name not in profiles:
            raise ConfigError(f"Profile '{profile_name}' not found in config")
        return profile_name, profiles[profile_name]
    default_profile = config.get("default_profile")
    if default_profile:
        if default_profile not in profiles:
            raise ConfigError("'default_profile' does not match any profile in config")
        return default_profile, profiles[default_profile]
    first_name = next(iter(profiles))
    return first_name, profiles[first_name]
