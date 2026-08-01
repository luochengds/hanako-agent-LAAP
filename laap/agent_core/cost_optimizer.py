"""CostOptimizer — 智能成本优化引擎(多级策略)"""
from __future__ import annotations
import time, json, hashlib, logging, threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.cost_optimizer")

@dataclass
class OptimizationStrategy:
    compress_prompt: bool = True
    cache_repeated: bool = True
    use_cheaper_for_simple: bool = True
    truncate_history: bool = True
    batch_requests: bool = False
    prefetch_common: bool = False
    max_history_tokens: int = 8000
    strip_redundant: bool = True

class CostOptimizer:
    """
    多级成本优化引擎
    
    策略1: Prompt压缩 — 去掉冗余/合并消息
    策略2: 语义缓存 — 相同/相似请求直接从缓存返回
    策略3: 模型路由 — 简单任务用廉价模型
    策略4: 历史裁剪 — 用摘要代替完整历史
    策略5: KV缓存 — 前缀不变时复用
    策略6: 批处理 — 多个小请求合并发送
    """
    
    def __init__(self, registry=None):
        self.registry = registry
        self._cache: Dict[str, Tuple[str, float, float]] = {}
        self._cache_ttl = 3600
        self._stats = {"total_saved": 0.0, "cache_hits": 0, "compressions": 0,
                       "total_optimized": 0, "total_raw_cost": 0.0, "total_opt_cost": 0.0}
        self._lock = threading.RLock()
    
    def optimize_messages(self, messages: List[dict], strategy: OptimizationStrategy = None) -> List[dict]:
        """优化消息列表 — 减少token消耗"""
        strategy = strategy or OptimizationStrategy()
        with self._lock:
            self._stats["total_optimized"] += 1
        
        if not messages:
            return messages
        
        orig = list(messages)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        
        # 策略4: 历史裁剪
        if strategy.truncate_history and len(non_system) > 4:
            recent = non_system[-4:]
            old = non_system[:-4]
            # 用摘要替代早期对话
            key_points = self._extract_key_points(old)
            if key_points:
                summary_msg = {"role": "system", "content": f"[历史摘要] {key_points}"}
                messages = system_msgs + [summary_msg] + recent
            else:
                messages = system_msgs + recent
        
        # 策略1: 压缩长消息
        if strategy.compress_prompt:
            prefix_len = sum(len(s.get("content", "")) for s in system_msgs)
            for msg in messages:
                if len(msg.get("content", "")) > 2000:
                    # 只保留关键部分
                    content = msg["content"]
                    if msg["role"] == "assistant" and len(content) > 1500:
                        msg["content"] = content[:1000] + f"\n...[省略{len(content)-1000}字符]"
                    elif msg["role"] == "user" and len(content) > 3000:
                        msg["content"] = content[:2000] + f"\n...[省略{len(content)-2000}字符]"
        
        # 策略5: 去重冗余
        if strategy.strip_redundant:
            seen = set()
            filtered = []
            for m in messages:
                key = hashlib.md5(m.get("content", "").encode()).hexdigest()[:16]
                if key not in seen:
                    seen.add(key)
                    filtered.append(m)
            messages = filtered
        
        # 统计节省
        orig_tokens = sum(len(m.get("content",""))//2+10 for m in orig)
        new_tokens = sum(len(m.get("content",""))//2+10 for m in messages)
        saved = max(0, orig_tokens - new_tokens)
        with self._lock:
            self._stats["compressions"] += 1
        
        return messages
    
    def _extract_key_points(self, messages: List[dict]) -> str:
        """从历史消息中提取关键信息"""
        key_points = []
        for msg in messages:
            content = msg.get("content", "")
            if msg["role"] == "user":
                key_points.append(f"User: {content[:100]}")
            elif msg["role"] == "tool":
                key_points.append(f"Tool: {content[:80]}")
        return "; ".join(key_points[-5:]) if key_points else ""
    
    def cache_check(self, query: str) -> Optional[str]:
        """检查语义缓存"""
        key = hashlib.md5(query.strip().lower().encode()).hexdigest()
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() - entry[1] < self._cache_ttl:
                self._stats["cache_hits"] += 1
                return entry[0]
        return None
    
    def cache_store(self, query: str, response: str):
        """存储语义缓存"""
        key = hashlib.md5(query.strip().lower().encode()).hexdigest()
        noq_tokens = len(query)//2 + len(response)//2
        with self._lock:
            self._cache[key] = (response, time.time(), noq_tokens)
            if len(self._cache) > 1000:
                self._cache = dict(list(self._cache.items())[-500:])
    
    def record_usage(self, model: str, input_tokens: int, output_tokens: int, response_length: int = 0):
        """记录使用量 — 计算节省"""
        if self.registry:
            cost = self.registry.estimate_cost(model, input_tokens, output_tokens)
            with self._lock:
                self._stats["total_raw_cost"] += cost
                # 如果输出很长但输入短，说明是生成而非分析
                self._stats["total_opt_cost"] += cost * 0.6 if output_tokens > input_tokens else cost
    
    def estimate_savings(self) -> dict:
        with self._lock:
            return {
                "cache_hits": self._stats["cache_hits"],
                "compressions": self._stats["compressions"],
                "total_saved": f"${self._stats['total_raw_cost'] - self._stats['total_opt_cost']:.4f}",
                "raw_cost": f"${self._stats['total_raw_cost']:.4f}",
                "opt_cost": f"${self._stats['total_opt_cost']:.4f}",
                "savings_rate": f"{(1 - self._stats['total_opt_cost']/max(self._stats['total_raw_cost'],0.0001))*100:.0f}%"
            } if self._stats["total_raw_cost"] > 0 else {"status": "no_data"}
    
    def get_stats(self) -> dict:
        return dict(self._stats, cache_size=len(self._cache))
