from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib.util
import json
import traceback


@dataclass
class PluginContribution:
    plugin_id: str
    name: str
    version: str
    explorer_path: list[str]
    label: str
    open_handler: Callable[[Any], Any]
    description: str = ""
    enabled: bool = True
    folder: Path | None = None


class PluginHostAPI:
    """Small stable surface exposed to plugins.

    Plugins receive the MainWindow through ``host`` only for opening managed pages;
    paths and common services are exposed as properties so plugins do not guess
    private attributes.
    """
    def __init__(self, host: Any):
        self.host = host

    @property
    def project(self):
        return self.host.project

    @property
    def workspace(self):
        return self.host.workspace

    def log(self, level: str, message: str) -> None:
        self.host.write_output(level, message)

    def inspect(self, title: str, values: dict[str, Any]) -> None:
        self.host._set_inspector(title, values)

    def add_tab(self, key: str, title: str, frame: Any, *, pinned: bool = False):
        return self.host._add_managed_tab(f"plugin:{key}", title, frame, kind="plugin", pinned=pinned)

    def show_error(self, title: str, message: str) -> None:
        from tkinter import messagebox
        messagebox.showerror(title, message, parent=self.host)


class PluginManager:
    def __init__(self, plugins_root: Path, host: Any):
        self.plugins_root = Path(plugins_root)
        self.host = host
        self.api = PluginHostAPI(host)
        self.contributions: dict[str, PluginContribution] = {}
        self.errors: list[str] = []

    def discover(self) -> list[PluginContribution]:
        self.contributions.clear()
        self.errors.clear()
        self.plugins_root.mkdir(parents=True, exist_ok=True)
        for folder in sorted((p for p in self.plugins_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            manifest_path = folder / "plugin.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not manifest.get("enabled", True):
                    continue
                plugin_id = str(manifest["id"])
                entry = folder / str(manifest.get("entry", "plugin.py"))
                spec = importlib.util.spec_from_file_location(f"crystal_legacy_plugin_{plugin_id}", entry)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not load plugin entry {entry}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                registered = module.register(self.api, manifest)
                handler = registered.get("open") if isinstance(registered, dict) else registered
                if not callable(handler):
                    raise TypeError("register() must return a callable or {'open': callable}")
                contribution = PluginContribution(
                    plugin_id=plugin_id,
                    name=str(manifest.get("name", plugin_id)),
                    version=str(manifest.get("version", "0.0.0")),
                    explorer_path=list(manifest.get("explorer_path", ["Plugins"])),
                    label=str(manifest.get("label", manifest.get("name", plugin_id))),
                    open_handler=handler,
                    description=str(manifest.get("description", "")),
                    folder=folder,
                )
                self.contributions[plugin_id] = contribution
            except Exception as exc:
                self.errors.append(f"{folder.name}: {exc}")
                traceback.print_exc()
        return list(self.contributions.values())

    def get(self, plugin_id: str) -> PluginContribution | None:
        return self.contributions.get(plugin_id)

    def open(self, plugin_id: str):
        contribution = self.get(plugin_id)
        if not contribution:
            raise KeyError(plugin_id)
        return contribution.open_handler(self.api)
