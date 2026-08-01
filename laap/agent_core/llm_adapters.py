"""laap/agent_core/llm_adapters.py — 已废弃 (shim)

本文件原是旧版 Anthropic/Gemini 适配器 (urllib 简陋实现)。
现已统一到:
    - laap.llm.provider.AnthropicProvider (完整实现, anthropic SDK)
    - laap.llm.provider.GoogleProvider (Gemini OpenAI 兼容端点)

向后兼容:
    from laap.agent_core.llm_adapters import AnthropicAdapter, GeminiAdapter, AdapterRegistry
    仍然可用, 但会委托到 laap.llm 的实现。
"""
from __future__ import annotations
import warnings
from typing import Any, Dict, List, Optional

warnings.warn(
    "laap.agent_core.llm_adapters 已废弃。"
    "Anthropic/Gemini 已在 laap.llm.provider 中有完整实现。"
    "请改用 `from laap.llm import AnthropicProvider, GoogleProvider`。",
    DeprecationWarning,
    stacklevel=2,
)

from laap.llm.provider import (
    AnthropicProvider, GoogleProvider, Message, LLMProvider,
)


class AnthropicAdapter:
    """旧版 AnthropicAdapter — 委托给 laap.llm.AnthropicProvider。"""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-5"):
        import os
        self._provider = AnthropicProvider(
            model=model,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    def chat(self, messages: List[Dict], **kwargs) -> str:
        """旧版 chat — 接受 dict 列表, 返回字符串。"""
        msg_objects = [Message.user(m.get("content", "")) if m.get("role") == "user"
                       else Message.system(m.get("content", "")) if m.get("role") == "system"
                       else Message.assistant(m.get("content", ""))
                       for m in messages]
        result = self._provider.chat(msg_objects)
        return result.content or ""


class GeminiAdapter:
    """旧版 GeminiAdapter — 委托给 laap.llm.GoogleProvider。"""

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash"):
        import os
        self._provider = GoogleProvider(
            model=model,
            api_key=api_key or os.environ.get("GOOGLE_API_KEY", ""),
        )

    def chat(self, messages: List[Dict], **kwargs) -> str:
        """旧版 chat — 接受 dict 列表, 返回字符串。"""
        msg_objects = [Message.user(m.get("content", "")) if m.get("role") == "user"
                       else Message.system(m.get("content", "")) if m.get("role") == "system"
                       else Message.assistant(m.get("content", ""))
                       for m in messages]
        result = self._provider.chat(msg_objects)
        return result.content or ""


class AdapterRegistry:
    """旧版 AdapterRegistry — 注册中心, 委托给新版 Provider。"""

    def __init__(self):
        self._adapters: Dict[str, Any] = {}

    def register(self, name: str, adapter: Any):
        self._adapters[name] = adapter

    def get(self, name: str) -> Optional[Any]:
        return self._adapters.get(name)

    def chat(self, name: str, messages: List[Dict], **kwargs) -> str:
        adapter = self._adapters.get(name)
        if adapter is None:
            return f"[Adapter '{name}' not found]"
        if hasattr(adapter, "chat"):
            return adapter.chat(messages, **kwargs)
        return ""


__all__ = ["AnthropicAdapter", "GeminiAdapter", "AdapterRegistry"]
