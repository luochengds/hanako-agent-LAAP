"""Context Plugin — 上下文增强插件"""
from __future__ import annotations
from typing import Any, Dict


class ContextPlugin:
    """上下文插件 — 处理并增强对话上下文"""
    
    def __init__(self):
        self.name = "context_engine"
        self.version = "1.0.0"
        self._metadata: Dict[str, Any] = {}
    
    def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(context) if isinstance(context, dict) else {"data": str(context)}
        result["processed"] = True
        return result
    
    def enhance(self, context: Any) -> Any:
        if isinstance(context, dict):
            result = dict(context)
        else:
            result = {"data": str(context), "original": context}
        result["enhanced"] = True
        result["metadata"] = self._metadata
        return result
