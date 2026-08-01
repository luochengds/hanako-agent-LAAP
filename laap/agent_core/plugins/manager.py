"""PluginManager — 统一插件管理"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.plugins")


class PluginManager:
    """插件管理器 — 加载/卸载/列表"""
    
    def __init__(self):
        self._plugins: Dict[str, Any] = {}
    
    @property
    def plugins(self) -> Dict[str, Any]:
        return dict(self._plugins)
    
    def init_plugins(self, agent=None):
        pass
    
    def load(self, plugin) -> Any:
        name = getattr(plugin, "name", plugin.__class__.__name__)
        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' already loaded")
        self._plugins[name] = plugin
        logger.info(f"Plugin loaded: {name}")
        return plugin
    
    def unload(self, name: str):
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' not found")
        del self._plugins[name]
        logger.info(f"Plugin unloaded: {name}")
    
    def list_plugins(self) -> List[str]:
        return list(self._plugins.keys())
    
    def get(self, name: str) -> Optional[Any]:
        return self._plugins.get(name)
