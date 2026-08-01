"""ConversationCompression — 对话压缩策略"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional

class ConversationCompression:
    STRATEGIES = {"drop_oldest": 0, "summarize_middle": 1, "keep_key": 2}
    def compress(self, messages: List[dict], strategy: str = "drop_oldest", max_tokens: int = 32000) -> List[dict]:
        if strategy == "drop_oldest":
            while self._count_tokens(messages) > max_tokens and len(messages) > 4:
                messages.pop(1)
        elif strategy == "keep_key":
            system = [m for m in messages if m.get("role") == "system"]
            recent = messages[-4:]
            return system + recent
        return messages
    def _count_tokens(self, messages: List[dict]) -> int:
        return sum(len(m.get("content",""))//2+10 for m in messages)
