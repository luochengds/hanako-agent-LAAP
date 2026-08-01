"""
LAAP — Phase 2 长期记忆存储模块

实现基于层次化记忆理论的长期记忆系统，包括：
- 情景记忆 (Episodic Memory) - 存储事件序列
- 语义记忆 (Semantic Memory) - 存储知识事实
- 程序记忆 (Procedural Memory) - 存储技能和操作序列
- 向量检索 (Vector Retrieval) - 基于语义相似度的检索
- 情绪关联 (Emotional Linking) - 记忆与情绪状态的关联

关键特性：
1. 支持结构化记忆条目
2. 高效的全文搜索和语义检索
3. 情绪驱动的记忆巩固
4. 记忆衰减与强化机制
5. 与认知引擎的深度集成
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import json
import logging
import math
import sqlite3
import threading
import time
import uuid

import numpy as np

logger = logging.getLogger("laap.memory.long_term")


# ──────────────────────────────────────────────────────────────────────
# 记忆类型定义
# ──────────────────────────────────────────────────────────────────────

class MemoryType:
    """记忆类型枚举"""
    EPISODIC = "episodic"      # 情景记忆 - 事件和经历
    SEMANTIC = "semantic"       # 语义记忆 - 事实和知识
    PROCEDURAL = "procedural"   # 程序记忆 - 技能和步骤
    SKILL = "skill"             # 技能记忆 - 专业技能
    IDENTITY = "identity"       # 身份记忆 - 自我认知
    PREFERENCE = "preference"   # 偏好记忆 - 用户偏好


@dataclass
class MemoryEntry:
    """
    长期记忆条目
    
    包含完整的记忆元数据和内容
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str = ""
    memory_type: str = MemoryType.EPISODIC
    title: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    emotional_valence: float = 0.0  # 情绪效价 -1.0 到 1.0
    importance: float = 0.5         # 重要性 0.0 到 1.0
    confidence: float = 0.8         # 置信度 0.0 到 1.0
    source: str = "user"            # 来源
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    last_modified_at: float = field(default_factory=time.time)
    access_count: int = 0
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def age_days(self) -> float:
        """记忆存在的天数"""
        return (time.time() - self.created_at) / 86400.0
    
    @property
    def recall_probability(self) -> float:
        """
        Ebbinghaus 遗忘曲线计算的回忆概率
        
        recall_prob = e^(-days / decay_constant)
        decay_constant = 7 表示约7天后回忆概率降至约37%
        """
        decay_constant = 7.0
        return math.exp(-self.age_days / decay_constant)
    
    @property
    def relevance_score(self) -> float:
        """
        综合相关性分数 (0-1)
        
        权重分配：
        - 重要性: 40%
        - 新近度: 30%
        - 访问频率: 20%
        - 回忆概率: 10%
        """
        recency = math.exp(-self.age_days / 30.0)  # 30天半衰期
        frequency = min(1.0, self.access_count / 10.0)
        return (0.4 * self.importance + 
                0.3 * recency + 
                0.2 * frequency + 
                0.1 * self.recall_probability)
    
    def record_access(self):
        """记录一次访问"""
        self.access_count += 1
        self.accessed_at = time.time()
    
    def strengthen(self, amount: float = 0.1):
        """强化记忆（增加重要性）"""
        self.importance = min(1.0, self.importance + amount)
        self.last_modified_at = time.time()
    
    def weaken(self, amount: float = 0.05):
        """弱化记忆（减少重要性）"""
        self.importance = max(0.0, self.importance - amount)
        self.last_modified_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "type": self.memory_type,
            "title": self.title,
            "content": self.content[:200],
            "importance": round(self.importance, 3),
            "relevance": round(self.relevance_score, 3),
            "valence": round(self.emotional_valence, 3),
            "confidence": round(self.confidence, 3),
            "tags": self.tags,
            "source": self.source,
            "age_days": round(self.age_days, 1),
            "access_count": self.access_count,
            "metadata": self.metadata,
        }
    
    def to_prompt_block(self) -> str:
        """格式化为提示词块"""
        tag_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        title = f"「{self.title}」" if self.title else ""
        return f"- [{self.memory_type}]✨ {title}{self.content[:100]}{tag_str}"


@dataclass
class ProceduralStep:
    """程序记忆的步骤"""
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_result: Optional[str] = None
    success_rate: float = 0.5


@dataclass
class ProceduralMemory(MemoryEntry):
    """程序记忆 - 存储操作序列"""
    steps: List[ProceduralStep] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    
    @property
    def overall_success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.5
    
    def add_step(self, action: str, parameters: Optional[Dict] = None, 
                 expected_result: Optional[str] = None):
        """添加步骤"""
        self.steps.append(ProceduralStep(
            action=action,
            parameters=parameters or {},
            expected_result=expected_result
        ))
    
    def record_execution(self, success: bool):
        """记录执行结果"""
        if success:
            self.success_count += 1
            self.strengthen(0.05)
        else:
            self.fail_count += 1
            self.weaken(0.05)


# ──────────────────────────────────────────────────────────────────────
# 长期记忆存储引擎
# ──────────────────────────────────────────────────────────────────────

class LongTermMemory:
    """
    长期记忆存储引擎
    
    提供完整的长期记忆写入和检索接口，支持：
    1. 结构化记忆存储
    2. 全文搜索
    3. 语义向量检索
    4. 情绪关联检索
    5. 记忆巩固机制
    """
    
    _DECAY_THRESHOLD_DAYS = 90  # 90天未访问且低重要性的记忆会被清理
    _MIN_IMPORTANCE_FOR_DECAY = 0.3  # 低于此值的记忆可能被遗忘
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self._db_path = Path(db_path) if db_path else (Path.home() / ".laap" / "long_term.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._embedder = None
        
        self._connect()
        logger.info(f"长期记忆引擎初始化完成，存储路径: {self._db_path}")
    
    def _connect(self):
        """建立数据库连接并初始化表结构"""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
    
    def _init_schema(self):
        """初始化数据库表结构"""
        cur = self._conn.cursor()
        cur.executescript("""
            -- 主记忆表
            CREATE TABLE IF NOT EXISTS long_term_memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'episodic',
                title TEXT,
                description TEXT,
                tags TEXT DEFAULT '[]',
                emotional_valence REAL DEFAULT 0.0,
                importance REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'user',
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                last_modified_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                user_id TEXT DEFAULT 'default'
            );
            
            -- 程序记忆步骤表
            CREATE TABLE IF NOT EXISTS procedural_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                action TEXT NOT NULL,
                parameters TEXT DEFAULT '{}',
                expected_result TEXT,
                success_rate REAL DEFAULT 0.5,
                FOREIGN KEY(memory_id) REFERENCES long_term_memories(id) ON DELETE CASCADE
            );
            
            -- 全文搜索索引
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, title, type, tags, tokenize='unicode61');
            
            -- 索引
            CREATE INDEX IF NOT EXISTS idx_ltm_type ON long_term_memories(type);
            CREATE INDEX IF NOT EXISTS idx_ltm_user ON long_term_memories(user_id);
            CREATE INDEX IF NOT EXISTS idx_ltm_accessed ON long_term_memories(accessed_at);
            CREATE INDEX IF NOT EXISTS idx_ltm_importance ON long_term_memories(importance);
            CREATE INDEX IF NOT EXISTS idx_ps_memory ON procedural_steps(memory_id);
        """)
        self._conn.commit()
    
    # ──────────────────────────────────────────────────────────────
    # 写入接口
    # ──────────────────────────────────────────────────────────────
    
    def store(self, entry: Union[MemoryEntry, ProceduralMemory], 
              user_id: str = "default") -> str:
        """
        存储记忆条目
        
        参数:
            entry: MemoryEntry 或 ProceduralMemory 对象
            user_id: 用户标识
        
        返回:
            记忆条目的ID
        """
        with self._lock:
            # 存储主条目
            embedding_blob = self._serialize_embedding(entry.embedding)
            
            self._conn.execute("""
                INSERT OR REPLACE INTO long_term_memories (
                    id, content, type, title, description, tags,
                    emotional_valence, importance, confidence, source,
                    created_at, accessed_at, last_modified_at, access_count,
                    embedding, metadata, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id, entry.content, entry.memory_type, entry.title,
                entry.description, json.dumps(entry.tags),
                entry.emotional_valence, entry.importance, entry.confidence,
                entry.source, entry.created_at, entry.accessed_at,
                entry.last_modified_at, entry.access_count,
                embedding_blob, json.dumps(entry.metadata), user_id
            ))
            
            # 如果是程序记忆，存储步骤
            if isinstance(entry, ProceduralMemory):
                # 先删除旧步骤
                self._conn.execute(
                    "DELETE FROM procedural_steps WHERE memory_id = ?",
                    (entry.id,)
                )
                # 插入新步骤
                for idx, step in enumerate(entry.steps):
                    self._conn.execute("""
                        INSERT INTO procedural_steps (
                            memory_id, step_index, action, parameters,
                            expected_result, success_rate
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        entry.id, idx, step.action, json.dumps(step.parameters),
                        step.expected_result, step.success_rate
                    ))
            
            # 更新全文搜索索引
            self._update_fts_index(entry.id, entry)
            
            self._conn.commit()
        
        logger.debug(f"长期记忆存储成功: {entry.id[:8]} ({entry.memory_type})")
        return entry.id
    
    def store_episodic(self, content: str, title: Optional[str] = None,
                       tags: Optional[List[str]] = None, emotional_valence: float = 0.0,
                       importance: float = 0.5, source: str = "user",
                       user_id: str = "default") -> str:
        """
        快捷方法：存储情景记忆
        
        参数:
            content: 记忆内容
            title: 标题（可选）
            tags: 标签列表（可选）
            emotional_valence: 情绪效价（-1.0 到 1.0）
            importance: 重要性（0.0 到 1.0）
            source: 来源
            user_id: 用户标识
        
        返回:
            记忆条目的ID
        """
        entry = MemoryEntry(
            content=content,
            title=title,
            memory_type=MemoryType.EPISODIC,
            tags=tags or [],
            emotional_valence=emotional_valence,
            importance=importance,
            source=source,
        )
        # 生成嵌入向量
        entry.embedding = self._generate_embedding(content)
        return self.store(entry, user_id)
    
    def store_semantic(self, key: str, content: str,
                       tags: Optional[List[str]] = None, importance: float = 0.7,
                       confidence: float = 0.9, user_id: str = "default") -> str:
        """
        快捷方法：存储语义记忆（事实/知识）
        
        参数:
            key: 知识键（用于快速查找）
            content: 知识内容
            tags: 标签列表（可选）
            importance: 重要性
            confidence: 置信度
            user_id: 用户标识
        
        返回:
            记忆条目的ID
        """
        entry = MemoryEntry(
            content=content,
            title=key,
            memory_type=MemoryType.SEMANTIC,
            tags=tags or ["knowledge"],
            importance=importance,
            confidence=confidence,
            source="system"
        )
        entry.embedding = self._generate_embedding(content)
        return self.store(entry, user_id)
    
    def store_procedural(self, name: str, steps: List[Dict],
                        description: Optional[str] = None,
                        user_id: str = "default") -> str:
        """
        快捷方法：存储程序记忆（技能/操作序列）
        
        参数:
            name: 程序名称
            steps: 步骤列表，每个步骤包含 action 和可选的 parameters
            description: 描述（可选）
            user_id: 用户标识
        
        返回:
            记忆条目的ID
        """
        entry = ProceduralMemory(
            content=description or name,
            title=name,
            memory_type=MemoryType.PROCEDURAL,
            tags=["procedure", name.lower()],
            importance=0.6
        )
        
        for step in steps:
            entry.add_step(
                action=step.get("action", ""),
                parameters=step.get("parameters", {}),
                expected_result=step.get("expected_result")
            )
        
        return self.store(entry, user_id)
    
    def store_skill(self, name: str, description: str = "",
                    code: Optional[str] = None, proficiency: float = 0.0,
                    user_id: str = "default") -> str:
        """
        快捷方法：存储技能记忆
        
        参数:
            name: 技能名称
            description: 技能描述
            code: 技能代码（可选）
            proficiency: 熟练度（0.0 到 1.0）
            user_id: 用户标识
        
        返回:
            记忆条目的ID
        """
        entry = MemoryEntry(
            content=description,
            title=name,
            memory_type=MemoryType.SKILL,
            tags=["skill", name.lower()],
            importance=0.5 + proficiency * 0.3,
            metadata={"code": code, "proficiency": proficiency}
        )
        return self.store(entry, user_id)
    
    def update(self, memory_id: str, **kwargs) -> bool:
        """
        更新记忆条目
        
        参数:
            memory_id: 记忆ID
            **kwargs: 要更新的字段（content, title, importance, tags 等）
        
        返回:
            是否更新成功
        """
        with self._lock:
            set_clauses = []
            params = []
            
            if "content" in kwargs:
                set_clauses.append("content = ?")
                params.append(kwargs["content"])
            
            if "title" in kwargs:
                set_clauses.append("title = ?")
                params.append(kwargs["title"])
            
            if "importance" in kwargs:
                set_clauses.append("importance = ?")
                params.append(kwargs["importance"])
            
            if "tags" in kwargs:
                set_clauses.append("tags = ?")
                params.append(json.dumps(kwargs["tags"]))
            
            if "emotional_valence" in kwargs:
                set_clauses.append("emotional_valence = ?")
                params.append(kwargs["emotional_valence"])
            
            if "metadata" in kwargs:
                set_clauses.append("metadata = ?")
                params.append(json.dumps(kwargs["metadata"]))
            
            set_clauses.append("last_modified_at = ?")
            params.append(time.time())
            
            if not set_clauses:
                return False
            
            params.append(memory_id)
            
            sql = f"UPDATE long_term_memories SET {', '.join(set_clauses)} WHERE id = ?"
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            
            return cur.rowcount > 0
    
    def delete(self, memory_id: str) -> bool:
        """
        删除记忆条目
        
        参数:
            memory_id: 记忆ID
        
        返回:
            是否删除成功
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM long_term_memories WHERE id = ?",
                (memory_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0
    
    # ──────────────────────────────────────────────────────────────
    # 检索接口
    # ──────────────────────────────────────────────────────────────
    
    def get(self, memory_id: str, user_id: str = "default") -> Optional[MemoryEntry]:
        """
        根据ID获取记忆条目
        
        参数:
            memory_id: 记忆ID
            user_id: 用户标识
        
        返回:
            MemoryEntry 对象或 None
        """
        with self._lock:
            cur = self._conn.execute("""
                SELECT * FROM long_term_memories 
                WHERE id = ? AND user_id = ?
            """, (memory_id, user_id))
            
            row = cur.fetchone()
            if not row:
                return None
            
            entry = self._row_to_entry(row)
            
            # 更新访问计数
            self._conn.execute("""
                UPDATE long_term_memories 
                SET access_count = access_count + 1, accessed_at = ? 
                WHERE id = ?
            """, (time.time(), memory_id))
            self._conn.commit()
            
            entry.record_access()
            return entry
    
    def search(self, query: str, limit: int = 10,
               memory_type: Optional[str] = None,
               user_id: str = "default") -> List[MemoryEntry]:
        """
        全文搜索记忆
        
        参数:
            query: 搜索关键词
            limit: 返回数量限制
            memory_type: 记忆类型过滤（可选）
            user_id: 用户标识
        
        返回:
            MemoryEntry 列表
        """
        with self._lock:
            # 使用 LIKE 模糊匹配，兼容中英文混合文本
            # （FTS5 的 unicode61 分词器会将中英文混合文本视为单个 token，
            # 导致如 "创建React应用" 中的 "React" 无法被匹配）
            like_pattern = f"%{query}%"
            sql = """
                SELECT * FROM long_term_memories
                WHERE user_id = ? AND (content LIKE ? OR title LIKE ?)
            """
            params = [user_id, like_pattern, like_pattern]

            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)

            sql += " ORDER BY accessed_at DESC LIMIT ?"
            params.append(limit)

            cur = self._conn.execute(sql, params)
            entries = [self._row_to_entry(row) for row in cur.fetchall()]

            # 更新访问计数
            for entry in entries:
                entry.record_access()

            return entries
    
    def semantic_search(self, query: str, limit: int = 10,
                       memory_type: Optional[str] = None,
                       user_id: str = "default") -> List[Tuple[MemoryEntry, float]]:
        """
        语义相似度搜索（基于向量匹配）
        
        参数:
            query: 搜索查询
            limit: 返回数量限制
            memory_type: 记忆类型过滤（可选）
            user_id: 用户标识
        
        返回:
            (MemoryEntry, 相似度分数) 列表，按相似度降序排列
        """
        query_emb = self._generate_embedding(query)
        if not query_emb:
            return []
        
        with self._lock:
            sql = "SELECT * FROM long_term_memories WHERE user_id = ?"
            params = [user_id]
            
            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)
            
            cur = self._conn.execute(sql, params)
            results = []
            
            for row in cur.fetchall():
                entry = self._row_to_entry(row)
                if entry.embedding:
                    sim = self._cosine_similarity(query_emb, entry.embedding)
                    results.append((entry, sim))
            
            results.sort(key=lambda x: x[1], reverse=True)
            
            # 更新访问计数
            for entry, _ in results[:limit]:
                entry.record_access()
                self._conn.execute("""
                    UPDATE long_term_memories 
                    SET access_count = access_count + 1, accessed_at = ? 
                    WHERE id = ?
                """, (time.time(), entry.id))
            
            self._conn.commit()
            
            return results[:limit]
    
    def recall(self, limit: int = 10, memory_type: Optional[str] = None,
               min_importance: float = 0.0, user_id: str = "default",
               sort_by: str = "relevance") -> List[MemoryEntry]:
        """
        召回记忆（基于相关性排序）
        
        参数:
            limit: 返回数量限制
            memory_type: 记忆类型过滤（可选）
            min_importance: 最小重要性阈值
            user_id: 用户标识
            sort_by: 排序方式（relevance, importance, recency）
        
        返回:
            MemoryEntry 列表
        """
        with self._lock:
            sql = """
                SELECT * FROM long_term_memories 
                WHERE user_id = ? AND importance >= ?
            """
            params = [user_id, min_importance]
            
            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)
            
            # 基础排序
            if sort_by == "importance":
                sql += " ORDER BY importance DESC, accessed_at DESC"
            elif sort_by == "recency":
                sql += " ORDER BY created_at DESC"
            else:
                sql += " ORDER BY accessed_at DESC, importance DESC"
            
            sql += " LIMIT ?"
            params.append(limit)
            
            cur = self._conn.execute(sql, params)
            entries = [self._row_to_entry(row) for row in cur.fetchall()]
            
            # 如果按相关性排序，需要在内存中重新计算
            if sort_by == "relevance":
                entries.sort(key=lambda e: e.relevance_score, reverse=True)
            
            # 更新访问计数
            for entry in entries:
                entry.record_access()
                self._conn.execute("""
                    UPDATE long_term_memories 
                    SET access_count = access_count + 1, accessed_at = ? 
                    WHERE id = ?
                """, (time.time(), entry.id))
            
            self._conn.commit()
            
            return entries
    
    def recall_by_emotion(self, target_valence: float, tolerance: float = 0.3,
                         limit: int = 10, user_id: str = "default") -> List[MemoryEntry]:
        """
        根据情绪效价召回记忆
        
        参数:
            target_valence: 目标情绪效价（-1.0 到 1.0）
            tolerance: 容忍度
            limit: 返回数量限制
            user_id: 用户标识
        
        返回:
            MemoryEntry 列表，按情绪匹配度排序
        """
        with self._lock:
            cur = self._conn.execute("""
                SELECT * FROM long_term_memories 
                WHERE user_id = ? 
                AND emotional_valence BETWEEN ? AND ?
                ORDER BY ABS(emotional_valence - ?)
                LIMIT ?
            """, (user_id, 
                  target_valence - tolerance, 
                  target_valence + tolerance,
                  target_valence,
                  limit))
            
            entries = [self._row_to_entry(row) for row in cur.fetchall()]
            
            for entry in entries:
                entry.record_access()
            
            return entries
    
    def recall_recent(self, hours: int = 24, limit: int = 10,
                      user_id: str = "default") -> List[MemoryEntry]:
        """
        召回最近的记忆
        
        参数:
            hours: 时间范围（小时）
            limit: 返回数量限制
            user_id: 用户标识
        
        返回:
            MemoryEntry 列表
        """
        cutoff = time.time() - (hours * 3600)
        
        with self._lock:
            cur = self._conn.execute("""
                SELECT * FROM long_term_memories 
                WHERE user_id = ? AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, cutoff, limit))
            
            entries = [self._row_to_entry(row) for row in cur.fetchall()]
            return entries
    
    def search_by_tags(self, tags: List[str], limit: int = 20,
                       user_id: str = "default") -> List[MemoryEntry]:
        """
        根据标签搜索记忆
        
        参数:
            tags: 标签列表
            limit: 返回数量限制
            user_id: 用户标识
        
        返回:
            MemoryEntry 列表
        """
        with self._lock:
            results = []
            seen = set()
            
            for tag in tags:
                cur = self._conn.execute("""
                    SELECT * FROM long_term_memories 
                    WHERE user_id = ? AND tags LIKE ?
                    ORDER BY importance DESC
                    LIMIT ?
                """, (user_id, f'%{tag}%', limit))
                
                for row in cur.fetchall():
                    entry = self._row_to_entry(row)
                    if entry.id not in seen:
                        seen.add(entry.id)
                        results.append(entry)
            
            results.sort(key=lambda e: e.relevance_score, reverse=True)
            return results[:limit]
    
    def get_procedural(self, memory_id: str, user_id: str = "default") -> Optional[ProceduralMemory]:
        """
        获取程序记忆（包含步骤）
        
        参数:
            memory_id: 记忆ID
            user_id: 用户标识
        
        返回:
            ProceduralMemory 对象或 None
        """
        with self._lock:
            # 获取主条目
            cur = self._conn.execute("""
                SELECT * FROM long_term_memories 
                WHERE id = ? AND user_id = ? AND type = ?
            """, (memory_id, user_id, MemoryType.PROCEDURAL))
            
            row = cur.fetchone()
            if not row:
                return None
            
            entry = ProceduralMemory(**self._row_to_dict(row))
            
            # 获取步骤
            cur = self._conn.execute("""
                SELECT * FROM procedural_steps 
                WHERE memory_id = ? 
                ORDER BY step_index
            """, (memory_id,))
            
            for row in cur.fetchall():
                entry.add_step(
                    action=row["action"],
                    parameters=json.loads(row["parameters"]) if row["parameters"] else {},
                    expected_result=row["expected_result"]
                )
            
            return entry
    
    # ──────────────────────────────────────────────────────────────
    # 记忆巩固与衰减
    # ──────────────────────────────────────────────────────────────
    
    def consolidate(self, memory_id: str, strengthen_amount: float = 0.1):
        """
        巩固记忆（增加重要性）
        
        参数:
            memory_id: 记忆ID
            strengthen_amount: 增强量
        """
        with self._lock:
            self._conn.execute("""
                UPDATE long_term_memories 
                SET importance = MIN(1.0, importance + ?),
                    last_modified_at = ?,
                    accessed_at = ?
                WHERE id = ?
            """, (strengthen_amount, time.time(), time.time(), memory_id))
            self._conn.commit()
    
    def decay(self, threshold_days: float = None,
              min_importance: float = None,
              user_id: str = "default") -> int:
        """
        记忆衰减（清理长期未访问且低重要性的记忆）
        
        参数:
            threshold_days: 天数阈值
            min_importance: 最小重要性阈值
            user_id: 用户标识
        
        返回:
            删除的记忆数量
        """
        threshold = self._DECAY_THRESHOLD_DAYS if threshold_days is None else threshold_days
        min_imp = self._MIN_IMPORTANCE_FOR_DECAY if min_importance is None else min_importance
        cutoff = time.time() - (threshold * 86400)
        
        with self._lock:
            cur = self._conn.execute("""
                DELETE FROM long_term_memories 
                WHERE user_id = ? AND importance < ? AND accessed_at < ?
            """, (user_id, min_imp, cutoff))
            
            removed = cur.rowcount
            if removed:
                self._conn.commit()
                logger.info(f"记忆衰减清理: 删除了 {removed} 条记忆")
            
            return removed
    
    def strengthen_by_use(self, memory_id: str):
        """
        通过使用强化记忆（访问时自动调用）
        
        参数:
            memory_id: 记忆ID
        """
        self.consolidate(memory_id, strengthen_amount=0.02)
    
    # ──────────────────────────────────────────────────────────────
    # 统计与管理
    # ──────────────────────────────────────────────────────────────
    
    def count(self, user_id: str = "default",
              memory_type: Optional[str] = None) -> int:
        """
        统计记忆数量
        
        参数:
            user_id: 用户标识
            memory_type: 记忆类型过滤（可选）
        
        返回:
            记忆数量
        """
        with self._lock:
            sql = "SELECT COUNT(*) FROM long_term_memories WHERE user_id = ?"
            params = [user_id]
            
            if memory_type:
                sql += " AND type = ?"
                params.append(memory_type)
            
            cur = self._conn.execute(sql, params)
            return cur.fetchone()[0]
    
    def summarize(self, user_id: str = "default") -> Dict[str, Any]:
        """
        获取记忆统计摘要
        
        参数:
            user_id: 用户标识
        
        返回:
            统计字典
        """
        return {
            "total": self.count(user_id=user_id),
            "by_type": {
                MemoryType.EPISODIC: self.count(user_id=user_id, memory_type=MemoryType.EPISODIC),
                MemoryType.SEMANTIC: self.count(user_id=user_id, memory_type=MemoryType.SEMANTIC),
                MemoryType.PROCEDURAL: self.count(user_id=user_id, memory_type=MemoryType.PROCEDURAL),
                MemoryType.SKILL: self.count(user_id=user_id, memory_type=MemoryType.SKILL),
                MemoryType.IDENTITY: self.count(user_id=user_id, memory_type=MemoryType.IDENTITY),
                MemoryType.PREFERENCE: self.count(user_id=user_id, memory_type=MemoryType.PREFERENCE),
            },
            "db_path": str(self._db_path),
        }
    
    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("长期记忆引擎已关闭")
    
    # ──────────────────────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────────────────────
    
    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        """将数据库行转换为 MemoryEntry 对象"""
        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            memory_type=row["type"],
            title=row["title"],
            description=row["description"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            emotional_valence=row["emotional_valence"],
            importance=row["importance"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            last_modified_at=row["last_modified_at"],
            access_count=row["access_count"],
            embedding=self._deserialize_embedding(row["embedding"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            "id": row["id"],
            "content": row["content"],
            "memory_type": row["type"],
            "title": row["title"],
            "description": row["description"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "emotional_valence": row["emotional_valence"],
            "importance": row["importance"],
            "confidence": row["confidence"],
            "source": row["source"],
            "created_at": row["created_at"],
            "accessed_at": row["accessed_at"],
            "last_modified_at": row["last_modified_at"],
            "access_count": row["access_count"],
            "embedding": self._deserialize_embedding(row["embedding"]),
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }
    
    def _serialize_embedding(self, embedding: Optional[List[float]]) -> Optional[bytes]:
        """序列化嵌入向量为BLOB"""
        if embedding is None:
            return None
        return np.array(embedding, dtype=np.float32).tobytes()
    
    def _deserialize_embedding(self, blob: Optional[bytes]) -> Optional[List[float]]:
        """从BLOB反序列化嵌入向量"""
        if blob is None:
            return None
        try:
            return np.frombuffer(blob, dtype=np.float32).tolist()
        except Exception:
            return None
    
    def _update_fts_index(self, memory_id: str, entry: MemoryEntry):
        """更新全文搜索索引"""
        cur = self._conn.execute(
            "SELECT rowid FROM long_term_memories WHERE id = ?",
            (memory_id,)
        )
        row = cur.fetchone()
        if row:
            self._conn.execute("""
                INSERT OR REPLACE INTO memories_fts 
                (rowid, content, title, type, tags) 
                VALUES (?, ?, ?, ?, ?)
            """, (row[0], entry.content, entry.title or "", 
                  entry.memory_type, json.dumps(entry.tags)))
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        a_arr = np.array(a)
        b_arr = np.array(b)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
    
    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """生成文本的嵌入向量"""
        if self._embedder is None:
            self._embedder = self._init_embedder()
        
        if self._embedder is None:
            return None
        
        try:
            result = self._embedder([text])
            if result and len(result) > 0:
                emb = result[0]
                return emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            return None
        except Exception as e:
            logger.debug(f"嵌入生成失败: {e}")
            return None
    
    def _init_embedder(self):
        """初始化嵌入模型"""
        # 尝试 fastembed (Rust-based)
        try:
            from fastembed import TextEmbedding
            model = TextEmbedding()
            logger.info("长期记忆: 使用 fastembed 嵌入模型")
            return lambda texts: list(model.embed(texts))
        except ImportError:
            pass  # 可选模块，降级处理
        except Exception as e:
            logger.debug(f"fastembed 加载失败: {e}")
            pass
        
        # 尝试 sentence-transformers（带异常处理）
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("长期记忆: 使用 sentence-transformers 嵌入模型")
            return model.encode
        except ImportError:
            pass  # 可选模块，降级处理
        except Exception as e:
            logger.debug(f"sentence-transformers 加载失败: {e}")
            pass
        
        # Fallback: 基于哈希的伪嵌入
        logger.info("长期记忆: 未找到嵌入模型，使用哈希回退")
        return lambda texts: [
            [float(hash(text + str(i)) % 256) / 255.0 for i in range(384)]
            for text in (texts if isinstance(texts, list) else [texts])
        ]
