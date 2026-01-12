import asyncio
import importlib.util
import pathlib
from typing import Any, Dict, List, Optional

import typer
from typer.main import get_command


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


def _call_helper(loop: Optional[asyncio.AbstractEventLoop]):
    def _call(coro):
        if loop is None:
            return asyncio.run(coro)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    return _call


async def run_plugin_code(name: str, context: Dict[str, Any], args: List[str], logger) -> Any:
    module = load_plugin(name)
    runner = _get_plugin_runner(module)
    if runner is None:
        raise PluginError("Plugin must define run(context, args) or main(context, args)")

    result = runner(context, args)
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
