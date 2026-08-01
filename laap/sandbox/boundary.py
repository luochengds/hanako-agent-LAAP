"""LAAP Sandbox 边界控制器

Boundary 是每个 Cognitive Sandbox 的安全边界，
管理 ingress/egress 信号过滤与访问日志。

每个 CognitiveSandbox 拥有独立的 Boundary 实例，
控制什么信号可以进入/离开本沙箱，记录所有访问尝试。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.sandbox.boundary")

__all__ = ["Boundary"]


class Boundary:
    """沙箱边界控制器——管理 ingress/egress 信号过滤与访问日志。

    每个 CognitiveSandbox 拥有独立的 Boundary 实例，
    控制什么信号可以进入/离开本沙箱，记录所有访问尝试。

    Attributes:
        sandbox_id: 所属 sandbox 的唯一标识。
        DEFAULT_ALLOWED_EGRESS: 默认允许离开的信号类型。
        DEFAULT_ALLOWED_INGRESS: 默认允许进入的信号类型。
    """

    DEFAULT_ALLOWED_EGRESS = ("colony_event", "suggestion", "skill_lookup", "memory_export")
    DEFAULT_ALLOWED_INGRESS = ("colony_event", "perception_update", "shared_fact")

    def __init__(
        self,
        sandbox_id: str,
        allowed_ingress: Optional[List[str]] = None,
        allowed_egress: Optional[List[str]] = None,
    ):
        """初始化边界控制器。

        Args:
            sandbox_id: 所属 sandbox 的唯一标识。
            allowed_ingress: 允许进入的信号类型列表，默认使用 DEFAULT_ALLOWED_INGRESS。
            allowed_egress: 允许离开的信号类型列表，默认使用 DEFAULT_ALLOWED_EGRESS。
        """
        self.sandbox_id = sandbox_id
        self._allowed_ingress: set = set(allowed_ingress if allowed_ingress is not None else self.DEFAULT_ALLOWED_INGRESS)
        self._allowed_egress: set = set(allowed_egress if allowed_egress is not None else self.DEFAULT_ALLOWED_EGRESS)
        # 访问日志条目格式：
        # {timestamp, direction, signal_type, source, allowed, reason}
        self._access_log: List[Dict[str, Any]] = []
        self._max_log = 1000

    # ------------------------------------------------------------------
    # 检查接口
    # ------------------------------------------------------------------
    def check_ingress(self, signal_type: str, source_sandbox: Optional[str] = None) -> bool:
        """检查外部信号是否允许进入本沙箱。

        Args:
            signal_type: 信号类型，如 "colony_event" / "shared_fact"。
            source_sandbox: 发起方 sandbox 标识（可选）。

        Returns:
            True 表示允许进入；False 表示拒绝。
        """
        allowed = signal_type in self._allowed_ingress
        reason = "type in allowed ingress list" if allowed else "type not in ingress whitelist"
        self._record_log(
            direction="ingress",
            signal_type=signal_type,
            source=source_sandbox,
            allowed=allowed,
            reason=reason,
        )
        if not allowed:
            logger.debug(
                "Boundary[%s] denied ingress: signal_type=%s source=%s",
                self.sandbox_id, signal_type, source_sandbox,
            )
        return allowed

    def check_egress(self, signal_type: str) -> bool:
        """检查本沙箱的信号是否允许离开。

        Args:
            signal_type: 信号类型，如 "suggestion" / "memory_export"。

        Returns:
            True 表示允许离开；False 表示拒绝。
        """
        allowed = signal_type in self._allowed_egress
        reason = "type in allowed egress list" if allowed else "type not in egress whitelist"
        self._record_log(
            direction="egress",
            signal_type=signal_type,
            source=self.sandbox_id,
            allowed=allowed,
            reason=reason,
        )
        if not allowed:
            logger.debug(
                "Boundary[%s] denied egress: signal_type=%s",
                self.sandbox_id, signal_type,
            )
        return allowed

    # ------------------------------------------------------------------
    # 动态注册 / 撤销
    # ------------------------------------------------------------------
    def register_allowed_ingress(self, types: List[str]) -> None:
        """动态添加允许进入的信号类型。

        Args:
            types: 要添加的信号类型列表。
        """
        for t in types:
            self._allowed_ingress.add(t)
        logger.debug("Boundary[%s] registered ingress types: %s", self.sandbox_id, types)

    def register_allowed_egress(self, types: List[str]) -> None:
        """动态添加允许离开的信号类型。

        Args:
            types: 要添加的信号类型列表。
        """
        for t in types:
            self._allowed_egress.add(t)
        logger.debug("Boundary[%s] registered egress types: %s", self.sandbox_id, types)

    def revoke_ingress(self, types: List[str]) -> None:
        """撤销允许进入的信号类型。

        Args:
            types: 要撤销的信号类型列表。
        """
        for t in types:
            self._allowed_ingress.discard(t)
        logger.debug("Boundary[%s] revoked ingress types: %s", self.sandbox_id, types)

    def revoke_egress(self, types: List[str]) -> None:
        """撤销允许离开的信号类型。

        Args:
            types: 要撤销的信号类型列表。
        """
        for t in types:
            self._allowed_egress.discard(t)
        logger.debug("Boundary[%s] revoked egress types: %s", self.sandbox_id, types)

    # ------------------------------------------------------------------
    # 访问日志
    # ------------------------------------------------------------------
    def _record_log(
        self,
        direction: str,
        signal_type: str,
        source: Optional[str],
        allowed: bool,
        reason: str,
    ) -> None:
        """记录一次访问检查到日志（内部使用）。

        当日志条目超过 _max_log 时丢弃最旧条目。
        """
        entry = {
            "timestamp": time.time(),
            "direction": direction,
            "signal_type": signal_type,
            "source": source,
            "allowed": allowed,
            "reason": reason,
        }
        self._access_log.append(entry)
        # 超出容量时丢弃最旧条目
        overflow = len(self._access_log) - self._max_log
        if overflow > 0:
            del self._access_log[:overflow]

    def get_access_log(
        self,
        direction: Optional[str] = None,
        allowed_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """查询访问日志。

        Args:
            direction: 过滤方向，'ingress' / 'egress' / None（全部）。
            allowed_only: 仅返回允许的条目。

        Returns:
            匹配的日志条目列表（按时间顺序）。
        """
        results: List[Dict[str, Any]] = []
        for entry in self._access_log:
            if direction is not None and entry["direction"] != direction:
                continue
            if allowed_only and not entry["allowed"]:
                continue
            results.append(entry)
        return results

    def clear_log(self) -> None:
        """清空访问日志。"""
        self._access_log.clear()
        logger.debug("Boundary[%s] access log cleared", self.sandbox_id)

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """返回统计信息：允许/拒绝次数、ingress/egress 类型列表。

        Returns:
            统计字典，包含：
                - sandbox_id
                - ingress_allowed_count / ingress_denied_count
                - egress_allowed_count / egress_denied_count
                - allowed_ingress_types / allowed_egress_types
                - log_size
        """
        ingress_allowed = 0
        ingress_denied = 0
        egress_allowed = 0
        egress_denied = 0
        for entry in self._access_log:
            if entry["direction"] == "ingress":
                if entry["allowed"]:
                    ingress_allowed += 1
                else:
                    ingress_denied += 1
            elif entry["direction"] == "egress":
                if entry["allowed"]:
                    egress_allowed += 1
                else:
                    egress_denied += 1
        return {
            "sandbox_id": self.sandbox_id,
            "ingress_allowed_count": ingress_allowed,
            "ingress_denied_count": ingress_denied,
            "egress_allowed_count": egress_allowed,
            "egress_denied_count": egress_denied,
            "allowed_ingress_types": sorted(self._allowed_ingress),
            "allowed_egress_types": sorted(self._allowed_egress),
            "log_size": len(self._access_log),
        }
