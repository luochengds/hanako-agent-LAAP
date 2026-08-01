"""Triphase Memory Bridge — 将 CRM 复谐振记忆封装为 LAAP 服务。"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from triphase.memory import ComplexResonantMemory, MemoryItem

from .codec import triphase_to_dict
from .encoder import TextEncoder
from .topics import TriphaseTopic

logger = logging.getLogger(__name__)


class TriphaseMemoryService:
    """CRM 记忆服务封装。

    职责：
    - 把文本/上下文编码为复向量后写入 CRM
    - 按查询向量检索记忆，返回带三值态的结果
    - 在记忆巩固迁移时发布事件
    """

    def __init__(
        self,
        encoder: TextEncoder,
        dim: int | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.encoder = encoder
        self.dim = dim or encoder.dim
        self.memory = ComplexResonantMemory(dim=self.dim)
        self.on_event = on_event
        self.memory.on_consolidated = self._on_consolidated

    # ------------------------------------------------------------------ 写入

    def store(
        self,
        text: str,
        payload: Any = None,
        key: str | None = None,
        initial_evidence: float = 0.0,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        """存储一条文本记忆。

        当调用方没有提供 payload 或 tags 时，直接以 text 作为 payload，
        保证 CRM 的 warnings() 等机制能输出可读文本。
        """
        vector = self.encoder.encode(text)
        if payload is None and not tags:
            final_payload = text
        else:
            final_payload = {
                "text": text,
                "payload": payload,
                "tags": tags or [],
            }
        item = self.memory.store(
            vector=vector,
            payload=final_payload,
            key=key,
            initial_evidence=initial_evidence,
        )
        logger.debug("Triphase 存储记忆 %s (state=%s)", item.key, item.state.name)
        return item

    def consolidate(self, key: str, evidence: float) -> MemoryItem:
        """对已有记忆追加证据。"""
        return self.memory.consolidate(key, evidence)

    # ------------------------------------------------------------------ 检索

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 1e-9,
    ) -> list[dict[str, Any]]:
        """检索与查询文本最相关的记忆，返回 JSON-safe 列表。"""
        vector = self.encoder.encode(query)
        results = self.memory.retrieve(vector, top_k=top_k, min_score=min_score)
        return [triphase_to_dict(r) for r in results]

    def warnings(self, query: str, max_warnings: int = 3) -> list[str]:
        """返回负相位抗体警告（已证伪记忆的提示）。"""
        vector = self.encoder.encode(query)
        return self.memory.warnings(vector, max_warnings=max_warnings)

    # ------------------------------------------------------------------ 事件

    def _on_consolidated(self, item: MemoryItem) -> None:
        """记忆状态迁移时发布事件。"""
        if self.on_event is None:
            return
        self.on_event(
            TriphaseTopic.MEMORY_CONSOLIDATED,
            {
                "key": item.key,
                "state": triphase_to_dict(item.state),
                "strength": float(item.strength),
                "payload": item.payload,
            },
        )

    # ------------------------------------------------------------------ 工具方法

    def stats(self) -> dict[str, Any]:
        """返回记忆库统计。"""
        return self.memory.stats()

    def get(self, key: str) -> MemoryItem | None:
        return self.memory.get(key)

    def decay(self, dt: float) -> int:
        """触发去相干遗忘。"""
        return self.memory.decay(dt)
