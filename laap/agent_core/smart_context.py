"""SmartContext — 智能上下文管理(用最少信息达成最佳效果)"""
from __future__ import annotations
import json, logging, time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.smart_context")

class SmartContext:
    """
    智能上下文 — 在有限的token预算内保留最关键信息
    
    策略:
    - 最近交互: 必须保留(最后3轮)
    - 关键事实: 用户显式要求记住的
    - 任务上下文: 当前正在执行的任务相关
    - 情感/用户偏好: 隐含的历史信息
    """
    
    def __init__(self, max_tokens: int = 32000):
        self.max_tokens = max_tokens
        self._key_facts: Dict[str, str] = {}
        self._stats = {"optimizations": 0, "tokens_saved": 0}
    
    def add_fact(self, key: str, value: str):
        self._key_facts[key] = value
    
    def build(self, messages: List[dict], task: str = "") -> List[dict]:
        """构建最优上下文"""
        if not messages:
            return messages
        
        # 保留系统提示
        system = [m for m in messages if m.get("role") == "system"]
        
        # 保留最后3轮
        recent = messages[-6:] if len(messages) > 6 else messages
        
        # 添加关键事实
        if self._key_facts:
            facts = "; ".join(f"{k}: {v[:50]}" for k, v in self._key_facts.items())
            fact_msg = {"role": "system", "content": f"[重要事实] {facts}"}
            result = system + [fact_msg] + recent
        else:
            result = system + recent
        
        self._stats["optimizations"] += 1
        saved = max(0, len(json.dumps(messages, ensure_ascii=False)) - len(json.dumps(result, ensure_ascii=False)))
        self._stats["tokens_saved"] += saved // 2
        
        return result
    
    def get_stats(self) -> dict:
        return dict(self._stats, facts=len(self._key_facts))
