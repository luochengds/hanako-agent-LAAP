"""LAAP Body Layer ↔ Hermes 可选适配器。

``HermesBodyAdapter`` 将 ``laap.body.BodySystem`` 桥接到 Hermes Agent 框架。
当 Hermes 不可用时，所有方法退化为透传/no-op，不影响 LAAP 启动。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from laap.body import BodySystem, create_default_body_system

logger = logging.getLogger("laap.body.adapters.hermes")


# 可选 Hermes 客户端：导入失败时保持 _HermesClient 为 None，避免启动崩溃。
_HermesClient: Optional[type] = None
try:
    # Hermes 如果作为包安装，通常通过 hermes 命名空间暴露。
    # 这里使用延迟查找；若不存在则适配器完全退化为透传。
    import hermes  # type: ignore[import-not-found]

    _HermesClient = getattr(hermes, "Hermes", None)
except Exception:  # pragma: no cover - Hermes 可选
    hermes = None  # type: ignore[assignment]


class HermesBodyAdapter:
    """Body 层到 Hermes 的可选适配器。

    默认行为是透传：构造时传入的 ``body_system`` 会原样返回，
    因此即使 Hermes 未安装或不可用，LAAP 也能正常启动。

    Args:
        body_system: 要适配的 ``BodySystem`` 实例。若未提供，则创建默认实例。
        hermes_client: 可选的 Hermes 客户端实例。若未提供，则尝试自动发现。
    """

    def __init__(
        self,
        body_system: Optional[BodySystem] = None,
        hermes_client: Optional[Any] = None,
    ):
        self.body_system = body_system or create_default_body_system()
        self._hermes = hermes_client
        self._hermes_available = False

        if self._hermes is not None:
            self._hermes_available = True
        elif _HermesClient is not None:
            try:
                self._hermes = _HermesClient()
                self._hermes_available = True
            except Exception as exc:  # pragma: no cover
                logger.debug("Hermes auto-discovery failed: %s", exc)

    @property
    def available(self) -> bool:
        """Hermes 是否可用。"""
        return self._hermes_available

    def adapt(self) -> BodySystem:
        """返回适配后的 ``BodySystem``。

        当 Hermes 不可用时，直接返回原始 ``body_system``（透传）。
        """
        if not self._hermes_available:
            return self.body_system

        # 当 Hermes 可用时，可在此注入 Hermes 提供的工具、LLM 能力等。
        # 当前保持最小实现：透传原始 body_system。
        return self.body_system

    def status(self) -> Dict[str, Any]:
        """返回适配器状态摘要。"""
        return {
            "available": self._hermes_available,
            "has_hermes_client": self._hermes is not None,
            "body_system": {
                "tools": self.body_system.tools.__name__,
                "llm": self.body_system.llm.__name__,
                "mcp": self.body_system.mcp.__name__,
                "skills": self.body_system.skills.__name__,
                "plugins": self.body_system.plugins.__name__,
                "gateway": self.body_system.gateway.__name__,
            },
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"available={self._hermes_available}, "
            f"body_system={self.body_system!r})"
        )
