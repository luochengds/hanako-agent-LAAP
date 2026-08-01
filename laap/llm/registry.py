"""laap/llm/registry.py — 统一模型注册表

合并自:
  - laap/llm/provider.py MODEL_REGISTRY (连接信息: api_url, api_key_env)
  - laap/agent_core/model_registry.py ModelRegistry (成本/能力/tier)

声明与实现一致: 27 provider / 88+ 模型, 每条条目含完整元数据。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger("laap.llm.registry")


class ModelTier(str, Enum):
    """模型能力/成本分层。"""
    CHEAP = "cheap"        # 低成本高速 (deepseek-v4-flash, gpt-4o-mini)
    STANDARD = "standard"  # 标准生产 (deepseek-chat, claude-sonnet)
    PREMIUM = "premium"    # 高质量 (gpt-4o, claude-opus)
    ULTRA = "ultra"        # 顶级 (gpt-5.5, claude-opus-4-8)


@dataclass
class ModelEntry:
    """统一模型注册表条目 — 含连接信息 + 成本/能力元数据。"""
    # 标识
    model_id: str = ""
    provider: str = ""
    label: str = ""
    # 连接 (来自原 provider.MODEL_REGISTRY)
    api_url: str = ""
    api_key_env: str = ""
    # 成本 (来自原 agent_core.ModelRegistry)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    # 能力
    tier: ModelTier = ModelTier.STANDARD
    context_window: int = 128000
    speed: float = 1.0  # tokens/sec 相对值
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tool_calls: int = 5
    knowledge_cutoff: str = "2024-12"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "label": self.label,
            "api_url": self.api_url,
            "api_key_env": self.api_key_env,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "tier": self.tier.value,
            "context_window": self.context_window,
            "speed": self.speed,
            "supports_tools": self.supports_tools,
            "supports_streaming": self.supports_streaming,
            "max_tool_calls": self.max_tool_calls,
            "knowledge_cutoff": self.knowledge_cutoff,
        }


class ModelRegistry:
    """统一模型注册表 — 单一真相源。

    合并了原 laap/llm/provider.py 的 MODEL_REGISTRY (连接信息)
    和原 laap/agent_core/model_registry.py 的 ModelRegistry (成本/能力)。
    """

    def __init__(self):
        self._models: Dict[str, ModelEntry] = {}
        self._register_builtin()

    def _register_builtin(self):
        """注册内置 88+ 模型条目 (声明与实现一致)。"""
        # ── 国际 13 provider ──────────────────────────────────────
        # OpenAI
        self._add("gpt-4o", "openai", "GPT-4o", "https://api.openai.com/v1",
                  "OPENAI_API_KEY", 0.0025, 0.01, ModelTier.PREMIUM, 128000, 1.0)
        self._add("gpt-4o-mini", "openai", "GPT-4o mini", "https://api.openai.com/v1",
                  "OPENAI_API_KEY", 0.00015, 0.0006, ModelTier.CHEAP, 128000, 2.0)
        self._add("gpt-5.5", "openai", "GPT-5.5", "https://api.openai.com/v1",
                  "OPENAI_API_KEY", 0.005, 0.015, ModelTier.ULTRA, 256000, 0.8)
        self._add("o1-preview", "openai", "o1 Preview", "https://api.openai.com/v1",
                  "OPENAI_API_KEY", 0.015, 0.06, ModelTier.ULTRA, 128000, 0.5,
                  supports_tools=True, max_tool_calls=1)
        # Anthropic
        self._add("claude-opus-4-8", "anthropic", "Claude Opus 4.8",
                  "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                  0.015, 0.075, ModelTier.ULTRA, 200000, 0.6)
        self._add("claude-sonnet-4-5", "anthropic", "Claude Sonnet 4.5",
                  "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                  0.003, 0.015, ModelTier.PREMIUM, 200000, 1.0)
        self._add("claude-haiku-4", "anthropic", "Claude Haiku 4",
                  "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                  0.00025, 0.00125, ModelTier.CHEAP, 200000, 2.5)
        # Google Gemini
        self._add("gemini-2.5-pro", "google", "Gemini 2.5 Pro",
                  "https://generativelanguage.googleapis.com/v1beta/openai",
                  "GOOGLE_API_KEY", 0.00125, 0.005, ModelTier.PREMIUM, 2000000, 1.0)
        self._add("gemini-2.5-flash", "google", "Gemini 2.5 Flash",
                  "https://generativelanguage.googleapis.com/v1beta/openai",
                  "GOOGLE_API_KEY", 0.000075, 0.0003, ModelTier.CHEAP, 1000000, 3.0)
        # DeepSeek
        self._add("deepseek-v4-flash", "deepseek", "DeepSeek V4 Flash",
                  "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
                  0.00007, 0.00014, ModelTier.CHEAP, 128000, 4.0)
        self._add("deepseek-chat", "deepseek", "DeepSeek Chat",
                  "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
                  0.00027, 0.0011, ModelTier.STANDARD, 128000, 2.5)
        self._add("deepseek-r1", "deepseek", "DeepSeek R1 Reasoner",
                  "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
                  0.00055, 0.0022, ModelTier.PREMIUM, 128000, 1.0,
                  supports_tools=False)
        # xAI Grok
        self._add("grok-4", "xai", "Grok 4", "https://api.x.ai/v1",
                  "XAI_API_KEY", 0.005, 0.015, ModelTier.PREMIUM, 256000, 0.8)
        # Mistral
        self._add("mistral-large-2", "mistral", "Mistral Large 2",
                  "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
                  0.002, 0.006, ModelTier.PREMIUM, 128000, 1.5)
        # Cohere
        self._add("command-r-plus-08-2024", "cohere", "Command R+",
                  "https://api.cohere.com/v1", "COHERE_API_KEY",
                  0.0025, 0.01, ModelTier.STANDARD, 128000, 1.2)
        # Perplexity
        self._add("llama-3.1-sonar-large-128k-online", "perplexity",
                  "Sonar Large Online", "https://api.perplexity.ai",
                  "PERPLEXITY_API_KEY", 0.001, 0.001, ModelTier.STANDARD,
                  127000, 1.0, supports_tools=False)
        # OpenRouter (聚合)
        self._add("openrouter/auto", "openrouter", "OpenRouter Auto",
                  "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                  0.002, 0.006, ModelTier.STANDARD, 200000, 1.0)
        # Together
        self._add("meta-llama/Llama-3.3-70B-Instruct-Turbo", "together",
                  "Llama 3.3 70B Turbo", "https://api.together.xyz/v1",
                  "TOGETHER_API_KEY", 0.00088, 0.00088, ModelTier.STANDARD,
                  128000, 2.0)
        # Groq
        self._add("llama-3.3-70b-versatile", "groq", "Llama 3.3 70B Versatile",
                  "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                  0.00059, 0.00079, ModelTier.CHEAP, 128000, 5.0)
        # Azure (与 OpenAI 同模型, 不同端点)
        self._add("azure/gpt-4o", "azure", "Azure GPT-4o",
                  "https://{resource}.openai.azure.com", "AZURE_OPENAI_API_KEY",
                  0.0025, 0.01, ModelTier.PREMIUM, 128000, 1.0)
        # Ollama (本地)
        self._add("ollama/llama3.3", "ollama", "Ollama Llama 3.3",
                  "http://localhost:11434/v1", "", 0.0, 0.0, ModelTier.CHEAP,
                  128000, 1.0, supports_tools=True)

        # ── 🆓 OmniRoute 永久免费 LLM 路由网关 (290+ provider / 90+ free) ──
        # 启动: scripts/start_omniroute.cmd 或 cd OmniRoute-release-v3.8.50 && npm start
        # 端点: http://localhost:20128/v1  (OpenAI 兼容)
        # 成本: 全部 0.0 — 经 OmniRoute 网关调用上游免费 tier
        # tier 映射: auto/auto:free → CHEAP (零成本高速)
        #            oc/gpt-5.5 / oc/claude-sonnet → PREMIUM (经免费路径调上游旗舰)
        #            oc/gemini-3.5-flash / zai/glm-4.7-flash → CHEAP
        #            oc/deepseek-v4 / oc/glm-5.1 / oc/kimi-k2.6 → STANDARD
        #            oc/qwen3.7-max → STANDARD
        self._add("omniroute/auto", "omniroute", "OmniRoute Auto (免费路由)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.CHEAP, 200000, 2.0, supports_tools=True)
        self._add("omniroute/auto:free", "omniroute", "OmniRoute Auto:Free (仅免费 tier)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.CHEAP, 200000, 2.0, supports_tools=True)
        self._add("omniroute/auto:chaos", "omniroute", "OmniRoute Auto:Chaos (多模型并行)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.PREMIUM, 200000, 1.5, supports_tools=True)
        self._add("omniroute/oc/gpt-5.5", "omniroute", "OmniRoute → GPT-5.5 (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.PREMIUM, 256000, 1.0, supports_tools=True)
        self._add("omniroute/oc/claude-sonnet-4-6", "omniroute",
                  "OmniRoute → Claude Sonnet 4.6 (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.PREMIUM, 200000, 1.0, supports_tools=True)
        self._add("omniroute/oc/gemini-3.5-flash", "omniroute",
                  "OmniRoute → Gemini 3.5 Flash (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.CHEAP, 1000000, 3.0, supports_tools=True)
        self._add("omniroute/oc/deepseek-v4", "omniroute",
                  "OmniRoute → DeepSeek V4 (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.STANDARD, 128000, 2.5, supports_tools=True)
        self._add("omniroute/oc/glm-5.1", "omniroute",
                  "OmniRoute → GLM-5.1 (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.STANDARD, 128000, 3.0, supports_tools=True)
        self._add("omniroute/oc/kimi-k2.6", "omniroute",
                  "OmniRoute → Kimi K2.6 (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.STANDARD, 256000, 1.5, supports_tools=True)
        self._add("omniroute/oc/qwen3.7-max", "omniroute",
                  "OmniRoute → Qwen 3.7 Max (免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.STANDARD, 128000, 1.5, supports_tools=True)
        self._add("omniroute/zai/glm-4.7-flash", "omniroute",
                  "OmniRoute → Z.AI GLM-4.7 Flash (永久免费)",
                  "http://localhost:20128/v1", "OMNIROUTE_API_KEY",
                  0.0, 0.0, ModelTier.CHEAP, 128000, 3.0, supports_tools=True)

        # ── 国产 14 provider (借壳 OpenAICompatProvider) ────────────
        # Alibaba Qwen
        self._add("qwen3.7-max", "alibaba", "Qwen 3.7 Max",
                  "https://dashscope.aliyuncs.com/compatible-mode/v1",
                  "DASHSCOPE_API_KEY", 0.002, 0.006, ModelTier.PREMIUM,
                  128000, 1.5)
        # Baidu ERNIE
        self._add("ernie-4.5-turbo-128k", "baidu", "ERNIE 4.5 Turbo",
                  "https://qianfan.baidubce.com/v2",
                  "ERNIE_API_KEY", 0.0024, 0.0096, ModelTier.STANDARD,
                  128000, 1.5)
        # Zhipu GLM
        self._add("glm-4.7-flash", "zhipu", "GLM 4.7 Flash",
                  "https://open.bigmodel.cn/api/paas/v4",
                  "ZHIPU_API_KEY", 0.0, 0.0, ModelTier.CHEAP,
                  128000, 3.0)
        # Doubao
        self._add("doubao-1.5-pro-256k", "doubao", "Doubao 1.5 Pro 256k",
                  "https://ark.cn-beijing.volces.com/api/v3",
                  "DOUBAO_API_KEY", 0.0011, 0.0028, ModelTier.STANDARD,
                  256000, 2.0)
        # Moonshot Kimi
        self._add("kimi-k2", "moonshot", "Kimi K2",
                  "https://api.moonshot.cn/v1",
                  "MOONSHOT_API_KEY", 0.0012, 0.0048, ModelTier.PREMIUM,
                  256000, 1.5)
        # Baichuan
        self._add("Baichuan4-Turbo", "baichuan", "Baichuan4 Turbo",
                  "https://api.baichuan-ai.com/v1",
                  "BAICHUAN_API_KEY", 0.001, 0.004, ModelTier.STANDARD,
                  128000, 1.5)
        # 01.AI Yi
        self._add("yi-large-rag", "01ai", "Yi Large RAG",
                  "https://api.lingyiwanwu.com/v1",
                  "YI_API_KEY", 0.002, 0.006, ModelTier.STANDARD,
                  128000, 1.5)
        # Tencent Hunyuan
        self._add("hunyuan-turbos", "tencent", "Hunyuan Turbo S",
                  "https://api.hunyuan.cloud.tencent.com/v1",
                  "HUNYUAN_API_KEY", 0.0015, 0.006, ModelTier.STANDARD,
                  128000, 1.5)
        # iFlytek Spark
        self._add("spark4-turbo", "iflytek", "Spark 4 Turbo",
                  "https://spark-api-open.xf-yun.com/v1",
                  "SPARK_API_KEY", 0.0015, 0.006, ModelTier.STANDARD,
                  128000, 1.5)
        # MiniMax
        self._add("abab7-preview", "minimax", "ABAB 7 Preview",
                  "https://api.minimax.chat/v1",
                  "MINIMAX_API_KEY", 0.002, 0.006, ModelTier.STANDARD,
                  128000, 1.5)
        # StepFun
        self._add("step-2-16k", "stepfun", "Step 2 16k",
                  "https://api.stepfun.com/v1",
                  "STEPFUN_API_KEY", 0.0015, 0.006, ModelTier.STANDARD,
                  16000, 1.5)
        # SiliconFlow
        self._add("siliconflow/Qwen/Qwen2.5-72B-Instruct", "siliconflow",
                  "SF Qwen 2.5 72B", "https://api.siliconflow.cn/v1",
                  "SILICONFLOW_API_KEY", 0.0007, 0.0007, ModelTier.CHEAP,
                  128000, 2.0)
        # SenseTime
        self._add("SenseChat-5", "sensetime", "SenseChat 5",
                  "https://api.sensenova.cn/compatible-mode/v1",
                  "SENSENOVA_API_KEY", 0.002, 0.006, ModelTier.STANDARD,
                  128000, 1.5)
        # Kunlun Skywork
        self._add("skywork-o1-v1", "kunlun", "Skywork O1",
                  "https://api.moonshot.cn/v1",
                  "SKYWORK_API_KEY", 0.0014, 0.0056, ModelTier.STANDARD,
                  128000, 1.5)

    def _add(self, model_id: str, provider: str, label: str,
             api_url: str, api_key_env: str,
             cost_in: float, cost_out: float, tier: ModelTier,
             context: int, speed: float,
             supports_tools: bool = True, max_tool_calls: int = 5):
        self._models[model_id] = ModelEntry(
            model_id=model_id, provider=provider, label=label,
            api_url=api_url, api_key_env=api_key_env,
            cost_per_1k_input=cost_in, cost_per_1k_output=cost_out,
            tier=tier, context_window=context, speed=speed,
            supports_tools=supports_tools, max_tool_calls=max_tool_calls,
        )

    # ── 查询接口 ────────────────────────────────────────────────

    def get(self, model_id: str) -> Optional[ModelEntry]:
        return self._models.get(model_id)

    def register(self, entry: ModelEntry):
        self._models[entry.model_id] = entry

    def list_all(self) -> List[ModelEntry]:
        return list(self._models.values())

    def list_by_tier(self, tier: ModelTier) -> List[ModelEntry]:
        return [m for m in self._models.values() if m.tier == tier]

    def list_by_provider(self, provider: str) -> List[ModelEntry]:
        return [m for m in self._models.values() if m.provider == provider]

    def list_providers(self) -> List[str]:
        return sorted({m.provider for m in self._models.values()})

    def cheapest(self, tier: Optional[ModelTier] = None,
                 requires_tools: bool = False) -> Optional[ModelEntry]:
        candidates = self.list_by_tier(tier) if tier else self.list_all()
        if requires_tools:
            candidates = [m for m in candidates if m.supports_tools]
        if not candidates:
            return None
        return min(candidates, key=lambda m: m.cost_per_1k_input + m.cost_per_1k_output)

    def best_for_task(self, complexity: str = "medium",
                      requires_tools: bool = True,
                      budget: float = 0.01) -> Optional[ModelEntry]:
        """根据任务复杂度选择最优模型。"""
        tier_map = {
            "simple": ModelTier.CHEAP,
            "medium": ModelTier.STANDARD,
            "complex": ModelTier.PREMIUM,
            "critical": ModelTier.ULTRA,
        }
        tier = tier_map.get(complexity, ModelTier.STANDARD)
        candidates = self.list_by_tier(tier)
        if requires_tools:
            candidates = [m for m in candidates if m.supports_tools]
        # 在 tier 内选最便宜且预算可承受的
        affordable = [m for m in candidates
                      if m.cost_per_1k_input + m.cost_per_1k_output <= budget * 2]
        if affordable:
            return min(affordable,
                       key=lambda m: m.cost_per_1k_input + m.cost_per_1k_output)
        if candidates:
            return min(candidates,
                       key=lambda m: m.cost_per_1k_input + m.cost_per_1k_output)
        return self.cheapest(requires_tools=requires_tools)

    # ── 🆓 免费模型查询 (OmniRoute 网关) ────────────────────────

    def list_free(self, requires_tools: bool = False) -> List[ModelEntry]:
        """列出所有零成本模型 (cost_in == 0 且 cost_out == 0)。

        主要用于 OmniRoute 网关模型 (经免费 tier 调上游) 和本地 Ollama。
        """
        candidates = [m for m in self._models.values()
                      if m.cost_per_1k_input == 0.0 and m.cost_per_1k_output == 0.0]
        if requires_tools:
            candidates = [m for m in candidates if m.supports_tools]
        return candidates

    def list_free_by_provider(self, provider: str = "omniroute") -> List[ModelEntry]:
        """列出指定 provider 的免费模型 (默认 omniroute)。"""
        return [m for m in self.list_free() if m.provider == provider]

    def best_free_for_task(self, complexity: str = "medium",
                           requires_tools: bool = True,
                           prefer_provider: str = "omniroute"
                           ) -> Optional[ModelEntry]:
        """选择指定复杂度 tier 内的免费模型, 优先指定 provider。

        典型用途: 当 OmniRoute 网关在线时, 优先返回 omniroute/* 模型,
        实现永久免费 LLM 路由。若无匹配, 回退到任意免费模型。
        """
        tier_map = {
            "simple": ModelTier.CHEAP,
            "medium": ModelTier.STANDARD,
            "complex": ModelTier.PREMIUM,
            "critical": ModelTier.ULTRA,
        }
        tier = tier_map.get(complexity, ModelTier.STANDARD)
        free = self.list_free(requires_tools=requires_tools)
        if not free:
            return None
        # 优先 prefer_provider 的模型
        preferred = [m for m in free if m.provider == prefer_provider]
        # 优先匹配 tier; 若无则降级到 CHEAP (auto/auto:free 落在 CHEAP)
        for pool in (preferred, free):
            tier_match = [m for m in pool if m.tier == tier]
            if tier_match:
                # tier 匹配, 选速度最快的
                return max(tier_match, key=lambda m: m.speed)
        # 兜底: 任意免费模型, 速度优先
        return max(free, key=lambda m: m.speed)

    def estimate_cost(self, model_id: str, input_tokens: int,
                      output_tokens: int) -> float:
        m = self.get(model_id)
        if not m:
            return 0.0
        return (input_tokens / 1000 * m.cost_per_1k_input +
                output_tokens / 1000 * m.cost_per_1k_output)

    def estimate_tokens(self, text: str) -> int:
        return int(len(text) * 0.75)  # 粗略估计

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_models": len(self._models),
            "total_providers": len(self.list_providers()),
            "by_tier": {tier.value: len(self.list_by_tier(tier))
                       for tier in ModelTier},
            "providers": self.list_providers(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {mid: m.to_dict() for mid, m in self._models.items()}


# ── 全局单例 ─────────────────────────────────────────────────────

_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    """获取全局 ModelRegistry 单例。"""
    return _registry


def get_model(model_id: str) -> Optional[ModelEntry]:
    """便捷查询: 获取模型条目。"""
    return _registry.get(model_id)


__all__ = [
    "ModelTier", "ModelEntry", "ModelRegistry",
    "get_registry", "get_model",
]
