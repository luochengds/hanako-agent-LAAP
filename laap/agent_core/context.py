"""
LAAP Agent Context — 智能体上下文管理
管理对话窗口、消息历史、Token计数
"""
from __future__ import annotations
import time, json, logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.context")

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass
class Message:
    role: Role = Role.USER
    content: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
    metadata: Dict = field(default_factory=dict)
    
    def __getitem__(self, key):
        """Dict-like access for test compatibility"""
        return getattr(self, key)
    
    def get(self, key, default=None):
        """Dict-like get for test compatibility"""
        return getattr(self, key, default)
    
    def to_dict(self) -> dict:
        return {"role": self.role.value, "content": self.content,
                "tool_calls": self.tool_calls, "tool_call_id": self.tool_call_id,
                "name": self.name, "timestamp": self.timestamp}

class Context:
    """上下文窗口管理 — 滑动窗口 + Token预算控制"""
    
    def __init__(self, max_tokens: int = 128000, max_messages: int = 200, token_counter=None):
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self._messages: List[Message] = []
        self.system_prompt: str = ""
        self._token_counts: List[int] = []
        self._token_counter = token_counter or self._estimate_tokens
    
    @property
    def messages(self):
        """Return messages for compatibility (tests expect dict-like access)"""
        return self._messages
    
    @messages.setter
    def messages(self, val):
        self._messages = val
    
    def set_system(self, prompt: str):
        self.system_prompt = prompt
    
    def add(self, role: Role, content: str, tool_calls: List = None,
            tool_call_id: str = "", name: str = ""):
        msg = Message(role=role, content=content, tool_calls=tool_calls or [],
                     tool_call_id=tool_call_id, name=name)
        msg.token_count = self._token_counter(content)
        self._messages.append(msg)
        self._token_counts.append(msg.token_count)
        self._trim()
    
    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 2 + len(text.split())
    
    def _trim(self):
        while len(self._messages) > self.max_messages:
            self._messages.pop(1) if len(self._messages) > 2 else self._messages.pop(0)
            if self._token_counts:
                self._token_counts.pop(0)
        total = sum(self._token_counts) + (self._token_counter(self.system_prompt) if self.system_prompt else 0)
        while total > self.max_tokens and len(self._messages) > 2:
            removed = self._messages.pop(1)
            if self._token_counts:
                t = self._token_counts.pop(0)
                total -= t
    
    def get_messages(self, include_system: bool = True) -> List[dict]:
        result = []
        if include_system and self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in self.messages:
            if msg.role == Role.TOOL:
                result.append({"role": "tool", "content": msg.content,
                              "tool_call_id": msg.tool_call_id, "name": msg.name})
            elif msg.tool_calls:
                result.append({"role": "assistant", "content": msg.content or None,
                              "tool_calls": msg.tool_calls})
            elif msg.role == Role.ASSISTANT:
                result.append({"role": "assistant", "content": msg.content})
            elif msg.role == Role.USER:
                result.append({"role": "user", "content": msg.content})
            elif msg.role == Role.SYSTEM:
                result.append({"role": "system", "content": msg.content})
        return result
    
    def get_llm_messages(self, include_system: bool = True) -> List[Message]:
        """Return Message objects for providers that call ``to_dict()``.

        ``get_messages`` remains dict-compatible for existing compressors and
        tests; provider calls must use this typed view.
        """
        result: List[Message] = []
        if include_system and self.system_prompt:
            result.append(Message(role=Role.SYSTEM, content=self.system_prompt))
        for raw in self._messages:
            if isinstance(raw, Message):
                result.append(raw)
                continue
            if isinstance(raw, dict):
                role = raw.get("role", Role.USER)
                try:
                    role = Role(role)
                except ValueError:
                    role = Role.USER
                result.append(Message(
                    role=role,
                    content=raw.get("content", "") or "",
                    tool_calls=raw.get("tool_calls", []) or [],
                    tool_call_id=raw.get("tool_call_id", "") or "",
                    name=raw.get("name", "") or "",
                ))
        return result

    def total_tokens(self) -> int:
        return sum(self._token_counts) + (self._token_counter(self.system_prompt) if self.system_prompt else 0)
    
    def token_count(self) -> int:
        """Test-compatible token count method"""
        return self.total_tokens()
    
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None
    
    def clear(self, preserve_system: bool = False):
        if preserve_system:
            system_msgs = [m for m in self._messages if m.role == Role.SYSTEM]
            self._messages.clear()
            self._token_counts.clear()
            for msg in system_msgs:
                self._messages.append(msg)
        else:
            self._messages.clear()
            self._token_counts.clear()
    
    def add_message(self, role: str, content: str):
        """Add a message by string role name (compatibility API)"""
        role_map = {"system": Role.SYSTEM, "user": Role.USER, "assistant": Role.ASSISTANT, "tool": Role.TOOL}
        r = role_map.get(role.lower(), Role.USER)
        self.add(r, content)

    def add_system_message(self, content: str):
        """Add a system message (compatibility API)"""
        self.add(Role.SYSTEM, content)

    def trim(self):
        """Public trim method (compatibility API)"""
        self._trim()

    def to_dict(self) -> dict:
        return {"system_prompt": self.system_prompt[:100] if self.system_prompt else "",
                "messages": len(self.messages), "total_tokens": self.total_tokens()}
