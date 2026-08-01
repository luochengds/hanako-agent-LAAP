"""LAAP plugin registry."""
from __future__ import annotations

import threading
from typing import List, Optional

from laap.plugins.plugin import Plugin


class PluginRegistry:
    """In-memory registry of discovered/loaded plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._lock = threading.RLock()

    def register(self, plugin: Plugin) -> None:
        """Register a plugin descriptor."""
        with self._lock:
            self._plugins[plugin.name] = plugin

    def get(self, name: str) -> Optional[Plugin]:
        """Return the plugin named *name* or ``None``."""
        with self._lock:
            return self._plugins.get(name)

    def list_plugins(self) -> List[Plugin]:
        """Return all registered plugins."""
        with self._lock:
            return list(self._plugins.values())

    def enable(self, name: str) -> bool:
        """Enable a plugin. Returns ``True`` if the plugin existed."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return False
            plugin.enabled = True
            return True

    def disable(self, name: str) -> bool:
        """Disable a plugin. Returns ``True`` if the plugin existed."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return False
            plugin.enabled = False
            return True

    def remove(self, name: str) -> bool:
        """Remove a plugin from the registry."""
        with self._lock:
            return self._plugins.pop(name, None) is not None
