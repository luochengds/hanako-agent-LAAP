"""laap/agent_core/llm_provider.py — 已迁移到 laap.llm (shim)

本文件原是旧版 LLM 抽象层 (4 provider + TokenBucket + LLMConfig/LLMResponse)。
现已统一到 `laap.llm.provider` (27 provider) + `laap.llm.rate_limiter` (TokenBucket)。

向后兼容:
    from laap.agent_core.llm_provider import LLMProvider, LLMConfig, LLMResponse, LLMFactory
    仍然可用, 但实际指向 laap.llm 的实现。

迁移指南:
    推荐: from laap.llm import LLMProvider, LLMFactory, Message, ToolDef
          from laap.llm.rate_limiter import TokenBucket
          from laap.llm.router import ModelRouter
          from laap.llm.registry import ModelRegistry
"""
from __future__ import annotations
import warnings
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

# ── 触发 DeprecationWarning ─────────────────────────────────────
warnings.warn(
    "laap.agent_core.llm_provider 已统一到 laap.llm。"
    "请改用 `from laap.llm import LLMProvider, LLMFactory, Message, ToolDef`。"
    "限流器用 `from laap.llm.rate_limiter import TokenBucket`，"
    "路由器用 `from laap.llm.router import ModelRouter`。",
    DeprecationWarning,
    stacklevel=2,
)

# ── 从 laap.llm re-export ───────────────────────────────────────
from laap.llm.provider import (
    LLMProvider as _NewLLMProvider,
    Message,
    ToolDef,
    StreamEvent,
    MODEL_REGISTRY,
    get_provider,
)
from laap.llm.factory import LLMFactory
from laap.llm.rate_limiter import TokenBucket


# ── LLMConfig — 旧版数据类 (保留以兼容调用方) ───────────────────
@dataclass
class LLMConfig:
    """旧版 LLM 配置 (保留兼容, 推荐用 laap.llm.LLMProvider 构造参数)。"""
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    api_base: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    timeout: int = 60


# ── LLMResponse — 旧版响应类 (适配新版 Message) ─────────────────
@dataclass
class LLMResponse:
    """旧版 LLM 响应 (保留兼容, 推荐用 laap.llm.Message)。

    新版 LLMProvider.chat() 返回 Message 对象, 此类提供 from_message() 适配。
    """
    content: str = ""
    finish_reason: str = "stop"
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0
    tool_calls: List[Dict] = field(default_factory=list)

    @classmethod
    def from_message(cls, msg: Message, latency_ms: float = 0.0) -> "LLMResponse":
        """从新版 Message 适配为旧版 LLMResponse。"""
        return cls(
            content=msg.content or "",
            finish_reason="tool_calls" if msg.tool_calls else "stop",
            usage={},
            model=getattr(msg, "model", ""),
            latency_ms=latency_ms,
            tool_calls=msg.tool_calls or [],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "tool_calls": self.tool_calls,
        }


# ── LLMProvider — 旧版类 (委托给新版 LLMProvider) ───────────────
class LLMProvider(_NewLLMProvider):
    """旧版 LLMProvider (保留类名兼容, 实际继承新版 LLMProvider)。

    旧版 API:
        provider = LLMProvider(config=LLMConfig(provider="openai", ...))
        resp = provider.chat(messages_dict_list)  # 返回 LLMResponse

    新版 API (推荐):
        from laap.llm import LLMFactory
        provider = LLMFactory.get(model="gpt-4o")
        msg = provider.chat([Message.user("...")])  # 返回 Message

    兼容层:
        - 接受 LLMConfig 构造 (旧版风格)
        - chat() 接受 List[dict] 并转换为 List[Message]
        - chat() 返回 LLMResponse (通过 from_message 适配)
    """

    # 旧版 PROVIDERS 字典 (4 个, 保留兼容)
    PROVIDERS = {
        "openai": {"base_url": "https://api.openai.com/v1",
                   "models": ["gpt-4o", "gpt-4o-mini", "gpt-5.5"]},
        "deepseek": {"base_url": "https://api.deepseek.com/v1",
                     "models": ["deepseek-chat", "deepseek-v4-flash"]},
        "anthropic": {"base_url": "https://api.anthropic.com/v1",
                      "models": ["claude-opus-4-8", "claude-sonnet-4-5"]},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                       "models": ["*"]},
    }

    def __init__(self, config: Optional[LLMConfig] = None, **kwargs):
        if config is not None:
            # 旧版构造: LLMProvider(config=LLMConfig(...))
            import os
            api_key = config.api_key or os.environ.get(
                f"{config.provider.upper()}_API_KEY", "")
            super().__init__(
                model=config.model,
                api_key=api_key,
                base_url=config.api_base or None,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                **kwargs,
            )
            self._config = config
        else:
            # 新版构造: LLMProvider(model="...", api_key="...")
            super().__init__(**kwargs)
            self._config = None

    def chat(self, messages: List[Dict], tools=None, stream: bool = False) -> LLMResponse:
        """旧版 chat — 接受 dict 列表, 返回 LLMResponse。"""
        # dict → Message 转换
        if messages and isinstance(messages[0], dict):
            msg_objects = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    msg_objects.append(Message.system(content))
                elif role == "assistant":
                    msg_objects.append(Message.assistant(content))
                elif role == "tool":
                    msg_objects.append(Message.tool_result(
                        m.get("tool_call_id", ""), content))
                else:
                    msg_objects.append(Message.user(content))
        else:
            msg_objects = messages

        # 调用新版 chat
        import time
        t0 = time.monotonic()
        result_msg = super().chat(msg_objects, tools=tools)
        latency = (time.monotonic() - t0) * 1000

        # Message → LLMResponse 适配
        return LLMResponse.from_message(result_msg, latency_ms=latency)

    def stream_chat(self, messages: List[Dict], tools=None):
        """旧版 stream_chat — yield str (兼容旧版 API)。"""
        if messages and isinstance(messages[0], dict):
            msg_objects = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    msg_objects.append(Message.system(content))
                elif role == "assistant":
                    msg_objects.append(Message.assistant(content))
                else:
                    msg_objects.append(Message.user(content))
        else:
            msg_objects = messages

        # 新版 chat_stream yield StreamEvent, 旧版期望 str
        for event in super().chat_stream(msg_objects, tools=tools):
            if event.type == "token" and event.content:
                yield event.content

    def on(self, event: str, callback):
        """旧版事件回调 (桩, 新版用 StreamEvent)。"""
        pass

    def get_stats(self) -> dict:
        return getattr(self, "metrics", {})


# ── 旧版 LLMFactory (委托给新版) ────────────────────────────────
# 已从 laap.llm.factory 导入 LLMFactory, 旧版静态方法 create() 兼容
def _legacy_create(provider: str = "openai", model: str = "",
                   api_key: str = "", **kwargs) -> LLMProvider:
    """旧版 LLMFactory.create() — 静态方法兼容。"""
    if not model:
        model_map = {
            "openai": "gpt-4o", "deepseek": "deepseek-chat",
            "anthropic": "claude-sonnet-4-5", "openrouter": "openrouter/auto",
        }
        model = model_map.get(provider, "gpt-4o")
    config = LLMConfig(provider=provider, model=model, api_key=api_key)
    return LLMProvider(config=config, **kwargs)


# 给 LLMFactory 添加旧版静态方法
LLMFactory.create = staticmethod(_legacy_create)


__all__ = [
    "LLMProvider", "LLMConfig", "LLMResponse", "LLMFactory",
    "TokenBucket", "Message", "ToolDef", "StreamEvent",
    "MODEL_REGISTRY", "get_provider",
]
