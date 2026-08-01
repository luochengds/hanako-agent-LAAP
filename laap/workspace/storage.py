"""工作区存储模块

实现基于 SQLite 的持久化存储：
- SuggestionQueue：建议队列（支持优先级、状态管理、过期清理）
- WorkspaceStateDB：工作区状态数据库（快照历史、建议历史、状态变更记录）
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from laap.sandbox._types import ProjectSnapshot, Suggestion


class SuggestionQueue:
    """建议队列——基于 SQLite 的持久化队列。
    
    特性：
    - FIFO 队列，但支持优先级插队
    - 最大容量限制（默认 100），超过时删除最旧的低优先级建议
    - 支持状态标记：pending（待处理）、adopted（已采纳）、ignored（已忽略）、later（稍后处理）
    - 支持按类别、状态、优先级查询
    - 自动清理过期建议（默认 30 天）
    
    用法：
        queue = SuggestionQueue(db_path="laap_workspace.db")
        queue.push(Suggestion(title="修复技术债", category="tech_debt"))
        suggestion = queue.pop()
        queue.mark(suggestion.suggestion_id, "adopted")
    """
    
    MAX_SIZE = 100
    EXPIRY_DAYS = 30
    
    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    
    def __init__(self, db_path: str = "laap_workspace.db"):
        """
        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_add_causal_columns()

    def _create_tables(self) -> None:
        """创建数据库表。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                suggestion_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                priority TEXT DEFAULT 'medium',
                relevance REAL DEFAULT 0.5,
                category TEXT DEFAULT '',
                target_file TEXT,
                actions TEXT DEFAULT '[]',
                source_sandbox TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL DEFAULT 0.0,
                updated_at REAL DEFAULT 0.0,
                causal_chain TEXT DEFAULT '[]',
                explanation TEXT DEFAULT '',
                confidence REAL DEFAULT 0.5,
                source_data TEXT DEFAULT ''
            )
        """)
        self._conn.commit()

    def _migrate_add_causal_columns(self) -> None:
        """数据库迁移：添加因果链相关列（兼容已有数据）。

        对于已存在的旧数据库（Phase 2.1 之前创建），
        使用 ALTER TABLE ADD COLUMN 补充 causal_chain、explanation、
        confidence、source_data 四列。

        SQLite 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS 语法，
        因此先通过 PRAGMA table_info 查询现有列再决定是否添加。
        """
        cursor = self._conn.cursor()

        # 查询 suggestions 表当前的列名集合
        cursor.execute("PRAGMA table_info(suggestions)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        # Phase 2.1 需要添加的因果链相关列定义
        new_columns = [
            ("causal_chain", "TEXT DEFAULT '[]'"),
            ("explanation", "TEXT DEFAULT ''"),
            ("confidence", "REAL DEFAULT 0.5"),
            ("source_data", "TEXT DEFAULT ''"),
        ]

        for column_name, column_type in new_columns:
            if column_name not in existing_columns:
                cursor.execute(
                    f"ALTER TABLE suggestions ADD COLUMN {column_name} {column_type}"
                )

        self._conn.commit()
    
    def push(self, suggestion: Suggestion) -> None:
        """推入建议到队列。
        
        如果队列已满：
        - 删除最旧的低优先级（medium/low）建议
        - 如果都是高优先级，删除最旧的
        
        优先级插队规则：
        - critical 优先级插入到队首
        - high 优先级插入到 pending 建议的前面
        - medium/low 插入到队尾
        """
        cursor = self._conn.cursor()
        
        current_count = cursor.execute(
            "SELECT COUNT(*) FROM suggestions WHERE status = 'pending'"
        ).fetchone()[0]
        
        if current_count >= self.MAX_SIZE:
            cursor.execute("""
                SELECT suggestion_id, priority, created_at 
                FROM suggestions 
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
            """)
            oldest = cursor.fetchone()
            if oldest:
                if self._PRIORITY_ORDER[oldest["priority"]] >= self._PRIORITY_ORDER["medium"]:
                    cursor.execute(
                        "DELETE FROM suggestions WHERE suggestion_id = ?",
                        (oldest["suggestion_id"],)
                    )
                else:
                    cursor.execute("""
                        DELETE FROM suggestions 
                        WHERE status = 'pending'
                        ORDER BY created_at ASC
                        LIMIT 1
                    """)
        
        actions_json = json.dumps(suggestion.actions)
        causal_chain_json = json.dumps(suggestion.causal_chain)
        now = time.time()

        cursor.execute("""
            INSERT OR REPLACE INTO suggestions (
                suggestion_id, title, description, priority, relevance,
                category, target_file, actions, source_sandbox, status,
                created_at, updated_at, causal_chain, explanation,
                confidence, source_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            suggestion.suggestion_id,
            suggestion.title,
            suggestion.description,
            suggestion.priority,
            suggestion.relevance,
            suggestion.category,
            suggestion.target_file,
            actions_json,
            suggestion.source_sandbox,
            "pending",
            suggestion.created_at if suggestion.created_at else now,
            now,
            causal_chain_json,
            suggestion.explanation,
            suggestion.confidence,
            suggestion.source_data,
        ))

        self._conn.commit()
    
    def pop(self) -> Optional[Suggestion]:
        """弹出优先级最高的待处理建议。
        
        顺序：critical > high > medium > low，同优先级按时间排序
        
        Returns:
            Suggestion 实例，如果队列为空返回 None
        """
        self._clean_expired()
        
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestions 
            WHERE status = 'pending'
            ORDER BY 
                CASE priority 
                    WHEN 'critical' THEN 0 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    WHEN 'low' THEN 3 
                END ASC,
                created_at ASC
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        if not row:
            return None
        
        suggestion = self._row_to_suggestion(row)
        
        cursor.execute(
            "UPDATE suggestions SET status = 'adopted', updated_at = ? WHERE suggestion_id = ?",
            (time.time(), suggestion.suggestion_id)
        )
        self._conn.commit()
        
        return suggestion
    
    def peek_all(self) -> List[Suggestion]:
        """查看所有建议（按优先级排序）。"""
        self._clean_expired()
        
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestions 
            ORDER BY 
                CASE priority 
                    WHEN 'critical' THEN 0 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    WHEN 'low' THEN 3 
                END ASC,
                created_at ASC
        """)
        
        return [self._row_to_suggestion(row) for row in cursor.fetchall()]
    
    def mark(self, suggestion_id: str, status: str) -> bool:
        """标记建议状态。
        
        Args:
            suggestion_id: 建议 ID
            status: pending / adopted / ignored / later
        
        Returns:
            是否成功标记
        """
        valid_statuses = {"pending", "adopted", "ignored", "later"}
        if status not in valid_statuses:
            return False
        
        cursor = self._conn.cursor()
        cursor.execute("""
            UPDATE suggestions 
            SET status = ?, updated_at = ? 
            WHERE suggestion_id = ?
        """, (status, time.time(), suggestion_id))
        
        self._conn.commit()
        return cursor.rowcount > 0
    
    def get_by_status(self, status: str) -> List[Suggestion]:
        """按状态查询建议。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestions 
            WHERE status = ?
            ORDER BY created_at DESC
        """, (status,))
        
        return [self._row_to_suggestion(row) for row in cursor.fetchall()]
    
    def get_by_category(self, category: str) -> List[Suggestion]:
        """按类别查询建议。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestions 
            WHERE category = ?
            ORDER BY created_at DESC
        """, (category,))
        
        return [self._row_to_suggestion(row) for row in cursor.fetchall()]
    
    def get_by_priority(self, priority: str) -> List[Suggestion]:
        """按优先级查询建议。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestions 
            WHERE priority = ?
            ORDER BY created_at DESC
        """, (priority,))
        
        return [self._row_to_suggestion(row) for row in cursor.fetchall()]
    
    def remove(self, suggestion_id: str) -> bool:
        """移除建议。"""
        cursor = self._conn.cursor()
        cursor.execute(
            "DELETE FROM suggestions WHERE suggestion_id = ?",
            (suggestion_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0
    
    def clear(self) -> None:
        """清空队列。"""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM suggestions")
        self._conn.commit()
    
    def _clean_expired(self) -> int:
        """清理过期建议（EXPIRY_DAYS 天前的）。返回删除数量。"""
        expire_threshold = time.time() - (self.EXPIRY_DAYS * 24 * 60 * 60)
        
        cursor = self._conn.cursor()
        cursor.execute(
            "DELETE FROM suggestions WHERE created_at < ?",
            (expire_threshold,)
        )
        
        deleted = cursor.rowcount
        self._conn.commit()
        return deleted
    
    def stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        cursor = self._conn.cursor()
        
        total = cursor.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
        pending = cursor.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'pending'").fetchone()[0]
        adopted = cursor.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'adopted'").fetchone()[0]
        ignored = cursor.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'ignored'").fetchone()[0]
        later = cursor.execute("SELECT COUNT(*) FROM suggestions WHERE status = 'later'").fetchone()[0]
        
        return {
            "total": total,
            "pending": pending,
            "adopted": adopted,
            "ignored": ignored,
            "later": later,
        }
    
    def close(self) -> None:
        """关闭数据库连接。"""
        if hasattr(self, "_conn") and self._conn:
            self._conn.close()
    
    def __del__(self) -> None:
        """析构时自动关闭连接。"""
        self.close()
    
    def _row_to_suggestion(self, row: sqlite3.Row) -> Suggestion:
        """将数据库行转换为 Suggestion 对象。"""
        return Suggestion(
            suggestion_id=row["suggestion_id"],
            title=row["title"],
            description=row["description"],
            priority=row["priority"],
            relevance=row["relevance"],
            category=row["category"],
            target_file=row["target_file"],
            actions=json.loads(row["actions"]) if row["actions"] else [],
            source_sandbox=row["source_sandbox"],
            created_at=row["created_at"],
            causal_chain=json.loads(row["causal_chain"]) if row["causal_chain"] else [],
            explanation=row["explanation"] if row["explanation"] else "",
            confidence=row["confidence"] if row["confidence"] is not None else 0.5,
            source_data=row["source_data"] if row["source_data"] else "",
        )


class WorkspaceStateDB:
    """工作区状态数据库——持久化 ProjectSnapshot 历史与建议历史。
    
    功能：
    - 存储 ProjectSnapshot 历史（时间序列）
    - 存储建议历史（包含状态变更记录）
    - 支持时间范围查询
    - 支持差异对比（两个快照之间的变化）
    
    用法：
        state_db = WorkspaceStateDB(db_path="laap_workspace.db")
        state_db.save_snapshot(snapshot)
        history = state_db.get_snapshot_history(hours=24)
        diff = state_db.compare_snapshots(before_id, after_id)
    """
    
    def __init__(self, db_path: str = "laap_workspace.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self) -> None:
        """创建数据库表（snapshot_history、suggestion_history、status_changes）。"""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshot_history (
                snapshot_id TEXT PRIMARY KEY,
                root_path TEXT NOT NULL,
                git_state_json TEXT DEFAULT '{}',
                file_tree_json TEXT DEFAULT '{}',
                test_state_json TEXT DEFAULT '{}',
                build_state_json TEXT DEFAULT '{}',
                tech_debt_json TEXT DEFAULT '{}',
                dependencies_json TEXT DEFAULT '{}',
                timestamp REAL DEFAULT 0.0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suggestion_history (
                suggestion_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT DEFAULT '',
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                created_at REAL DEFAULT 0.0,
                source TEXT DEFAULT 'advisor'
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS status_changes (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_id TEXT NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                actor TEXT DEFAULT 'system',
                timestamp REAL DEFAULT 0.0
            )
        """)
        
        self._conn.commit()
    
    def save_snapshot(self, snapshot: ProjectSnapshot) -> str:
        """保存快照到历史。返回 snapshot_id。"""
        import uuid
        
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        cursor = self._conn.cursor()
        
        cursor.execute("""
            INSERT INTO snapshot_history (
                snapshot_id, root_path, git_state_json, file_tree_json,
                test_state_json, build_state_json, tech_debt_json,
                dependencies_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            snapshot.root_path,
            json.dumps(self._dataclass_to_dict(snapshot.git_state)),
            json.dumps(self._dataclass_to_dict(snapshot.file_tree)),
            json.dumps(self._dataclass_to_dict(snapshot.test_state)),
            json.dumps(self._dataclass_to_dict(snapshot.build_state)),
            json.dumps(self._dataclass_to_dict(snapshot.tech_debt)),
            json.dumps(self._dataclass_to_dict(snapshot.dependencies)),
            snapshot.timestamp if snapshot.timestamp else time.time(),
        ))
        
        self._conn.commit()
        return snapshot_id
    
    def get_snapshot_history(self, hours: Optional[int] = None, 
                            limit: int = 50) -> List[Dict[str, Any]]:
        """获取快照历史。"""
        cursor = self._conn.cursor()
        
        if hours:
            threshold = time.time() - (hours * 60 * 60)
            cursor.execute("""
                SELECT * FROM snapshot_history 
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (threshold, limit))
        else:
            cursor.execute("""
                SELECT * FROM snapshot_history 
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def compare_snapshots(self, before_id: str, 
                         after_id: str) -> Dict[str, Any]:
        """对比两个快照的差异。
        
        返回：{
            "git_state": {"changed": bool, ...},
            "file_tree": {"changed": bool, ...},
            "tech_debt": {"changed": bool, ...},
            ...
        }
        """
        cursor = self._conn.cursor()
        
        cursor.execute("SELECT * FROM snapshot_history WHERE snapshot_id = ?", (before_id,))
        before_row = cursor.fetchone()
        
        cursor.execute("SELECT * FROM snapshot_history WHERE snapshot_id = ?", (after_id,))
        after_row = cursor.fetchone()
        
        if not before_row or not after_row:
            return {}
        
        result = {}
        
        fields = ["git_state_json", "file_tree_json", "test_state_json", 
                  "build_state_json", "tech_debt_json", "dependencies_json"]
        
        for field in fields:
            field_name = field.replace("_json", "")
            before_data = json.loads(before_row[field])
            after_data = json.loads(after_row[field])
            
            result[field_name] = {
                "changed": before_data != after_data,
                "before": before_data,
                "after": after_data,
            }
        
        return result
    
    def save_suggestion_history(self, suggestion: Suggestion, 
                                source: str = "advisor") -> None:
        """保存建议到历史（包含完整内容）。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO suggestion_history (
                suggestion_id, title, category, priority, status,
                created_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            suggestion.suggestion_id,
            suggestion.title,
            suggestion.category,
            suggestion.priority,
            "pending",
            suggestion.created_at if suggestion.created_at else time.time(),
            source,
        ))
        self._conn.commit()
    
    def get_suggestion_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取建议历史。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM suggestion_history 
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def log_status_change(self, suggestion_id: str, 
                         old_status: str, new_status: str,
                         actor: str = "system") -> None:
        """记录建议状态变更。"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO status_changes (
                suggestion_id, old_status, new_status, actor, timestamp
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            suggestion_id,
            old_status,
            new_status,
            actor,
            time.time(),
        ))
        self._conn.commit()
    
    def close(self) -> None:
        """关闭数据库连接。"""
        if hasattr(self, "_conn") and self._conn:
            self._conn.close()
    
    def __del__(self) -> None:
        """析构时自动关闭连接。"""
        self.close()
    
    def _dataclass_to_dict(self, obj: Any) -> Dict[str, Any]:
        """将 dataclass 对象转换为可序列化的字典。"""
        if hasattr(obj, "__dataclass_fields__"):
            return {
                key: self._dataclass_to_dict(value) 
                for key, value in obj.__dict__.items()
            }
        elif isinstance(obj, list):
            return [self._dataclass_to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._dataclass_to_dict(value) for key, value in obj.items()}
        else:
            return obj
