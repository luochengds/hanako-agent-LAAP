"""AgentAdapter — 外部智能体适配器抽象基类。

所有外部智能体适配器（Hermes / OpenClaw / ClaudeCode / Generic）必须继承此基类，
实现 4 个抽象方法，作为 LAAP 大脑挂载到外部智能体的统一契约。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from laap_brain import LaapBrain


class AgentAdapter(ABC):
    """外部智能体适配器抽象基类。

    所有子类必须实现 4 个抽象方法，作为 LAAP 大脑挂载到外部智能体的统一契约。

    抽象方法:
        - install_hooks(brain): 注入 LAAP 大脑钩子到外部智能体
        - uninstall_hooks(): 移除已安装的钩子，恢复原方法
        - detect(): 静态方法，检测当前环境是否存在该智能体宿主
        - name(): 返回适配器名称字符串
    """

    @abstractmethod
    def install_hooks(self, brain: "LaapBrain") -> None:
        """将 LAAP 大脑钩子注入到外部智能体。

        Args:
            brain: LaapBrain 实例。
        """
        ...

    @abstractmethod
    def uninstall_hooks(self) -> None:
        """移除已安装的钩子，恢复原方法。"""
        ...

    @staticmethod
    @abstractmethod
    def detect() -> bool:
        """检测当前环境是否检测到该智能体宿主。

        Returns:
            True 如果该智能体已安装且可被集成。
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """返回适配器名称（如 'hermes' / 'openclaw' / 'claude_code' / 'generic'）。

        Returns:
            适配器名称字符串。
        """
        ...
