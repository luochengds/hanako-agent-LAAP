"""mount — LAAP 大脑挂载到外部智能体的统一入口。"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:
    from laap_brain import LaapBrain

    from laap.sdk.adapter import AgentAdapter

logger = logging.getLogger(__name__)

# 适配器懒加载映射表：name → "module.path:ClassName"
_ADAPTERS_MAP = {
    "hermes": "laap.sdk.adapters.hermes:HermesAdapter",
    "claude_code": "laap.sdk.adapters.claude_code:ClaudeCodeAdapter",
    "openclaw": "laap.sdk.adapters.openclaw:OpenClawAdapter",
    "generic": "laap.sdk.adapters.generic:GenericAdapter",
}

# auto 模式检测顺序：Hermes → Claude Code → OpenClaw → Generic
_AUTO_DETECT_ORDER = ("hermes", "claude_code", "openclaw", "generic")


def _load_adapter(name: str):
    """懒加载适配器类。

    使用 importlib.import_module + getattr 解析 ``module:Class`` 形式的映射条目，
    适配器模块不存在时优雅返回 None。

    Args:
        name: 适配器名称（hermes / claude_code / openclaw / generic）。

    Returns:
        适配器类对象；若模块不存在或导入失败则返回 None。
    """
    spec = _ADAPTERS_MAP.get(name)
    if not spec:
        return None
    try:
        module_path, class_name = spec.split(":")
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        logger.debug(f"Failed to load adapter '{name}': {e}")
        return None


def _hermes_run_agent_available() -> bool:
    """快速检查 Hermes 环境是否真正可用（run_agent.py 在 HERMES_ROOT 中）。

    HermesAdapter.detect() 仅基于 HERMES_HOME / `import hermes` 即返回 True，
    但 install_hooks → install_laap → `import run_agent` 会触发 lark_oapi 等
    大量子模块的慢速加载（>30s）。本函数用于在 auto 模式下调用 install_hooks
    前做一次文件系统级预检，避免在 HERMES_ROOT 无效的环境中触发慢速 import。
    """
    try:
        from laap.config.paths import get_hermes_root

        hermes_root = get_hermes_root()
        return hermes_root is not None and (hermes_root / "run_agent.py").exists()
    except Exception:
        return False


def mount_brain_to_agent(
    brain: "LaapBrain",
    agent_type: str = "auto",
    agent: Optional[Any] = None,
) -> Tuple["LaapBrain", Optional["AgentAdapter"]]:
    """将 LAAP 大脑挂载到外部智能体。

    Args:
        brain: LaapBrain 实例。
        agent_type: 智能体类型。"auto" 自动检测；或 "hermes" / "claude_code" /
            "openclaw" / "generic"。
        agent: 可选的智能体对象（仅 generic 与 openclaw 模式使用，预留参数）。

    Returns:
        (brain, adapter) 元组；若 auto 全部失败则 adapter 为 None
        （仅在 GenericAdapter 也失败时，不应发生）。

    Raises:
        NotImplementedError: 若显式指定的 agent_type 未实现。
    """
    if agent_type == "auto":
        for name in _AUTO_DETECT_ORDER:
            adapter_cls = _load_adapter(name)
            if adapter_cls is None:
                continue
            try:
                if adapter_cls.detect():
                    adapter = adapter_cls()
                    # Hermes 快速预检：detect() 仅基于 HERMES_HOME 即返回 True，
                    # 但 install_hooks → install_laap → `import run_agent` 会触发
                    # lark_oapi 等大量子模块的慢速加载（>30s 超时）。在调用
                    # install_hooks 前先验证 HERMES_ROOT 真正含 run_agent.py，不满足
                    # 时回退到下一个适配器（GenericAdapter 兜底）。
                    # 仅对真实 HermesAdapter 应用（通过 __module__ 判定，避免误伤测试
                    # 注入的 mock 适配器，mock 的 __module__ 为测试模块路径）。
                    if (
                        name == "hermes"
                        and adapter_cls.__module__ == "laap.sdk.adapters.hermes"
                        and not _hermes_run_agent_available()
                    ):
                        logger.debug(
                            "Hermes pre-check failed: run_agent.py not in "
                            "HERMES_ROOT; falling back to next adapter"
                        )
                        continue
                    adapter.install_hooks(brain)
                    logger.info(f"Auto-mounted adapter: {name}")
                    return brain, adapter
            except Exception as e:
                logger.debug(f"Adapter '{name}' detect failed: {e}")
                continue
        logger.warning("No adapter detected; returning brain without mount")
        return brain, None

    # 显式模式：直接实例化，不调 detect()
    adapter_cls = _load_adapter(agent_type)
    if adapter_cls is None:
        raise NotImplementedError(f"Adapter '{agent_type}' not implemented")
    adapter = adapter_cls()
    adapter.install_hooks(brain)
    logger.info(f"Explicitly mounted adapter: {agent_type}")
    return brain, adapter
