"""Plugin Hooks — 插件生命周期钩子"""
from __future__ import annotations
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.plugins")


class HookPoint(str, Enum):
    BEFORE_PROCESS = "before_process"
    AFTER_PROCESS = "after_process"
    BEFORE_CHAT = "before_chat"
    AFTER_CHAT = "after_chat"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    ON_ERROR = "on_error"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"


class HookRegistry:
    """钩子注册表 — 注册/触发/卸载"""
    
    def __init__(self):
        self._hooks: Dict[str, List[Tuple[int, Callable]]] = {}
    
    @property
    def hooks(self) -> Dict[str, List[Callable]]:
        return {k: [h for _, h in v] for k, v in self._hooks.items()}
    
    
    def register(self, hook_point: str, handler: Callable, priority: int = 10):
        hp = hook_point.value if isinstance(hook_point, HookPoint) else hook_point
        if hp not in self._hooks:
            self._hooks[hp] = []
        self._hooks[hp].append((priority, handler))
        self._hooks[hp].sort(key=lambda x: x[0])
    
    def unregister(self, hook_point: str, handler: Callable):
        hp = hook_point.value if isinstance(hook_point, HookPoint) else hook_point
        if hp in self._hooks:
            self._hooks[hp] = [(p, h) for p, h in self._hooks[hp] if h is not handler]
    
    def list_hooks(self, hook_point: Optional[str] = None) -> List[str]:
        if hook_point:
            hp = hook_point.value if isinstance(hook_point, HookPoint) else hook_point
            return [h for _, h in self._hooks.get(hp, [])]
        return list(self._hooks.keys())
    
    def trigger(self, hook_point: str, *args, **kwargs) -> List[Any]:
        hp = hook_point.value if isinstance(hook_point, HookPoint) else hook_point
        results = []
        for _, handler in self._hooks.get(hp, []):
            try:
                results.append(handler(*args, **kwargs))
            except Exception as e:
                logger.error(f"Hook {hp} failed: {e}")
        return results
    
    def clear(self):
        self._hooks.clear()
