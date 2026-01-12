import asyncio
import importlib.util
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional, Tuple

import typer
from typer.main import get_command


class PluginError(RuntimeError):
    pass


_PLUGIN_CACHE: Dict[str, Tuple[float, Any]] = {}


def _project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def plugin_root() -> pathlib.Path:
    return _project_root() / "plugins"


def plugin_state_path() -> pathlib.Path:
    return _project_root() / "data" / "plugins.json"


def load_plugin_state(path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    state_path = path or plugin_state_path()
    if not state_path.exists():
        return {"plugins": {}}
    with state_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "plugins" not in data or not isinstance(data["plugins"], dict):
        return {"plugins": {}}
    return data


def save_plugin_state(state: Dict[str, Any], path: Optional[pathlib.Path] = None) -> None:
    state_path = path or plugin_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_plugin_enabled(name: str, path: Optional[pathlib.Path] = None) -> bool:
    state = load_plugin_state(path)
    return state.get("plugins", {}).get(name, True)


def set_plugin_enabled(name: str, enabled: bool, path: Optional[pathlib.Path] = None) -> None:
    state = load_plugin_state(path)
    state.setdefault("plugins", {})[name] = bool(enabled)
    save_plugin_state(state, path)


def list_plugin_states(path: Optional[pathlib.Path] = None) -> Dict[str, bool]:
    state = load_plugin_state(path)
    return {key: bool(value) for key, value in state.get("plugins", {}).items()}


def list_plugins() -> List[str]:
    root = plugin_root()
    if not root.exists():
        return []
    result = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        plugin_file = item / "plugin.py"
        if plugin_file.exists():
            result.append(item.name)
    return sorted(result)


def load_plugin(name: str):
    root = plugin_root()
    plugin_dir = root / name
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        raise PluginError(f"Plugin '{name}' not found in {root}")
    plugin_file = plugin_dir / "plugin.py"
    if not plugin_file.exists():
        raise PluginError(f"Plugin '{name}' missing plugin.py")
    module_name = f"tg_dog_plugin_{name}"
    mtime = plugin_file.stat().st_mtime
    cached = _PLUGIN_CACHE.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise PluginError(f"Failed to load plugin '{name}'")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _PLUGIN_CACHE[name] = (mtime, module)
    return module


def _get_plugin_app(module):
    app = getattr(module, "app", None)
    if isinstance(app, typer.Typer):
        return app
    build_cli = getattr(module, "build_cli", None)
    if callable(build_cli):
        built = build_cli()
        if isinstance(built, typer.Typer):
            return built
    return None


def _get_plugin_runner(module):
    return getattr(module, "run", None) or getattr(module, "main", None)


def _get_plugin_setup(module):
    return getattr(module, "setup", None)


def _call_helper(loop: Optional[asyncio.AbstractEventLoop]):
    def _call(coro):
        if loop is None:
            return asyncio.run(coro)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    return _call


async def run_plugin_code(name: str, context: Dict[str, Any], args: List[str], logger) -> Any:
    if not is_plugin_enabled(name):
        raise PluginError(f"Plugin '{name}' is disabled")
    module = load_plugin(name)
    runner = _get_plugin_runner(module)
    if runner is None:
        raise PluginError("Plugin must define run(context, args) or main(context, args)")

    result = runner(context, args)
    if hasattr(result, "__await__"):
        return await result
    return result


async def run_plugin_setup(name: str, context: Dict[str, Any], args: List[str], logger) -> Any:
    if not is_plugin_enabled(name):
        raise PluginError(f"Plugin '{name}' is disabled")
    module = load_plugin(name)
    setup = _get_plugin_setup(module)
    if setup is None:
        raise PluginError("Plugin must define setup(context, args) for listeners")
    result = setup(context, args)
    if hasattr(result, "__await__"):
        return await result
    return result


async def run_plugin_cli(
    name: str,
    context: Dict[str, Any],
    args: List[str],
    logger,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> Any:
    if not is_plugin_enabled(name):
        raise PluginError(f"Plugin '{name}' is disabled")
    module = load_plugin(name)
    app = _get_plugin_app(module)
    if app is None:
        return await run_plugin_code(name, context, args, logger)

    context = dict(context)
    context["call"] = _call_helper(loop)
    context["args"] = list(args)

    command = get_command(app)
    await asyncio.to_thread(
        command.main,
        args=args,
        prog_name=f"tg-dog plugin {name}",
        standalone_mode=False,
        obj=context,
    )
    return None
