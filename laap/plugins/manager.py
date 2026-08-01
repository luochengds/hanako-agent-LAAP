"""
LAAP — Plugin Manager
Plugin discovery, loading, and lifecycle management.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

import yaml

from laap.plugins.context import PluginContext
from laap.plugins.plugin import Plugin
from laap.plugins.registry import PluginRegistry

logger = logging.getLogger("laap.plugins")


class PluginLoadError(Exception):
    """Raised when a plugin cannot be loaded."""


class PluginManager:
    """Discovers, loads, and unloads LAAP plugins.

    Each plugin lives in a directory containing a ``plugin.yaml`` manifest and
    an entrypoint module. Activation failures are isolated: they are logged and
    the plugin is marked disabled, but they never crash the manager or the core
    system.
    """

    def __init__(self, plugins_dir: Optional[str] = None, context: Optional[PluginContext] = None) -> None:
        self.plugins_dir = Path(plugins_dir) if plugins_dir is not None else Path("plugins")
        self.context = context or PluginContext()
        self.registry = PluginRegistry()
        self._modules: Dict[str, ModuleType] = {}

    def trigger(self, event: str, **kwargs: Any) -> None:
        """Emit a lifecycle event to all loaded plugins.

        This method is intentionally a no-op by default; plugins that register
        hooks via ``PluginContext`` can respond to events in future iterations.
        It exists so callers such as ``AGIBrain`` can fire events without
        checking for attribute presence.
        """
        logger.debug("Plugin event '%s' triggered with %d kwargs", event, len(kwargs))

    def _load_manifest(self, plugin_path: Path) -> Dict[str, Any]:
        """Read and return the plugin manifest from *plugin_path/plugin.yaml*."""
        manifest_path = plugin_path / "plugin.yaml"
        if not manifest_path.is_file():
            raise PluginLoadError(f"Missing plugin.yaml in {plugin_path}")

        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            raise PluginLoadError(f"Failed to parse {manifest_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise PluginLoadError(f"Invalid plugin.yaml in {plugin_path}")
        return data

    def _check_dependencies(self, dependencies: List[str]) -> None:
        """Verify that all declared dependencies are importable.

        Raises ``PluginLoadError`` on the first missing dependency.
        """
        for dep in dependencies:
            try:
                importlib.import_module(dep)
            except Exception as exc:
                raise PluginLoadError(f"Missing dependency '{dep}': {exc}") from exc

    def _import_entrypoint(self, plugin_path: Path, entrypoint: str) -> ModuleType:
        """Import the plugin entrypoint module from *plugin_path*."""
        module_file = plugin_path / f"{entrypoint}.py"
        if not module_file.is_file():
            raise PluginLoadError(f"Entrypoint '{entrypoint}' not found in {plugin_path}")

        module_name = f"_laap_plugin_{plugin_path.name}_{entrypoint}"
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not create module spec for {module_file}")

        module = importlib.util.module_from_spec(spec)
        # Add the plugin directory to sys.path temporarily so relative imports work.
        sys_path_added = False
        try:
            str_path = str(plugin_path)
            if str_path not in sys.path:
                sys.path.insert(0, str_path)
                sys_path_added = True
            spec.loader.exec_module(module)
        finally:
            if sys_path_added and str_path in sys.path:
                sys.path.remove(str_path)

        return module

    def load(self, plugin_path: str) -> bool:
        """Load a single plugin from *plugin_path*.

        Returns ``True`` on success, ``False`` if the plugin failed to load.
        """
        path = Path(plugin_path)
        try:
            manifest = self._load_manifest(path)
        except PluginLoadError as exc:
            logger.error("Plugin manifest error for %s: %s", plugin_path, exc)
            return False

        name = manifest.get("name") or path.name
        version = manifest.get("version", "0.0.0")
        description = manifest.get("description", "")
        entrypoint = manifest.get("entrypoint", "main")
        dependencies = manifest.get("dependencies", []) or []
        hooks = manifest.get("hooks", {}) or {}

        plugin = Plugin(
            name=name,
            version=version,
            description=description,
            entrypoint=entrypoint,
            dependencies=dependencies,
            hooks=hooks,
            enabled=True,
        )

        try:
            self._check_dependencies(dependencies)
            module = self._import_entrypoint(path, entrypoint)
            self._modules[name] = module
            self.registry.register(plugin)

            if hasattr(module, "activate"):
                module.activate(self.context)

            logger.info("Plugin loaded: %s v%s", name, version)
            return True
        except Exception as exc:
            logger.error("Plugin activation failed for '%s': %s", name, exc)
            plugin.enabled = False
            self.registry.register(plugin)
            return False

    def unload(self, name: str) -> bool:
        """Unload a plugin by name.

        Calls ``deactivate()`` on the plugin module if it exists, then removes
        the plugin from the registry.
        """
        plugin = self.registry.get(name)
        if plugin is None:
            logger.warning("Cannot unload unknown plugin: %s", name)
            return False

        module = self._modules.pop(name, None)
        if module is not None and hasattr(module, "deactivate"):
            try:
                module.deactivate()
            except Exception as exc:
                logger.error("Plugin deactivate failed for '%s': %s", name, exc)

        self.registry.remove(name)
        logger.info("Plugin unloaded: %s", name)
        return True

    def load_all(self) -> Dict[str, bool]:
        """Scan *plugins_dir* and attempt to load every plugin subdirectory.

        Returns a mapping of plugin name -> success status.  Failures are
        isolated per plugin.
        """
        results: Dict[str, bool] = {}
        if not self.plugins_dir.is_dir():
            logger.warning("Plugins directory does not exist: %s", self.plugins_dir)
            return results

        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "plugin.yaml").is_file():
                continue
            name = entry.name
            try:
                results[name] = self.load(str(entry))
            except Exception as exc:
                logger.error("Unexpected error loading plugin '%s': %s", name, exc)
                results[name] = False
        return results

    def list_plugins(self) -> List[Plugin]:
        """Return all registered plugin descriptors."""
        return self.registry.list_plugins()
