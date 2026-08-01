"""ConversationLoop — 完整ReAct对话循环（深度版）"""
from __future__ import annotations
import time, json, logging, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Generator

logger = logging.getLogger("agent_core.conversation_loop")

class TurnPhase(str, Enum):
    STARTED = "started"; THINKING = "thinking"; TOOL_CALL = "tool_call"
    OBSERVING = "observing"; COMPLETED = "completed"; FAILED = "failed"

@dataclass
class TurnRecord:
    turn_id: int = 0; user_msg: str = ""; assistant_msg: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    tokens_in: int = 0; tokens_out: int = 0
    duration_ms: float = 0.0; phase: TurnPhase = TurnPhase.STARTED
    error: str = ""; created_at: float = field(default_factory=time.time)

class ConversationLoop:
    def __init__(self, agent=None, max_iterations: int = 20, max_tokens: int = 128000):
        self.agent = agent
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.history: List[TurnRecord] = []
        self._callbacks: Dict[str, List[Callable]] = {}
    
    def on(self, event: str, cb: Callable):
        self._callbacks.setdefault(event, []).append(cb)
    
    def _emit(self, event: str, data=None):
        for cb in self._callbacks.get(event, []):
            try: cb(data)
            except: pass
    
    def process(self, user_msg: str) -> str:
        turn = TurnRecord(turn_id=len(self.history)+1, user_msg=user_msg)
        self._emit("turn_start", turn)
        start = time.time()
        
        # Add user message
        self.agent.context.add(Role.USER, user_msg)
        self._stats["total_turns"] += 1
        
        for iteration in range(self.max_iterations):
            turn.phase = TurnPhase.THINKING
            self._emit("thinking", {"iteration": iteration, "user_msg": user_msg})
            
            # Check token budget
            if self.agent.context.total_tokens() > self.max_tokens * 0.8:
                self.agent.context.messages = self.agent.compressor.compress(self.agent.context.get_messages())
            
            # Call LLM
            response = self.agent.llm.chat(
                self.agent.context.get_messages(),
                tools=self.agent.tool_mgr.get_openai_tools() if self.agent.config.enable_tools else []
            )
            turn.tokens_in += response.usage.get("prompt_tokens", 0)
            turn.tokens_out += response.usage.get("completion_tokens", 0)
            
            # Handle tool call or direct response
            if not response.content and response.finish_reason == "tool_calls":
                turn.phase = TurnPhase.TOOL_CALL
                result = self.agent._exec_tool(user_msg)
                turn.tool_calls.append({"tool": "auto", "result": result.output[:200]})
                self._stats["total_tool_calls"] += 1
                self._emit("tool_call", {"tool": "auto", "result": result.output[:100]})
                
                turn.phase = TurnPhase.OBSERVING
                obs = result.output or str(result.data or "")
                self.agent.context.add(Role.TOOL, obs, tool_call_id=f"call_{iteration}", name="tool")
            else:
                self.agent.context.add(Role.ASSISTANT, response.content)
                if self.agent.memory:
                    self.agent.memory.remember_interaction(user_msg, response.content)
                turn.assistant_msg = response.content
                turn.phase = TurnPhase.COMPLETED
                turn.duration_ms = round((time.time() - start) * 1000, 2)
                self.history.append(turn)
                self._emit("turn_complete", turn)
                return response.content
        
        # Max iterations reached
        fallback = f"（已达{self.max_iterations}次迭代上限）"
        self.agent.context.add(Role.ASSISTANT, fallback)
        turn.assistant_msg = fallback
        turn.phase = TurnPhase.COMPLETED
        turn.duration_ms = round((time.time() - start) * 1000, 2)
        self.history.append(turn)
        return fallback
    
    def get_stats(self) -> dict:
        c = sum(1 for t in self.history if t.phase == TurnPhase.COMPLETED)
        return {"total_turns": len(self.history), "completed": c,
                "total_tokens_in": sum(t.tokens_in for t in self.history),
                "total_tokens_out": sum(t.tokens_out for t in self.history),
                "avg_duration_ms": round(sum(t.duration_ms for t in self.history)/max(len(self.history),1), 2)}
