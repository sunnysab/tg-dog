import importlib.util
import pathlib
from typing import Any, Dict, List


class PluginError(RuntimeError):
    pass


def _project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def plugin_root() -> pathlib.Path:
    return _project_root() / "plugins"


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
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise PluginError(f"Failed to load plugin '{name}'")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_plugin(name: str, context: Dict[str, Any], args: List[str], logger) -> Any:
    module = load_plugin(name)
    runner = getattr(module, "run", None) or getattr(module, "main", None)
    if runner is None:
        raise PluginError("Plugin must define run(context, args) or main(context, args)")

    result = runner(context, args)
    if hasattr(result, "__await__"):
        return await result
    return result
