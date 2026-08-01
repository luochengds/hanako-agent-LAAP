"""
LAAP — LongTermMemory × 遗忘引擎集成层

把 LongTermMemory（SQLite 存储）接入遗忘引擎与夜间认知周期：

    1. schema 迁移：long_term_memories 表增加三列
         lifecycle         — active / dormant / archived
         activation_value  — ACT-R 激活值（0~1）
         access_times      — 历史访问时间戳 JSON（用于激活值计算）
    2. 生命周期感知的存储子类：store 时初始化生命周期；
       get/search/recall 命中时记录访问；默认过滤 archived。
    3. loader/saver 适配器：遗忘引擎与夜间周期可直接消费。
    4. attach_nightly_cycle()：一键装配 巩固→反思→遗忘 全周期。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .long_term import LongTermMemory, MemoryEntry, ProceduralMemory
from .forgetting.activation import ActivationCalculator
from .forgetting.engine import ForgettingEngine
from .forgetting.lifecycle import MemoryLifecycle
from .consolidation import ConsolidationEngine
from .nightly_cycle import NightlyCycleScheduler

logger = logging.getLogger("laap.memory.lifecycle_integration")

# 访问历史上限（防止无限膨胀）
_MAX_ACCESS_HISTORY = 100


def migrate_schema(ltm: LongTermMemory) -> bool:
    """给 long_term_memories 表增加生命周期列（幂等）。"""
    with ltm._lock:
        cols = {row["name"] for row in ltm._conn.execute("PRAGMA table_info(long_term_memories)")}
        added = False
        if "lifecycle" not in cols:
            ltm._conn.execute(
                "ALTER TABLE long_term_memories ADD COLUMN lifecycle TEXT DEFAULT 'active'"
            )
            added = True
        if "activation_value" not in cols:
            ltm._conn.execute(
                "ALTER TABLE long_term_memories ADD COLUMN activation_value REAL DEFAULT 0.5"
            )
            added = True
        if "access_times" not in cols:
            ltm._conn.execute(
                "ALTER TABLE long_term_memories ADD COLUMN access_times TEXT DEFAULT '[]'"
            )
            added = True
        if added:
            ltm._conn.commit()
            logger.info("LongTermMemory schema migrated: lifecycle columns added")
    return added


class LifecycleAwareLongTermMemory(LongTermMemory):
    """生命周期感知的长期记忆存储。"""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        super().__init__(db_path)
        migrate_schema(self)
        self.calculator = ActivationCalculator()

    # ── 写入：初始化生命周期 ─────────────────────────────────
    def store(self, entry: Union[MemoryEntry, ProceduralMemory],
              user_id: str = "default") -> str:
        # 为新记忆计算初始激活值（基于创建时刻）
        now = time.time()
        activation = self.calculator.activation(
            access_times=[now],
            importance=entry.importance,
            valence=entry.emotional_valence,
            now=now,
        )
        with self._lock:
            embedding_blob = self._serialize_embedding(entry.embedding)
            self._conn.execute("""
                INSERT OR REPLACE INTO long_term_memories (
                    id, content, type, title, description, tags,
                    emotional_valence, importance, confidence, source,
                    created_at, accessed_at, last_modified_at, access_count,
                    embedding, metadata, user_id,
                    lifecycle, activation_value, access_times
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id, entry.content, entry.memory_type, entry.title,
                entry.description, json.dumps(entry.tags),
                entry.emotional_valence, entry.importance, entry.confidence,
                entry.source, entry.created_at, entry.accessed_at,
                entry.last_modified_at, entry.access_count,
                embedding_blob, json.dumps(entry.metadata), user_id,
                MemoryLifecycle.ACTIVE.value, activation,
                json.dumps([entry.created_at]),
            ))
            if isinstance(entry, ProceduralMemory):
                self._conn.execute(
                    "DELETE FROM procedural_steps WHERE memory_id = ?", (entry.id,))
                for idx, step in enumerate(entry.steps):
                    self._conn.execute("""
                        INSERT INTO procedural_steps (
                            memory_id, step_index, action, parameters,
                            expected_result, success_rate
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (entry.id, idx, step.action, json.dumps(step.parameters),
                          step.expected_result, step.success_rate))
            self._update_fts_index(entry.id, entry)
            self._conn.commit()
        return entry.id

    # ── 行解析：附加生命周期属性 ─────────────────────────────
    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        entry = super()._row_to_entry(row)
        try:
            entry.lifecycle = row["lifecycle"]
            entry.activation_value = row["activation_value"]
            entry.access_times = json.loads(row["access_times"] or "[]")
        except (KeyError, TypeError, json.JSONDecodeError):
            entry.lifecycle = MemoryLifecycle.ACTIVE.value
            entry.activation_value = 0.5
            entry.access_times = []
        return entry

    # ── 访问记录：追加时间戳 + 更新激活值 ─────────────────────
    def record_access(self, memory_id: str) -> None:
        """记录一次访问：追加时间戳、更新激活值。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM long_term_memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return
            entry = self._row_to_entry(row)
            times = list(entry.access_times) + [time.time()]
            times = times[-_MAX_ACCESS_HISTORY:]
            activation = self.calculator.activation(
                access_times=times,
                importance=entry.importance,
                valence=entry.emotional_valence,
                now=time.time(),
            )
            self._conn.execute("""
                UPDATE long_term_memories
                SET access_count = access_count + 1, accessed_at = ?,
                    access_times = ?, activation_value = ?
                WHERE id = ?
            """, (time.time(), json.dumps(times), activation, memory_id))
            self._conn.commit()

    # ── 检索：默认过滤 archived，命中记录访问 ────────────────
    def search(self, query: str, limit: int = 10,
               memory_type: Optional[str] = None,
               user_id: str = "default",
               include_archived: bool = False) -> List[MemoryEntry]:
        with self._lock:
            like_pattern = f"%{query}%"
            sql = """
                SELECT * FROM long_term_memories
                WHERE user_id = ? AND (content LIKE ? OR title LIKE ?)
            """
            params = [user_id, like_pattern, like_pattern]
            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)
            if not include_archived:
                sql += " AND lifecycle != 'archived'"
            sql += " ORDER BY activation_value DESC, accessed_at DESC LIMIT ?"
            params.append(limit)

            cur = self._conn.execute(sql, params)
            entries = [self._row_to_entry(row) for row in cur.fetchall()]
            self._conn.commit()

        for entry in entries:
            self.record_access(entry.id)
        return entries

    def recall(self, limit: int = 10, memory_type: Optional[str] = None,
               min_importance: float = 0.0, user_id: str = "default",
               sort_by: str = "relevance",
               include_archived: bool = False) -> List[MemoryEntry]:
        """召回记忆：按激活值 × 相关性排序（默认过滤归档）。"""
        with self._lock:
            sql = """
                SELECT * FROM long_term_memories
                WHERE user_id = ? AND importance >= ?
            """
            params = [user_id, min_importance]
            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)
            if not include_archived:
                sql += " AND lifecycle != 'archived'"
            if sort_by == "importance":
                sql += " ORDER BY importance DESC, activation_value DESC"
            elif sort_by == "recency":
                sql += " ORDER BY created_at DESC"
            else:
                sql += " ORDER BY activation_value DESC, accessed_at DESC"
            sql += " LIMIT ?"
            params.append(limit)
            cur = self._conn.execute(sql, params)
            entries = [self._row_to_entry(row) for row in cur.fetchall()]
            self._conn.commit()

        for entry in entries:
            self.record_access(entry.id)
        return entries

    def semantic_search(self, query: str, limit: int = 10,
                        memory_type: Optional[str] = None,
                        user_id: str = "default",
                        include_archived: bool = False):
        """语义搜索：默认过滤归档（embedding 命中后按激活值加权）。"""
        results = super().semantic_search(query, limit * 3, memory_type, user_id)
        filtered = []
        for entry, sim in results:
            if not include_archived and getattr(entry, "lifecycle", "active") == "archived":
                continue
            # 激活值加权相似度：0.7*sim + 0.3*activation
            activation = getattr(entry, "activation_value", 0.5)
            weighted = 0.7 * sim + 0.3 * activation
            filtered.append((entry, weighted))
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[:limit]

    def get(self, memory_id: str, user_id: str = "default") -> Optional[MemoryEntry]:
        entry = super().get(memory_id, user_id)
        if entry:
            self.record_access(memory_id)
        return entry

    # ── 生命周期工具 ─────────────────────────────────────────
    def get_lifecycle_stats(self) -> Dict[str, int]:
        """各生命周期记忆数量统计。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT lifecycle, COUNT(*) FROM long_term_memories GROUP BY lifecycle"
            ).fetchall()
            return {r[0]: r[1] for r in rows}

    def revive(self, memory_id: str) -> bool:
        """显式唤醒一条归档记忆。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM long_term_memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return False
            entry = self._row_to_entry(row)
            times = list(entry.access_times) + [time.time()]
            activation = self.calculator.activation(
                access_times=times[-_MAX_ACCESS_HISTORY:],
                importance=entry.importance,
                valence=entry.emotional_valence,
                now=time.time(),
            )
            self._conn.execute("""
                UPDATE long_term_memories
                SET lifecycle = 'active', activation_value = ?, access_times = ?
                WHERE id = ?
            """, (activation, json.dumps(times), memory_id))
            self._conn.commit()
            return True


# ──────────────────────────────────────────────────────────────
# 遗忘引擎 / 夜间周期 适配器
# ──────────────────────────────────────────────────────────────

def memory_loader(ltm: LongTermMemory) -> List[Dict[str, Any]]:
    """加载全部记忆为遗忘引擎可消费的 dict 列表。"""
    with ltm._lock:
        rows = ltm._conn.execute(
            "SELECT * FROM long_term_memories"
        ).fetchall()
    out = []
    for row in rows:
        try:
            entry = ltm._row_to_entry(row)
        except Exception:
            continue
        out.append({
            "id": entry.id,
            "memory_type": entry.memory_type,
            "importance": entry.importance,
            "valence": entry.emotional_valence,
            "created_at": entry.created_at,
            "access_times": getattr(entry, "access_times", [entry.created_at]),
            "lifecycle": getattr(entry, "lifecycle", MemoryLifecycle.ACTIVE.value),
        })
    return out


def memory_saver(ltm: LongTermMemory) -> Callable[[List[Dict[str, Any]]], None]:
    """生成保存器：把评估后的 lifecycle/activation 写回数据库。"""
    def saver(memories: List[Dict[str, Any]]) -> None:
        with ltm._lock:
            for m in memories:
                ltm._conn.execute("""
                    UPDATE long_term_memories
                    SET lifecycle = ?, activation_value = ?
                    WHERE id = ?
                """, (m.get("lifecycle", "active"),
                      m.get("activation_value", 0.5),
                      m.get("id", "")))
            ltm._conn.commit()
    return saver


def attach_nightly_cycle(
    ltm: LifecycleAwareLongTermMemory,
    reflection_fn: Optional[Callable[[], Any]] = None,
    self_review_fn: Optional[Callable[[], Any]] = None,
    log_path: Optional[Path] = None,
    interval_seconds: float = 86400.0,
) -> NightlyCycleScheduler:
    """一键装配：巩固 → 反思 → 遗忘 → 自我审视 的夜间周期。

    用法：
        ltm = LifecycleAwareLongTermMemory("mem.db")
        cycle = attach_nightly_cycle(
            ltm,
            reflection_fn=my_reflection,
            self_review_fn=SelfInspectionEngine().review_nightly,
        )
        cycle.start()
    """
    cons = ConsolidationEngine()
    forget = ForgettingEngine()

    loader = lambda: memory_loader(ltm)
    saver = memory_saver(ltm)

    def _forget_and_save():
        """遗忘扫描 + 把 lifecycle 结果写回数据库。"""
        mems = loader()
        audit = forget.scan(mems, apply=True)
        saver(mems)
        return audit

    cycle = NightlyCycleScheduler(
        consolidation_fn=cons.run_consolidation,
        reflection_fn=reflection_fn,
        forgetting_fn=_forget_and_save,
        self_review_fn=self_review_fn,
        memory_loader=loader,
        memory_saver=saver,
        log_path=log_path or (Path(ltm._db_path).parent / "nightly_cycle.log"),
        interval_seconds=interval_seconds,
    )
    return cycle
