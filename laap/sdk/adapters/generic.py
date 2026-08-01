"""通用 Python Agent 适配器 — 支持任意实现钩子接口的对象。"""

from __future__ import annotations

import logging
from typing import Any, Optional

from laap.sdk.adapter import AgentAdapter

logger = logging.getLogger(__name__)


class GenericAdapter(AgentAdapter):
    """通用 Python Agent 适配器。

    支持两种 agent 集成方式：
    1. agent 有 ``register_hook(event, callback)`` 方法 — 注册三个钩子
    2. agent 无该方法 — 仅挂 ``agent.laap_brain = brain``，由用户手动调用钩子
    """

    def __init__(self, agent: Optional[Any] = None) -> None:
        self._agent = agent
        self._installed = False
        self._brain: Optional[Any] = None
        self._registered_callbacks: list = []

    def name(self) -> str:
        return "generic"

    @staticmethod
    def detect() -> bool:
        """GenericAdapter 永远返回 True，作为兜底。

        Returns:
            始终返回 True。
        """
        return True

    def install_hooks(self, brain: Any) -> None:
        """根据 agent 能力选择最佳集成方式。

        - agent=None: 仅挂 adapter，brain 由调用方持有
        - agent 有 ``register_hook``: 注册 before_turn / after_tool / after_turn 三个钩子
        - agent 无 ``register_hook``: 挂 ``agent.laap_brain = brain`` 属性

        单个注册失败不阻断其余钩子（log warning）。

        Args:
            brain: LaapBrain 实例。
        """
        self._brain = brain

        if self._agent is None:
            logger.info(
                "GenericAdapter: no agent provided, brain attached to adapter only"
            )
            self._installed = True
            return

        # 检测 agent 是否有 register_hook 方法
        if hasattr(self._agent, "register_hook") and callable(
            self._agent.register_hook
        ):
            # 模式 1：注册三个钩子
            try:
                self._agent.register_hook("before_turn", brain.before_turn)
                self._registered_callbacks.append("before_turn")
            except Exception as e:
                logger.warning(f"Failed to register before_turn hook: {e}")

            try:
                self._agent.register_hook("after_tool", brain.after_tool)
                self._registered_callbacks.append("after_tool")
            except Exception as e:
                logger.warning(f"Failed to register after_tool hook: {e}")

            try:
                self._agent.register_hook("after_turn", brain.after_turn)
                self._registered_callbacks.append("after_turn")
            except Exception as e:
                logger.warning(f"Failed to register after_turn hook: {e}")

            logger.info(
                f"GenericAdapter: registered hooks {self._registered_callbacks}"
            )
        else:
            # 模式 2：仅挂 brain 属性
            try:
                self._agent.laap_brain = brain
                logger.info(
                    "GenericAdapter: brain attached as agent.laap_brain (manual hooks required)"
                )
            except Exception as e:
                logger.warning(f"Failed to attach brain as attribute: {e}")

        self._installed = True

    def uninstall_hooks(self) -> None:
        """GenericAdapter 暂不支持 unregister_hook（多数 agent 不支持）。

        若 agent 有 ``unregister_hook`` 方法则尝试调用，否则仅清空内部状态。
        """
        if not self._installed:
            return
        # 尝试调用 unregister_hook（如果存在）
        if self._agent and hasattr(self._agent, "unregister_hook"):
            for event in self._registered_callbacks:
                try:
                    self._agent.unregister_hook(event)
                except Exception as e:
                    logger.warning(f"Failed to unregister {event}: {e}")

        self._registered_callbacks.clear()
        self._installed = False
        logger.info("GenericAdapter hooks uninstalled")
