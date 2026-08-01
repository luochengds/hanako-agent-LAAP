"""Hermes 适配器 — 包装现有 laap_brain.integrate.install_laap() 集成。"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from laap.sdk.adapter import AgentAdapter

logger = logging.getLogger(__name__)


class HermesAdapter(AgentAdapter):
    """Hermes Agent 适配器。

    包装 laap_brain.integrate.install_laap() 的 5 钩子 monkey-patch 集成，
    作为 AgentAdapter 子类暴露统一接口。
    """

    def __init__(self, agent: Optional[Any] = None) -> None:
        self._agent = agent
        self._installed = False
        self._brain: Optional[Any] = None

    def name(self) -> str:
        return "hermes"

    @staticmethod
    def detect() -> bool:
        """检测 Hermes 是否已安装。

        检测顺序：
        1. 环境变量 HERMES_HOME
        2. import hermes 包
        3. import hermes_agent 包

        Returns:
            True 如果检测到 Hermes 环境。
        """
        if os.environ.get("HERMES_HOME"):
            return True
        try:
            import hermes  # noqa: F401

            return True
        except ImportError:
            pass
        try:
            import hermes_agent  # noqa: F401

            return True
        except ImportError:
            pass
        return False

    def install_hooks(self, brain: Any) -> None:
        """安装 LAAP 大脑钩子到 Hermes。

        调用 laap_brain.integrate.install_laap() 完成 5 钩子 monkey-patch。

        Args:
            brain: LaapBrain 实例。

        Raises:
            RuntimeError: install_laap() 返回 False（Hermes 环境不可用）。
                抛出后由 mount_brain_to_agent 捕获并回退到下一个适配器。
        """
        from laap_brain.integrate import install_laap

        self._brain = brain
        if not install_laap():
            raise RuntimeError("install_laap() returned False")

        self._installed = True
        logger.info("Hermes LAAP hooks installed via HermesAdapter")

    def uninstall_hooks(self) -> None:
        """移除已安装的钩子。"""
        from laap_brain.integrate import uninstall_laap

        if self._installed:
            uninstall_laap()
            self._installed = False
            logger.info("Hermes LAAP hooks uninstalled")
