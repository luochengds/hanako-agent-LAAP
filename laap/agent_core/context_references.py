"""ContextReferences — 上下文引用管理"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ContextReference:
    source: str = ""; content: str = ""; relevance: float = 0.5
    timestamp: float = 0.0; metadata: Dict = field(default_factory=dict)

class ContextReferenceManager:
    def __init__(self):
        self._refs: List[ContextReference] = []
    def add(self, ref: ContextReference):
        self._refs.append(ref)
    def search(self, query: str, limit: int = 5) -> List[ContextReference]:
        q = query.lower()
        scored = [(r, r.relevance + (1 if q in r.content.lower() else 0)) for r in self._refs]
        return [r for r,_ in sorted(scored, key=lambda x: -x[1])[:limit]]
    def clear(self):
        self._refs.clear()
