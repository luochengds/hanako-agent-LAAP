"""LAAP SaaS — Schema 注册表 + SQLite 自动建表

输入: JSON Schema (类 OpenAPI 3.0 subset)
输出: 自动创建/管理 SQLite 表

用法:
    reg = SchemaRegistry(":memory:")
    reg.register("product", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 200},
            "price": {"type": "number", "minimum": 0},
            "active": {"type": "boolean", "default": True},
        },
        "required": ["name", "price"],
    })
    # → 自动创建 products 表 (id, name, price, active, created_at, updated_at)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.saas.datastore.schema")

# ── 类型映射 ──────────────────────────────────────────────────

JSON_TO_SQLITE: Dict[str, str] = {
    "string": "TEXT",
    "number": "REAL",
    "integer": "INTEGER",
    "boolean": "INTEGER",  # SQLite 无原生 BOOLEAN
    "array": "TEXT",       # JSON 序列化存储
    "object": "TEXT",      # JSON 序列化存储
}


@dataclass
class FieldDef:
    """Schema 字段定义"""
    name: str
    json_type: str
    sql_type: str
    nullable: bool = True
    default: Any = None
    max_length: Optional[int] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    description: str = ""

    def to_column_def(self) -> str:
        parts = [self.name, self.sql_type]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.default is not None:
            if isinstance(self.default, bool):
                parts.append(f"DEFAULT {1 if self.default else 0}")
            elif isinstance(self.default, str):
                parts.append(f"DEFAULT '{self.default}'")
            else:
                parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


@dataclass
class ModelDef:
    """已注册的数据模型"""
    name: str               # 实体名, 如 "product"
    table_name: str          # SQL 表名, 如 "ent_product"
    version: int = 1
    fields: List[FieldDef] = field(default_factory=list)
    required: List[str] = field(default_factory=list)
    schema_json: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    tenant_isolated: bool = True  # 默认多租户隔离


class SchemaRegistry:
    """Schema 注册表 — 单例, 线程安全"""

    _instances: Dict[str, "SchemaRegistry"] = {}
    _lock = threading.RLock()

    def __init__(self, db_path: str = "laap_saas.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._models: Dict[str, ModelDef] = {}
        self._table_to_model: Dict[str, str] = {}

    # ── 连接管理 ──

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_meta_table()
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 元数据表 ──

    def _init_meta_table(self):
        """存储已注册的 Schema"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS __schema_meta (
                name TEXT PRIMARY KEY,
                table_name TEXT UNIQUE NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                schema_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                tenant_isolated INTEGER NOT NULL DEFAULT 1
            )
        """)
        self.conn.commit()
        # 从持久化恢复
        rows = self.conn.execute(
            "SELECT name, table_name, version, schema_json, tenant_isolated FROM __schema_meta"
        ).fetchall()
        for row in rows:
            schema = json.loads(row["schema_json"])
            model = self._build_model(row["name"], row["table_name"], schema)
            model.version = row["version"]
            self._models[row["name"]] = model
            self._table_to_model[row["table_name"]] = row["name"]

    # ── Schema 解析 ──

    def _parse_schema(self, name: str, schema: dict) -> Tuple[List[FieldDef], List[str]]:
        """解析 JSON Schema → FieldDef 列表"""
        fields: List[FieldDef] = []
        required = schema.get("required", [])
        props = schema.get("properties", {})

        for prop_name, prop_schema in props.items():
            json_type = prop_schema.get("type", "string")
            sql_type = JSON_TO_SQLITE.get(json_type, "TEXT")
            nullable = prop_name not in required
            default = prop_schema.get("default", None)

            # array 和 object 用 TEXT 存 JSON 字符串
            if json_type in ("array", "object"):
                sql_type = "TEXT"

            field = FieldDef(
                name=prop_name,
                json_type=json_type,
                sql_type=sql_type,
                nullable=nullable,
                default=default,
                max_length=prop_schema.get("maxLength"),
                minimum=prop_schema.get("minimum"),
                maximum=prop_schema.get("maximum"),
                description=prop_schema.get("description", ""),
            )
            fields.append(field)

        return fields, required

    def _build_model(self, name: str, table_name: str, schema: dict) -> ModelDef:
        fields, required = self._parse_schema(name, schema)
        return ModelDef(
            name=name,
            table_name=table_name,
            fields=fields,
            required=required,
            schema_json=schema,
            tenant_isolated=schema.get("x-tenant-isolated", True),
        )

    # ── 注册 ──

    def register(self, name: str, schema: dict) -> ModelDef:
        """注册数据模型 → 自动建表

        Args:
            name: 实体名 (如 "product"), 会映射到表名 "ent_{name}"
            schema: JSON Schema

        Returns:
            ModelDef

        Raises:
            ValueError: 同名已注册且 schema 不兼容
        """
        table_name = f"ent_{name}"
        model = self._build_model(name, table_name, schema)

        with self._lock:
            existing = self._models.get(name)
            if existing:
                if existing.schema_json != schema:
                    # 版本升级 → 走迁移
                    model.version = existing.version + 1
                    self._migrate(existing, model)
                else:
                    return existing

            # 建表
            self._create_table(model)
            # 持久化元数据
            self.conn.execute(
                """INSERT OR REPLACE INTO __schema_meta
                   (name, table_name, version, schema_json, created_at, tenant_isolated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, table_name, model.version, json.dumps(schema),
                 model.created_at, int(model.tenant_isolated)),
            )
            self.conn.commit()
            self._models[name] = model
            self._table_to_model[table_name] = name
            logger.info(f"Schema registered: {name} → {table_name} (v{model.version})")

        return model

    # ── 建表 ──

    def _create_table(self, model: ModelDef):
        """CREATE TABLE IF NOT EXISTS"""
        columns = ["id TEXT PRIMARY KEY"]
        for f in model.fields:
            columns.append(f.to_column_def())
        columns.append("created_at REAL NOT NULL DEFAULT (julianday('now'))")
        columns.append("updated_at REAL NOT NULL DEFAULT (julianday('now'))")
        if model.tenant_isolated:
            columns.append("tenant_id TEXT NOT NULL DEFAULT 'default'")

        col_str = ',\n  '.join(columns)
        sql = f'CREATE TABLE IF NOT EXISTS {model.table_name} (\n  {col_str}\n)'
        self.conn.execute(sql)
        # 索引
        if model.tenant_isolated:
            self.conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{model.table_name}_tenant "
                f"ON {model.table_name}(tenant_id)"
            )
        self.conn.commit()

    # ── 迁移 ──

    def _migrate(self, old: ModelDef, new: ModelDef):
        """Schema 变更 → ALTER TABLE (仅新增列)"""
        old_names = {f.name for f in old.fields}
        for f in new.fields:
            if f.name not in old_names:
                try:
                    self.conn.execute(f"ALTER TABLE {old.table_name} ADD COLUMN {f.to_column_def()}")
                    logger.info(f"  Migrated: {old.table_name} +{f.name} ({f.sql_type})")
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        continue
                    raise
        self.conn.commit()

    # ── 查询 ──

    def get_model(self, name: str) -> Optional[ModelDef]:
        return self._models.get(name)

    def get_model_by_table(self, table_name: str) -> Optional[ModelDef]:
        entity = self._table_to_model.get(table_name)
        if entity:
            return self._models.get(entity)
        return None

    def list_models(self) -> List[dict]:
        return [
            {"name": m.name, "table": m.table_name, "version": m.version,
             "fields": len(m.fields), "tenant_isolated": m.tenant_isolated}
            for m in self._models.values()
        ]

    def is_registered(self, name: str) -> bool:
        return name in self._models
