"""LAAP Liquid — LiquidCognitiveCore 液态认知核心容器

本模块实现 ``LiquidCognitiveCore``：一个聚合多个液态子场
（bus_field / affective_field / attention_selector 等）的统一容器，
对外提供 ``evolve_all`` / ``get_state_summary`` 等编排接口。

设计要点：
  - **可空容器**：当运行环境缺少 numpy 时，``is_available()`` 返回 False，
    所有方法退化为 no-op，调用方可在不抛异常的前提下优雅降级。
  - **鸭子类型**：注册的子场只需实现 ``evolve`` / ``decode``（及可选的
    ``get_h_summary`` / ``step``）方法即可被容器调度，无需继承基类。
  - **事件驱动兼容**：``evolve_all(t_now)`` 只接受一个时间戳参数，
    适配 LAAP 事件驱动认知循环中的不规则时间步。

LAAP 日志风格：使用 [OK]/[INFO]/[WARN]/[ERROR] 标签。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.liquid.core")

# ── numpy 可用性探测（惰性导入，避免在缺 numpy 时模块加载失败）─────
try:
    import numpy as _np  # noqa: F401  仅用于探测可用性
    _NUMPY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover — 极少数无 numpy 环境
    _np = None
    _NUMPY_AVAILABLE = False


class LiquidCognitiveCore:
    """液态认知核心 — 聚合多个 liquid 子场的统一编排容器。

    子场接口约定（鸭子类型，全部可选除 evolve 外）：
        - ``evolve(...)``       : 必需。接受 ``evolve(t_now)`` 或 ``evolve(inputs, t_now)``。
        - ``step(t_now)``       : 可选。单参演化接口；若存在则优先调用，
                                  便于子场使用其内部最近一次输入进行演化。
        - ``decode()``          : 可选。返回该场的解码结果（dict / ndarray）。
        - ``get_h_summary()``  : 可选。返回 ``{"h_norm": float, "h_dim": int, ...}``。
        - ``get_tau()``         : 可选。返回当前有效时间常数（float）。

    使用示例：
        >>> from laap.liquid.core import LiquidCognitiveCore
        >>> from laap.liquid.bus_bridge import LiquidBusField
        >>> core = LiquidCognitiveCore()
        >>> core.register_field("bus", LiquidBusField())
        >>> summary = core.evolve_all(t_now=time.time())
        >>> "h_norm" in summary["bus"]
        True
    """

    def __init__(self) -> None:
        # 即使 numpy 不可用也允许实例化（成为 no-op 容器）
        self._fields: Dict[str, Any] = {}
        self._available: bool = _NUMPY_AVAILABLE
        if self._available:
            logger.debug("[INFO] LiquidCognitiveCore 初始化（numpy 可用）")
        else:  # pragma: no cover — 罕见路径
            logger.warning("[WARN] numpy 不可用，LiquidCognitiveCore 进入空容器模式")

    # ── 可用性 ──────────────────────────────────────────────────

    @staticmethod
    def is_available() -> bool:
        """检测 numpy 是否可用。

        返回 True 时所有方法正常工作；返回 False 时所有方法退化为 no-op。
        """
        return _NUMPY_AVAILABLE

    # ── 注册 ────────────────────────────────────────────────────

    def register_field(self, name: str, field: object) -> None:
        """注册一个液态子场。

        参数：
            name  : 子场名称（如 "bus_field" / "affective_field"）
            field : 子场对象，需实现 evolve 方法（推荐实现 step / get_h_summary）

        若 numpy 不可用，此方法为 no-op。
        """
        if not self._available:
            logger.debug(f"[INFO] 空容器模式：忽略注册子场 '{name}'")
            return
        if not isinstance(name, str) or not name:
            raise ValueError(f"[ERROR] 子场名称必须是非空字符串，实际 name={name!r}")
        if not hasattr(field, "evolve"):
            raise TypeError(
                f"[ERROR] 子场 '{name}' 必须实现 evolve 方法，实际类型={type(field).__name__}"
            )
        self._fields[name] = field
        logger.debug(f"[OK] 子场 '{name}' 已注册（type={type(field).__name__}）")

    # ── 统一演化 ────────────────────────────────────────────────

    def evolve_all(self, t_now: float) -> Dict[str, Dict[str, Any]]:
        """对所有注册子场执行一步演化，返回各场状态摘要。

        参数：
            t_now : 当前时间戳（秒，任意基准，仅用于计算 Δt）

        返回：
            dict ：``{field_name: summary_dict}``，其中 summary_dict 来自
            子场的 ``get_h_summary()``（若无则返回空 dict）。

        若 numpy 不可用，返回空 dict。
        """
        if not self._available:
            return {}

        summaries: Dict[str, Dict[str, Any]] = {}
        for name, field in self._fields.items():
            try:
                # 优先调用单参 step(t_now)，便于子场使用其内部缓存的输入
                if hasattr(field, "step"):
                    field.step(t_now)  # type: ignore[attr-defined]
                else:
                    # 退化路径：尝试 evolve(t_now) 单参形式
                    try:
                        field.evolve(t_now)  # type: ignore[arg-type]
                    except TypeError:
                        # evolve 可能需要 (inputs, t_now) 但容器无法提供
                        logger.warning(
                            f"[WARN] 子场 '{name}' 的 evolve 签名无法被 "
                            f"evolve_all 自动调用（建议实现 step(t_now)）"
                        )
            except Exception as exc:  # pragma: no cover — 保护容器不因单场崩溃
                logger.warning(f"[WARN] 子场 '{name}' 演化失败：{exc}")
                continue

            # 收集摘要
            if hasattr(field, "get_h_summary"):
                try:
                    summaries[name] = field.get_h_summary()  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"[WARN] 子场 '{name}' get_h_summary 失败：{exc}")
                    summaries[name] = {}
            else:
                summaries[name] = {}

        return summaries

    # ── 状态摘要 ────────────────────────────────────────────────

    def get_state_summary(self) -> Dict[str, Dict[str, Any]]:
        """返回所有子场的 h(t) 摘要（不触发演化）。

        返回：
            dict ：``{field_name: {"h_norm": float, "h_dim": int, "tau": float, ...}}``

        若 numpy 不可用，返回空 dict。
        """
        if not self._available:
            return {}

        summary: Dict[str, Dict[str, Any]] = {}
        for name, field in self._fields.items():
            if hasattr(field, "get_h_summary"):
                try:
                    summary[name] = field.get_h_summary()  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"[WARN] 子场 '{name}' get_h_summary 失败：{exc}")
                    summary[name] = {}
            else:
                summary[name] = {}
        return summary

    # ── 便捷查询 ────────────────────────────────────────────────

    def list_fields(self) -> list:
        """返回已注册子场名称列表。"""
        return list(self._fields.keys())

    def get_field(self, name: str) -> Optional[object]:
        """按名称获取子场对象；不存在时返回 None。"""
        return self._fields.get(name)

    def __repr__(self) -> str:
        state = "available" if self._available else "empty(no numpy)"
        return f"LiquidCognitiveCore(fields={list(self._fields.keys())}, {state})"
