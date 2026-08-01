"""
LAAP — 多模态记忆通道 (Multimodal Memory)

视觉/音频/文本记忆的存储与检索。与 MemoryBear 的 PerceptualType
对齐，但保持轻量：只存元数据 + 摘要，原始文件由外部存储负责。

模态：
    vision  — 视觉记忆（图片/视频帧）
    audio   — 听觉记忆（语音片段/音乐）
    text    — 文本记忆（文档/对话摘录）
    conversation — 会话记忆（完整对话事件）

每条多模态记忆可携带时间锚（对接 temporal.py）与情感标签，
并可被遗忘引擎评估（importance 参与生命周期）。
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class Modality:
    VISION = "vision"
    AUDIO = "audio"
    TEXT = "text"
    CONVERSATION = "conversation"


@dataclass
class MultimodalMemory:
    """多模态记忆条目。"""

    modality: str
    summary: str
    file_path: str = ""
    file_name: str = ""
    file_ext: str = ""
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)   # 模态细节（分辨率/时长等）
    emotional_valence: float = 0.0
    importance: float = 0.5
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "modality": self.modality,
            "summary": self.summary,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_ext": self.file_ext,
            "tags": self.tags,
            "meta": self.meta,
            "emotional_valence": self.emotional_valence,
            "importance": self.importance,
            "created_at": self.created_at,
        }


class MultimodalMemoryStore:
    """SQLite 多模态记忆存储。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS multimodal_memories (
                    id TEXT PRIMARY KEY,
                    modality TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    file_path TEXT DEFAULT '',
                    file_name TEXT DEFAULT '',
                    file_ext TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    meta TEXT DEFAULT '{}',
                    emotional_valence REAL DEFAULT 0.0,
                    importance REAL DEFAULT 0.5,
                    created_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mm_modality ON multimodal_memories(modality)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mm_created ON multimodal_memories(created_at)")
            conn.commit()

    def store(self, mem: MultimodalMemory) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO multimodal_memories
                   (id, modality, summary, file_path, file_name, file_ext,
                    tags, meta, emotional_valence, importance, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mem.id, mem.modality, mem.summary, mem.file_path, mem.file_name,
                 mem.file_ext, json.dumps(mem.tags), json.dumps(mem.meta),
                 mem.emotional_valence, mem.importance, mem.created_at),
            )
            conn.commit()
        return mem.id

    def _row_to_mem(self, row: tuple) -> MultimodalMemory:
        return MultimodalMemory(
            id=row[0], modality=row[1], summary=row[2], file_path=row[3],
            file_name=row[4], file_ext=row[5],
            tags=json.loads(row[6] or "[]"), meta=json.loads(row[7] or "{}"),
            emotional_valence=row[8], importance=row[9], created_at=row[10],
        )

    def search_by_modality(self, modality: str, limit: int = 20) -> List[MultimodalMemory]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM multimodal_memories WHERE modality = ? ORDER BY created_at DESC LIMIT ?",
                (modality, limit),
            ).fetchall()
            return [self._row_to_mem(r) for r in rows]

    def search_by_tags(self, tags: List[str], limit: int = 20) -> List[MultimodalMemory]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM multimodal_memories ORDER BY created_at DESC LIMIT 500"
            ).fetchall()
            out = []
            for r in rows:
                mem_tags = set(json.loads(r[6] or "[]"))
                if mem_tags & set(tags):
                    out.append(self._row_to_mem(r))
                    if len(out) >= limit:
                        break
            return out

    def search_keyword(self, keyword: str, limit: int = 20) -> List[MultimodalMemory]:
        """摘要关键词模糊检索。"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM multimodal_memories WHERE summary LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
            return [self._row_to_mem(r) for r in rows]

    def get_timeline(self, limit: int = 50) -> List[MultimodalMemory]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM multimodal_memories ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_mem(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM multimodal_memories").fetchone()[0]
            by_modality = {}
            for m in (Modality.VISION, Modality.AUDIO, Modality.TEXT, Modality.CONVERSATION):
                by_modality[m] = conn.execute(
                    "SELECT COUNT(*) FROM multimodal_memories WHERE modality = ?", (m,)
                ).fetchone()[0]
            return {"total": total, "by_modality": by_modality}
