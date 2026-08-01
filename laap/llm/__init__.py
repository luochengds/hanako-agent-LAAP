"""LAAP — LLM 抽象层 (唯一入口)

统一对外 API:
    from laap.llm import LLMFactory, LLMProvider, Message, ToolDef

子模块:
    - provider.py:         LLMProvider 基类 + 27 provider + Message/ToolDef/StreamEvent
    - engine.py:           简化版 LLMEngine 抽象 (LLMEngine / OllamaEngine / RemoteFallbackEngine / TokenUsage)
    - factory.py:          LLMFactory 工厂 (自动检测 + 多 provider fallback)
    - discovery.py:        ModelDiscovery 模型发现 (/v1/models 端点扫描)
    - credential_pool.py:  CredentialPool 凭证池 (多 key 轮换 + 别名 + 配额)
    - registry.py:         ModelRegistry 统一注册表 (88+ 模型, 含成本/tier)
    - router.py:           ModelRouter 智能路由 (4 复杂度等级)
    - rate_limiter.py:     RateLimiter 限流器 (per-provider TokenBucket)
"""
from laap.llm.engine import (
    LLMEngine, OllamaEngine, RemoteFallbackEngine, MockLLMEngine,
    TokenUsage, estimate_tokens,
)
from laap.llm.provider import (
    LLMProvider, OpenAIProvider, AnthropicProvider, GoogleProvider,
    DeepSeekProvider, XAIProvider, MistralProvider, CohereProvider,
    PerplexityProvider, OpenRouterProvider, TogetherProvider,
    GroqProvider, AzureProvider, OllamaProvider, CustomProvider,
    OpenAICompatProvider, OmniRouteProvider,
    Message, ToolDef, StreamEvent,
    MODEL_REGISTRY, MODEL_LABELS, get_provider,
)
from laap.llm.factory import LLMFactory, factory
from laap.llm.discovery import ModelDiscovery, discovery
from laap.llm.credential_pool import CredentialPool, credential_pool
from laap.llm.registry import (
    ModelTier, ModelEntry, ModelRegistry, get_registry, get_model,
)
from laap.llm.router import (
    ModelRouter, get_router, route_task, classify_task,
    is_omniroute_available, reset_omniroute_cache,
)
from laap.llm.rate_limiter import (
    TokenBucket, RateLimiter, get_rate_limiter, acquire_for_provider,
)

__all__ = [
    # Engine 抽象
    "LLMEngine", "OllamaEngine", "RemoteFallbackEngine", "MockLLMEngine",
    "TokenUsage", "estimate_tokens",
    # Provider 类
    "LLMProvider", "OpenAICompatProvider",
    "OpenAIProvider", "AnthropicProvider", "GoogleProvider",
    "DeepSeekProvider", "XAIProvider", "MistralProvider", "CohereProvider",
    "PerplexityProvider", "OpenRouterProvider", "TogetherProvider",
    "GroqProvider", "AzureProvider", "OllamaProvider", "CustomProvider",
    "OmniRouteProvider",  # 🆓 永久免费 LLM 路由网关
    # 数据类型
    "Message", "ToolDef", "StreamEvent",
    # 注册表
    "MODEL_REGISTRY", "MODEL_LABELS",
    "ModelTier", "ModelEntry", "ModelRegistry", "get_registry", "get_model",
    # 工厂
    "LLMFactory", "factory", "get_provider",
    # 发现
    "ModelDiscovery", "discovery",
    # 凭证池
    "CredentialPool", "credential_pool",
    # 路由
    "ModelRouter", "get_router", "route_task", "classify_task",
    "is_omniroute_available", "reset_omniroute_cache",  # 🆓 OmniRoute 探测
    # 限流
    "TokenBucket", "RateLimiter", "get_rate_limiter", "acquire_for_provider",
]
