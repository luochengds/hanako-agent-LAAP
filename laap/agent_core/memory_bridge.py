"""
Memory Bridge — 将智能体与分层记忆引擎连接
"""
from __future__ import annotations
import time, json, logging
from typing import Any, Callable, Dict, List, Optional
from laap.engine.memory.working import WorkingMemory
from laap.engine.memory.episodic import EpisodicMemory, Episode, EpisodeType, EmotionalValence
from laap.engine.memory.semantic import SemanticMemory, RelationType
from laap.engine.memory.forgetting import EbbinghausForgettingCurve

logger = logging.getLogger("agent_core.memory_bridge")

class MemoryBridge:
    """智能体 <-> 记忆引擎 桥接器"""
    
    def __init__(self, memory_manager=None):
        self.working = WorkingMemory(capacity=20)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.forgetting = EbbinghausForgettingCurve()
        self._session_id: str = ""
        self._memory_manager = memory_manager
    
    def remember_interaction(self, user_input: str, agent_response: str, importance: float = 0.5):
        """记录一次交互到情景记忆"""
        self.episodic.create_episode(
            ep_type=EpisodeType.INTERACTION,
            summary=f"User: {user_input[:100]}",
            content={"user": user_input, "agent": agent_response},
            importance=importance,
            tags=["interaction"],
        )
        self.working.store(f"Q: {user_input[:50]}", source="user")
        self.working.store(f"A: {agent_response[:50]}", source="agent")
    
    def remember_fact(self, fact: str, importance: float = 0.6):
        """记忆一个事实到语义记忆"""
        cid = self.semantic.store_concept(fact[:50], fact, source="user")
        self.working.store(fact[:100], source="learning")
        return cid
    
    def search_memory(self, query: str, top_k: int = 5) -> Dict:
        """搜索所有记忆层次"""
        # 工作记忆
        working = [{"content": c.content, "weight": c.attention_weight}
                  for c in self.working._store.get_all() 
                  if query.lower() in str(c.content).lower()]
        
        # 情景记忆
        episodic = [e.to_dict() for e in self.episodic.find_similar(query, n=top_k)]
        
        # 语义记忆
        semantic = self.semantic.get_context(query)
        
        return {
            "working_memory": working[:top_k],
            "episodic_memory": episodic,
            "semantic_memory": semantic,
        }
    
    def get_recent_context(self, n: int = 5) -> str:
        """获取最近的上下文摘要"""
        recent = self.episodic.recall_recent(n)
        lines = []
        for ep in recent:
            age_hours = (time.time() - ep.timestamp) / 3600
            recall = self.forgetting.recall_probability(
                t_hours=age_hours, importance=ep.importance, recall_count=ep.importance
            )
            if recall > 0.2:
                lines.append(f"[{ep.timestamp:.0f}] {ep.summary[:80]}")
        return "\n".join(lines) if lines else "（无近期记忆）"
    
    def store(self, content: str, metadata: dict = None):
        """Store content in memory (compatibility API)"""
        if self._memory_manager is not None:
            return self._memory_manager.store(content, metadata or {})
        self.remember_fact(content[:200], importance=metadata.get("importance", 0.5) if metadata else 0.5)
        return {"id": "mem-" + str(int(time.time())), "content": content[:100]}
    
    def retrieve(self, mem_id: str):
        """Retrieve memory by ID (compatibility API)"""
        if self._memory_manager is not None:
            return self._memory_manager.retrieve(mem_id)
        # Search across all memory layers
        for ep in self.episodic._episodes:
            if getattr(ep, "id", "") == mem_id:
                return ep.to_dict()
        return None
    
    def search(self, query: str, top_k: int = 5) -> list:
        """Search memory (compatibility API)"""
        if self._memory_manager is not None:
            if hasattr(self._memory_manager, 'search'):
                result = self._memory_manager.search(query, top_k)
                if hasattr(result, '__await__'):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            result = asyncio.run_coroutine_threadsafe(result, loop).result(timeout=10)
                        else:
                            result = asyncio.run(result)
                    except RuntimeError:
                        result = asyncio.run(result)
                return result
            return []
        result = self.search_memory(query, top_k)
        items = []
        for layer in ["working_memory", "episodic_memory", "semantic_memory"]:
            items.extend(result.get(layer, []))
        return items[:top_k]
    
    def delete(self, mem_id: str) -> bool:
        """Delete memory by ID (compatibility API)"""
        if self._memory_manager is not None:
            if hasattr(self._memory_manager, 'delete'):
                result = self._memory_manager.delete(mem_id)
                if hasattr(result, '__await__'):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            result = asyncio.run_coroutine_threadsafe(result, loop).result(timeout=10)
                        else:
                            result = asyncio.run(result)
                    except RuntimeError:
                        result = asyncio.run(result)
                return result
            return True
        return True
    
    def list_recent(self, limit: int = 10) -> list:
        """List recent memories (compatibility API)"""
        if self._memory_manager is not None and hasattr(self._memory_manager, 'list_recent'):
            return self._memory_manager.list_recent(limit)
        recent = self.episodic.recall_recent(limit)
        return [e.to_dict() for e in recent]
    
    def get_context_string(self, query: str) -> str:
        """Get context string from memory (compatibility API)"""
        if self._memory_manager is not None and hasattr(self._memory_manager, 'get_context_string'):
            return self._memory_manager.get_context_string(query)
        return self.get_recent_context(5)
    
    def get_stats(self) -> dict:
        return {
            "working_size": self.working._store.size(),
            "episodic_count": len(self.episodic._episodes),
            "semantic_nodes": len(self.semantic.graph._nodes),
        }
