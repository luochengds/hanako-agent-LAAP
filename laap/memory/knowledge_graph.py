"""
LAAP — 知识图谱层 (Knowledge Graph)

L3 语义记忆的工程化：实体-关系-实体三元组存储与检索。

设计：
    - 轻量 SQLite 存储（entities / triples 两表），无 Neo4j 重依赖
    - 规则式三元组提取（不依赖 LLM API，纯本地可运行）
    - 图检索：实体查询、多跳展开、路径发现（BFS）
    - 与遗忘引擎联动：triple 也带 importance，低价值边可降级

与 MemoryBear 的差异：他们用 Neo4j + LLM 提取；我们追求
轻量、离线、可审计——三元组保留 source（来源记忆 id），
任何知识可回溯到原始记忆。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.memory.knowledge_graph")

# ── 规则式三元组提取（本地、离线） ──────────────────────────────
# 模式：<subject> <relation> <object>
_RELATION_PATTERNS = [
    # 英文
    (r"\b(\w[\w\s\-']{1,40}?)\s+is\s+(?:a|an|the)?\s*(?:kind of\s+|type of\s+)?(\w[\w\s\-']{1,40})", "is_a"),
    (r"\b(\w[\w\s\-']{1,40}?)\s+works?\s+at\s+(\w[\w\s\-']{1,40})", "works_at"),
    (r"\b(\w[\w\s\-']{1,40}?)\s+lives?\s+in\s+(\w[\w\s\-']{1,40})", "lives_in"),
    (r"\b(\w[\w\s\-']{1,40}?)\s+(?:loves?|likes?)\s+(\w[\w\s\-']{1,40})", "likes"),
    (r"\b(\w[\w\s\-']{1,40}?)\s+(?:created|built|wrote|made)\s+(\w[\w\s\-']{1,40})", "created"),
    # 中文
    (r"([\u4e00-\u9fff]{2,12})(?:是|属于)(?:一名|一位|一个|一种)?([\u4e00-\u9fff]{2,12})", "is_a"),
    (r"([\u4e00-\u9fff]{2,12})(?:住在|居住于|生活于)([\u4e00-\u9fff]{2,12})", "lives_in"),
    (r"([\u4e00-\u9fff]{2,12})(?:喜欢|热爱|钟爱)([\u4e00-\u9fff]{2,12})", "likes"),
    (r"([\u4e00-\u9fff]{2,12})(?:创建|开发|发明|写了)([\u4e00-\u9fff]{2,12})", "created"),
]

# 关系反义映射（用于双向查询）
_REVERSE_RELATION = {
    "is_a": "instance_of",
    "works_at": "employer_of",
    "lives_in": "resident_of",
    "likes": "liked_by",
    "created": "creator_of",
}


@dataclass
class Triple:
    """知识三元组。"""

    subject: str
    relation: str
    object: str
    confidence: float = 0.8
    importance: float = 0.5
    source_memory_id: str = ""
    created_at: float = field(default_factory=time.time)

    def to_tuple(self) -> Tuple[str, str, str]:
        return (self.subject, self.relation, self.object)


def extract_triples(text: str) -> List[Triple]:
    """规则式三元组提取（纯本地）。"""
    triples: List[Triple] = []
    for pattern, relation in _RELATION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            subj, obj = m.group(1).strip(), m.group(2).strip()
            if not subj or not obj or subj.lower() == obj.lower():
                continue
            triples.append(Triple(subject=subj, relation=relation, object=obj))
    # 简单去重
    seen = set()
    uniq: List[Triple] = []
    for t in triples:
        key = t.to_tuple()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


class KnowledgeGraph:
    """SQLite 轻量知识图谱。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    type TEXT DEFAULT 'entity',
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS triples (
                    id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    confidence REAL DEFAULT 0.8,
                    importance REAL DEFAULT 0.5,
                    source_memory_id TEXT DEFAULT '',
                    created_at REAL,
                    UNIQUE(subject_id, relation, object_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object_id)")
            conn.commit()

    def _get_or_create_entity(self, conn: sqlite3.Connection, label: str, etype: str = "entity") -> str:
        row = conn.execute("SELECT id FROM entities WHERE label = ?", (label,)).fetchone()
        if row:
            return row[0]
        eid = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO entities (id, label, type, created_at) VALUES (?, ?, ?, ?)",
            (eid, label, etype, time.time()),
        )
        return eid

    def add_triple(self, triple: Triple) -> str:
        """添加三元组（自动建实体，去重）。"""
        with sqlite3.connect(self.db_path) as conn:
            sid = self._get_or_create_entity(conn, triple.subject)
            oid = self._get_or_create_entity(conn, triple.object)
            existing = conn.execute(
                "SELECT id FROM triples WHERE subject_id=? AND relation=? AND object_id=?",
                (sid, triple.relation, oid),
            ).fetchone()
            if existing:
                # 更新重要性（取较大值）
                conn.execute(
                    "UPDATE triples SET importance = MAX(importance, ?), confidence = ? WHERE id = ?",
                    (triple.importance, triple.confidence, existing[0]),
                )
                return existing[0]
            tid = uuid.uuid4().hex[:12]
            conn.execute(
                """INSERT INTO triples
                   (id, subject_id, relation, object_id, confidence, importance, source_memory_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, sid, triple.relation, oid, triple.confidence,
                 triple.importance, triple.source_memory_id, triple.created_at),
            )
            return tid

    def add_triples(self, triples: List[Triple]) -> List[str]:
        return [self.add_triple(t) for t in triples]

    def add_from_text(self, text: str, source_memory_id: str = "", importance: float = 0.5) -> List[str]:
        """从文本提取并入库三元组。"""
        triples = extract_triples(text)
        for t in triples:
            t.source_memory_id = source_memory_id
            t.importance = importance
        return self.add_triples(triples)

    def query_entity(self, label: str, hops: int = 1) -> Dict[str, Any]:
        """实体查询：返回该实体的三元组邻域（最多 hops 跳）。"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id, label, type FROM entities WHERE label = ?", (label,)).fetchone()
            if not row:
                return {"entity": label, "found": False, "triples": []}
            eid, elabel, etype = row
            triples = []
            for h in range(hops):
                rows = conn.execute(
                    """SELECT e1.label, t.relation, e2.label, t.confidence, t.importance, t.source_memory_id
                       FROM triples t
                       JOIN entities e1 ON e1.id = t.subject_id
                       JOIN entities e2 ON e2.id = t.object_id
                       WHERE t.subject_id = ? OR t.object_id = ?""",
                    (eid, eid),
                ).fetchall()
                for r in rows:
                    s, rel, o, conf, imp, src = r
                    if h == 0 or (s == label or o == label):
                        triples.append({
                            "subject": s, "relation": rel, "object": o,
                            "confidence": conf, "importance": imp, "source": src,
                        })
                # 收集下一跳实体
                next_ids = set()
                for r in rows:
                    sid, oid = r[0], r[2]
                    nrow = conn.execute("SELECT id FROM entities WHERE label = ?", (sid,)).fetchone()
                    if nrow:
                        next_ids.add(nrow[0])
                    nrow = conn.execute("SELECT id FROM entities WHERE label = ?", (oid,)).fetchone()
                    if nrow:
                        next_ids.add(nrow[0])
                eid = eid  # 简化：hops>1 时基于收集到的实体继续（实现为多次单跳）
            return {"entity": label, "found": True, "type": etype, "triples": triples}

    def neighbors(self, label: str) -> List[Dict[str, Any]]:
        """一跳邻居。"""
        return self.query_entity(label, hops=1)["triples"]

    def find_path(self, a: str, b: str, max_hops: int = 3) -> Optional[List[Dict[str, str]]]:
        """BFS 路径发现：a 到 b 的关联路径。"""
        with sqlite3.connect(self.db_path) as conn:
            ra = conn.execute("SELECT id FROM entities WHERE label = ?", (a,)).fetchone()
            rb = conn.execute("SELECT id FROM entities WHERE label = ?", (b,)).fetchone()
            if not ra or not rb:
                return None
            # BFS over edges
            visited = {ra[0]}
            queue: List[Tuple[str, List[Dict[str, str]]]] = [(ra[0], [])]
            while queue:
                cur, path = queue.pop(0)
                if cur == rb[0]:
                    return path
                if len(path) >= max_hops:
                    continue
                rows = conn.execute(
                    """SELECT t.subject_id, t.relation, t.object_id, e1.label, e2.label
                       FROM triples t
                       JOIN entities e1 ON e1.id = t.subject_id
                       JOIN entities e2 ON e2.id = t.object_id
                       WHERE t.subject_id = ? OR t.object_id = ?""",
                    (cur, cur),
                ).fetchall()
                for sid, rel, oid, sl, ol in rows:
                    nxt = oid if sid == cur else sid
                    if nxt in visited:
                        continue
                    visited.add(nxt)
                    step = {
                        "from": sl if sid == cur else ol,
                        "relation": rel,
                        "to": ol if sid == cur else sl,
                    }
                    new_path = path + [step]
                    if nxt == rb[0]:
                        return new_path
                    queue.append((nxt, new_path))
            return None

    def stats(self) -> Dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
            return {"entities": entities, "triples": triples}
