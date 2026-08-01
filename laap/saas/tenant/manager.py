"""LAAP SaaS — 多租户管理器（SQLite 持久化）

支持租户 CRUD、功能开关以及从 x-tenant-id header 解析。
租户数据持久化在 SQLite 数据库中。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.saas.tenant")


class TenantManager:
    """多租户管理器 — SQLite 持久化"""

    def __init__(self, db_path: str = "laap_saas.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """初始化租户表"""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS __tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                max_users INTEGER NOT NULL DEFAULT 100,
                features TEXT NOT NULL DEFAULT '{}',
                settings TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            )
        """)
        self._conn.commit()
        # 确保默认租户存在
        existing = self._conn.execute(
            "SELECT id FROM __tenants WHERE id = ?", ("default",)
        ).fetchone()
        if not existing:
            self._conn.execute(
                "INSERT INTO __tenants (id, name, status, max_users, features, settings, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("default", "Default Tenant", "active", 100,
                 json.dumps({"saas": True, "colony": True, "lifeform": True}),
                 json.dumps({}), time.time()),
            )
            self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "max_users": row["max_users"],
            "features": json.loads(row["features"]) if isinstance(row["features"], str) else row["features"],
            "settings": json.loads(row["settings"]) if isinstance(row["settings"], str) else row["settings"],
            "created_at": row["created_at"],
        }

    def create(self, tenant_id: str, name: str,
               max_users: int = 100) -> dict:
        existing = self._conn.execute(
            "SELECT id FROM __tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        if existing:
            raise ValueError(f"Tenant {tenant_id} already exists")
        now = time.time()
        features = json.dumps({"saas": True, "colony": True, "lifeform": True})
        self._conn.execute(
            "INSERT INTO __tenants (id, name, status, max_users, features, settings, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, name, "active", max_users, features, json.dumps({}), now),
        )
        self._conn.commit()
        logger.info(f"Tenant created: {tenant_id} ({name})")
        return {"id": tenant_id, "name": name, "status": "active",
                "max_users": max_users, "features": {"saas": True, "colony": True, "lifeform": True},
                "settings": {}, "created_at": now}

    def get(self, tenant_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM __tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, tenant_id: str) -> bool:
        if tenant_id == "default":
            return False
        cursor = self._conn.execute(
            "DELETE FROM __tenants WHERE id = ?", (tenant_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM __tenants ORDER BY created_at"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def set_feature(self, tenant_id: str, feature: str, enabled: bool) -> bool:
        row = self._conn.execute(
            "SELECT features FROM __tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        if not row:
            return False
        features = json.loads(row["features"]) if isinstance(row["features"], str) else row["features"]
        features[feature] = enabled
        self._conn.execute(
            "UPDATE __tenants SET features = ? WHERE id = ?",
            (json.dumps(features), tenant_id),
        )
        self._conn.commit()
        return True

    def update(self, tenant_id: str, updates: dict) -> Optional[dict]:
        """更新租户字段（name, max_users, status, settings）。"""
        allowed = {"name", "max_users", "status", "settings"}
        sets: List[str] = []
        vals: List[Any] = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                if k == "settings":
                    v = json.dumps(v) if isinstance(v, dict) else v
                vals.append(v)
        if not sets:
            return self.get(tenant_id)
        vals.append(tenant_id)
        self._conn.execute(
            f"UPDATE __tenants SET {', '.join(sets)} WHERE id = ?", vals
        )
        self._conn.commit()
        return self.get(tenant_id)

    def resolve_tenant(self, request_headers: dict) -> str:
        """从请求头解析 tenant_id"""
        return request_headers.get("x-tenant-id", "default")
