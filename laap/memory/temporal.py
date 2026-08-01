"""
LAAP — 时间锚定模块 (Temporal Anchoring)

给记忆条目赋予事件时间语义，让记忆能回答"什么时候"：

    valid_at   — 事件发生时间（unix 时间戳或 None）
    invalid_at — 事件失效时间（如"搬家后旧地址不再有效"）
    temporal_type:
        STATIC    — 静态事实（"Lorry 是顶级程序员"）
        DYNAMIC   — 动态事实，随时间变化（"Lorry 住在上海"）
        ATEMPORAL — 无时间属性

时间感知检索：按时间窗口过滤、时间线重建、时间排序。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class TemporalType:
    STATIC = "static"
    DYNAMIC = "dynamic"
    ATEMPORAL = "atemporal"


@dataclass
class TemporalAnchor:
    """记忆的时间锚。"""

    valid_at: Optional[float] = None       # 生效时间（unix）
    invalid_at: Optional[float] = None     # 失效时间（unix，None=仍有效）
    temporal_type: str = TemporalType.STATIC
    source_text: str = ""                  # 原始时间表述（"上个月"、"2023年5月"）
    confidence: float = 0.8

    def is_active(self, now: Optional[float] = None) -> bool:
        """当前是否有效（valid_at <= now < invalid_at）。"""
        now = now or time.time()
        if self.valid_at and now < self.valid_at:
            return False
        if self.invalid_at and now >= self.invalid_at:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "temporal_type": self.temporal_type,
            "source_text": self.source_text,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalAnchor":
        return cls(
            valid_at=data.get("valid_at"),
            invalid_at=data.get("invalid_at"),
            temporal_type=data.get("temporal_type", TemporalType.STATIC),
            source_text=data.get("source_text", ""),
            confidence=data.get("confidence", 0.8),
        )


def anchor_entry(
    valid_at: Optional[float] = None,
    invalid_at: Optional[float] = None,
    temporal_type: str = TemporalType.STATIC,
    source_text: str = "",
    confidence: float = 0.8,
) -> Dict[str, Any]:
    """生成时间锚补丁：返回应合并进 entry.metadata 的 dict。

    用法：
        entry.metadata.update(anchor_entry(valid_at=..., source_text="..."))
    """
    anchor = TemporalAnchor(
        valid_at=valid_at,
        invalid_at=invalid_at,
        temporal_type=temporal_type,
        source_text=source_text,
        confidence=confidence,
    )
    return {"temporal": anchor.to_dict()}


def get_anchor(entry: Any) -> Optional[TemporalAnchor]:
    """从记忆条目取出时间锚（无则 None）。"""
    meta = getattr(entry, "metadata", None) or {}
    raw = meta.get("temporal")
    if not raw:
        return None
    return TemporalAnchor.from_dict(raw)


def filter_active(
    entries: List[Any],
    now: Optional[float] = None,
    include_unanchored: bool = True,
) -> List[Any]:
    """只保留当前时间有效的记忆（无锚记忆默认保留）。"""
    now = now or time.time()
    out = []
    for e in entries:
        anchor = get_anchor(e)
        if anchor is None:
            if include_unanchored:
                out.append(e)
            continue
        if anchor.is_active(now):
            out.append(e)
    return out


def filter_by_time_window(
    entries: List[Any],
    start: Optional[float] = None,
    end: Optional[float] = None,
) -> List[Any]:
    """按事件时间窗口过滤：valid_at 落在 [start, end) 内。"""
    out = []
    for e in entries:
        anchor = get_anchor(e)
        if anchor is None or anchor.valid_at is None:
            continue
        if start and anchor.valid_at < start:
            continue
        if end and anchor.valid_at >= end:
            continue
        out.append(e)
    return out


def sort_by_time(entries: List[Any], reverse: bool = False) -> List[Any]:
    """按 valid_at 时间排序（无锚记忆排最后）。"""
    def key(e: Any) -> float:
        anchor = get_anchor(e)
        if anchor is None or anchor.valid_at is None:
            return float("-inf") if not reverse else float("inf")
        return anchor.valid_at
    return sorted(entries, key=key, reverse=reverse)


def build_timeline(entries: List[Any]) -> List[Dict[str, Any]]:
    """重建记忆时间线：按时间排序的事件列表（含锚信息）。"""
    sorted_entries = sort_by_time(entries)
    timeline = []
    for e in sorted_entries:
        anchor = get_anchor(e)
        content = getattr(e, "content", str(e))
        timeline.append({
            "content": content[:120],
            "valid_at": anchor.valid_at if anchor else None,
            "invalid_at": anchor.invalid_at if anchor else None,
            "temporal_type": anchor.temporal_type if anchor else None,
        })
    return timeline
