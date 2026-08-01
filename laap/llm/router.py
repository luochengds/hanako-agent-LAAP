"""laap/llm/router.py — 智能模型路由

移植自 laap/agent_core/model_router.py, 依赖统一后的 laap.llm.registry.ModelRegistry。
根据任务复杂度自动选择最优模型 (4 等级: simple/medium/complex/critical)。

🆓 OmniRoute 集成:
    当 OmniRoute 网关在线 (http://localhost:20128) 时, `prefer_free=True`
    会优先将请求路由到 omniroute/* 模型, 实现永久免费 LLM 调用。
    `auto_detect_omniroute()` 可探测网关可用性并自动开启免费路由。
"""
from __future__ import annotations
import re
import logging
from typing import Optional

from laap.llm.registry import ModelRegistry, get_registry, ModelTier

logger = logging.getLogger("laap.llm.router")


# ── 复杂度模式匹配 (移植自 agent_core/model_router.py) ───────────

SIMPLE_PATTERNS = [
    r"^(hi|hello|你好|嗨)[\s!！。.]*$",
    r"^(谢谢|thanks|thank you|多谢)[\s!！。.]*$",
    r"^(bye|再见|拜拜)[\s!！。.]*$",
    r"^(ok|okay|好的|嗯|ok啦)[\s!！。.]*$",
    r"^\d+$",  # 纯数字
    r"^[\w\s]{1,10}$",  # 10 字符以内
]

COMPLEX_PATTERNS = [
    r"(分析|设计|实现|架构|optimize|refactor|debug)",
    r"(比较|对比|evaluate|compare)",
    r"(解释|explain|为什么|why)",
    r"(写代码|编程|implement|code|函数|function)",
    r"(论文|paper|research)",
    r"(多步|step.by.step|流程)",
]

CRITICAL_PATTERNS = [
    r"(生产环境|production|deploy|部署)",
    r"(安全|security|vulnerability|漏洞)",
    r"(数据库|database|migration|迁移)",
    r"(删除|delete|drop|破坏性)",
    r"(金钱|支付|payment|transaction)",
]


# ── OmniRoute 网关可用性探测 (惰性缓存) ────────────────────────

_omniroute_available: Optional[bool] = None
_omniroute_checked: bool = False


def is_omniroute_available(force_refresh: bool = False) -> bool:
    """探测 OmniRoute 网关是否在线 (结果缓存到首次调用)。

    OmniRoute 默认监听 http://localhost:20128, 提供 /api/health 健康检查端点。
    若 OMNIROUTE_BASE_URL 环境变量已设置, 则探测该地址。
    """
    global _omniroute_available, _omniroute_checked
    if _omniroute_checked and not force_refresh:
        return bool(_omniroute_available)
    _omniroute_checked = True
    try:
        from laap.llm.provider import OmniRouteProvider
        _omniroute_available = OmniRouteProvider.is_available(timeout=1.5)
    except Exception as exc:
        logger.debug("OmniRoute availability probe failed: %s", exc)
        _omniroute_available = False
    if _omniroute_available:
        logger.info(
            "[OK] OmniRoute 网关在线 — 永久免费 LLM 路由已启用 (prefer_free 默认开启)"
        )
    else:
        logger.debug(
            "OmniRoute 网关离线 — 回退到常规付费路由。"
            " 启动方式: scripts/start_omniroute.cmd"
        )
    return bool(_omniroute_available)


def reset_omniroute_cache():
    """重置 OmniRoute 可用性缓存 (用于重启网关后重新探测)。"""
    global _omniroute_available, _omniroute_checked
    _omniroute_available = None
    _omniroute_checked = False


class ModelRouter:
    """智能模型路由器 — 根据任务复杂度选择模型。

    复杂度分 4 级:
        - simple:   问候/确认/简短回答 → CHEAP tier
        - medium:   常规对话/问答 → STANDARD tier
        - complex:  分析/设计/编程 → PREMIUM tier
        - critical: 生产/安全/支付 → ULTRA tier

    免费路由 (prefer_free=True 或 auto_detect=True 且 OmniRoute 在线):
        优先从 omniroute/* 模型池中按 tier 选择, 实现零成本 LLM 调用。
    """

    def __init__(self, registry: Optional[ModelRegistry] = None,
                 prefer_free: bool = False,
                 auto_detect: bool = True):
        """初始化路由器。

        Args:
            registry: 模型注册表 (默认使用全局单例)
            prefer_free: 强制启用免费路由 (优先 omniroute/*)
            auto_detect: 启动时探测 OmniRoute 可用性, 若在线则自动启用 prefer_free
        """
        self.registry = registry or get_registry()
        self.prefer_free = prefer_free
        self._stats = {
            "classifications": {"simple": 0, "medium": 0,
                                "complex": 0, "critical": 0},
            "routes": {},  # model_id → count
            "total_saved": 0.0,  # 估算节省成本
            "free_routes": 0,    # 经 omniroute/* 路由的次数
        }
        # 自动探测 OmniRoute 并据此决定是否启用免费路由
        if auto_detect and not self.prefer_free:
            try:
                self.prefer_free = is_omniroute_available()
            except Exception:
                self.prefer_free = False

    # ── 复杂度分类 ─────────────────────────────────────────────

    def classify(self, task: str) -> str:
        """分类任务复杂度, 返回 simple/medium/complex/critical。"""
        if not task:
            return "simple"

        task_lower = task.lower() if isinstance(task, str) else str(task).lower()

        # critical 优先
        for pattern in CRITICAL_PATTERNS:
            if re.search(pattern, task_lower, re.IGNORECASE):
                return "critical"

        # complex
        for pattern in COMPLEX_PATTERNS:
            if re.search(pattern, task_lower, re.IGNORECASE):
                return "complex"

        # simple
        for pattern in SIMPLE_PATTERNS:
            if re.match(pattern, task_lower, re.IGNORECASE):
                return "simple"

        # 默认 medium
        return "medium"

    # ── 路由 ───────────────────────────────────────────────────

    def route(self, task: str, requires_tools: bool = True,
              budget: float = 0.01,
              prefer_free: Optional[bool] = None) -> str:
        """根据任务选择最优模型 ID。

        Args:
            task: 任务描述
            requires_tools: 是否需要工具支持
            budget: 预算 (美元/1k tokens)
            prefer_free: 显式覆盖免费路由开关 (None=使用实例默认)

        Returns:
            模型 ID (如 "omniroute/auto" 或 "deepseek-v4-flash")
        """
        complexity = self.classify(task)
        self._stats["classifications"][complexity] += 1

        use_free = self.prefer_free if prefer_free is None else prefer_free
        entry = None

        # 🆓 免费路由优先: OmniRoute 网关在线时, 选 omniroute/* 模型
        if use_free:
            entry = self.registry.best_free_for_task(
                complexity=complexity,
                requires_tools=requires_tools,
                prefer_provider="omniroute",
            )
            if entry is not None:
                self._stats["free_routes"] += 1
                logger.debug(
                    "[TOKEN] 免费路由: complexity=%s → %s (provider=%s, tier=%s)",
                    complexity, entry.model_id, entry.provider, entry.tier.value,
                )

        # 常规路由: 按 tier + budget 选择 (可能产生费用)
        if entry is None:
            entry = self.registry.best_for_task(
                complexity=complexity,
                requires_tools=requires_tools,
                budget=budget,
            )

        # 兜底 fallback
        if entry is None:
            entry = self.registry.cheapest(requires_tools=requires_tools)
            if entry is None:
                return "omniroute/auto" if use_free else "deepseek-v4-flash"

        model_id = entry.model_id
        self._stats["routes"][model_id] = self._stats["routes"].get(model_id, 0) + 1

        # 估算节省 (相对于最贵的 ULTRA 模型)
        ultra_models = self.registry.list_by_tier(ModelTier.ULTRA)
        if ultra_models and entry.tier != ModelTier.ULTRA:
            most_expensive = max(ultra_models,
                                 key=lambda m: m.cost_per_1k_input + m.cost_per_1k_output)
            saved = ((most_expensive.cost_per_1k_input + most_expensive.cost_per_1k_output) -
                     (entry.cost_per_1k_input + entry.cost_per_1k_output))
            self._stats["total_saved"] += saved

        return model_id

    # ── 统计 ───────────────────────────────────────────────────

    def get_stats(self) -> dict:
        stats = dict(self._stats)
        stats["prefer_free"] = self.prefer_free
        stats["omniroute_online"] = is_omniroute_available()
        return stats

    def reset_stats(self):
        self._stats = {
            "classifications": {"simple": 0, "medium": 0,
                                "complex": 0, "critical": 0},
            "routes": {},
            "total_saved": 0.0,
            "free_routes": 0,
        }

    def set_prefer_free(self, enabled: bool):
        """运行时切换免费路由开关。"""
        self.prefer_free = enabled
        logger.debug("免费路由已 %s", "启用" if enabled else "禁用")


# ── 全局单例 ─────────────────────────────────────────────────────

_router = ModelRouter()


def get_router() -> ModelRouter:
    """获取全局 ModelRouter 单例。"""
    return _router


def route_task(task: str, **kwargs) -> str:
    """便捷函数: 路由任务到最优模型。"""
    return _router.route(task, **kwargs)


def classify_task(task: str) -> str:
    """便捷函数: 分类任务复杂度。"""
    return _router.classify(task)


__all__ = [
    "ModelRouter", "get_router",
    "route_task", "classify_task",
    "is_omniroute_available", "reset_omniroute_cache",
    "SIMPLE_PATTERNS", "COMPLEX_PATTERNS", "CRITICAL_PATTERNS",
]
