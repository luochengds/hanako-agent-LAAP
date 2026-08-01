"""
LAAP AGI — Consciousness Stream (意识流)
=========================================

M3 Task B4: 结构化意识流日志，记录智能体内部所有"主观体验"事件。

设计原则：
  - 统一接口：所有子系统（PSI/记忆/因果/元认知/Self Model/GWS）通过同一接口
    输出意识事件
  - 结构化 JSON：每条事件可被 jq / Datadog / ELK 等外部工具消费
  - 双通道输出：stdout（实时观察） + JSONL 文件（持久回放）
  - 零额外依赖：仅使用标准库 ``logging`` + ``json``

事件字段：
    {
        "timestamp": float,
        "component": str,        # 来源子系统 (psi/meta_cognitive/self_model/...)
        "event_type": str,       # 事件类型 (decision/reflection/update/...)
        "payload": dict,         # 事件具体内容
        "self_model_version": str # 关联的自我模型版本
    }

Usage:
    from laap.agi.consciousness_stream import get_consciousness_stream

    stream = get_consciousness_stream()
    stream.log_event(
        component="psi",
        event_type="decision",
        payload={"action": "respond", "urgency": 0.6},
        self_model_version="v1.0",
    )
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.agi.consciousness_stream")


def _default_stream_path() -> str:
    """运行时推导意识流 JSONL 文件路径。

    优先使用 ``LAAP_HOME`` 环境变量，否则落到 ``~/.laap/``。
    父目录会自动创建。
    """
    laap_home = os.environ.get("LAAP_HOME", str(Path.home() / ".laap"))
    state_dir = Path(laap_home)
    state_dir.mkdir(parents=True, exist_ok=True)
    return str(state_dir / "consciousness_stream.jsonl")


class ConsciousnessStream:
    """结构化意识流日志记录器。

    将每个意识事件同时输出到 stdout（Python logging）与
    ``~/.laap/consciousness_stream.jsonl``（JSON Lines 格式）。

    JSONL 每行一条事件，便于 ``jq`` 流式处理与回放。
    """

    def __init__(
        self,
        jsonl_path: Optional[str] = None,
        stdout_logger: Optional[logging.Logger] = None,
    ):
        self._jsonl_path: str = jsonl_path or _default_stream_path()
        self._logger: logging.Logger = stdout_logger or logger
        self._lock = threading.Lock()
        # 确保父目录存在
        Path(self._jsonl_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def jsonl_path(self) -> str:
        return self._jsonl_path

    def log_event(
        self,
        component: str,
        event_type: str,
        payload: Dict[str, Any],
        self_model_version: str = "",
    ) -> Dict[str, Any]:
        """记录一条意识事件。

        Args:
            component: 来源子系统名（如 ``psi``、``meta_cognitive``、
                ``self_model``、``gws``、``memory``、``causal``）。
            event_type: 事件类型（如 ``decision``、``reflection``、
                ``update``、``broadcast``）。
            payload: 事件具体内容字典（任意 JSON 可序列化字段）。
            self_model_version: 关联的自我模型版本标识。

        Returns:
            实际写入的事件字典（含 ``timestamp``）。
        """
        event = {
            "timestamp": time.time(),
            "component": str(component),
            "event_type": str(event_type),
            "payload": payload if isinstance(payload, dict) else {"value": payload},
            "self_model_version": str(self_model_version),
        }

        line = json.dumps(event, ensure_ascii=False, default=str)

        # 1. stdout 通道（结构化 JSON 一行）
        try:
            self._logger.info(line)
        except Exception:  # pragma: no cover
            pass

        # 2. JSONL 文件通道（追加模式，线程安全）
        try:
            with self._lock:
                with open(self._jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as e:  # pragma: no cover
            logger.warning(f"[ConsciousnessStream] 写入 JSONL 失败: {e}")

        return event

    def flush(self) -> None:
        """兼容接口 — Python ``open`` 默认行缓冲，无需显式 flush。"""
        return None


# ═════════════════════════════════════════════════════════════════
# 单例工厂
# ═════════════════════════════════════════════════════════════════

_singleton_lock = threading.Lock()
_singleton_instance: Optional[ConsciousnessStream] = None


def get_consciousness_stream() -> ConsciousnessStream:
    """获取全局 ``ConsciousnessStream`` 单例。

    首次调用时按 ``LAAP_HOME`` 推导路径并实例化，
    后续调用返回同一实例。

    Returns:
        全局唯一的 ``ConsciousnessStream`` 实例。
    """
    global _singleton_instance
    if _singleton_instance is None:
        with _singleton_lock:
            if _singleton_instance is None:
                _singleton_instance = ConsciousnessStream()
                logger.info(
                    f"[ConsciousnessStream] 单例已初始化, "
                    f"jsonl={_singleton_instance.jsonl_path}"
                )
    return _singleton_instance


def reset_consciousness_stream() -> None:
    """重置单例（主要用于测试隔离）。"""
    global _singleton_instance
    with _singleton_lock:
        _singleton_instance = None
