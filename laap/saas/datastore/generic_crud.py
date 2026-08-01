"""LAAP SaaS — 通用 CRUD 层

基于 SchemaRegistry 提供动态数据操作。

用法:
    crud = GenericCRUD(registry)
    
    # 注册模型后自动可用
    product = crud.create("product", {"name": "叉车", "price": 999})
    all_products = crud.query("product", filters=[("price", ">", 500)])
    crud.update("product", product["id"], {"price": 899})
    crud.delete("product", product["id"])
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from laap.saas.datastore.schema_registry import SchemaRegistry

logger = logging.getLogger("laap.saas.datastore.crud")

# ── 类型转换 ──────────────────────────────────────────────────

def _value_to_sql(value: Any, json_type: str) -> Any:
    """Python 值 → SQLite 存储值"""
    if value is None:
        return None
    if json_type == "boolean":
        return 1 if value else 0
    if json_type in ("array", "object"):
        return json.dumps(value, ensure_ascii=False)
    return value


def _value_from_sql(value: Any, json_type: str) -> Any:
    """SQLite 值 → Python 值"""
    if value is None:
        return None
    if json_type == "boolean":
        return bool(value)
    if json_type in ("array", "object"):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


# ── 过滤器解析 ──────────────────────────────────────────────

FilterTuple = Tuple[str, str, Any]  # (field, op, value)


def _build_where_clause(filters: Optional[List[FilterTuple]],
                        tenant_id: Optional[str],
                        model_has_tenant: bool) -> Tuple[str, List[Any]]:
    """构建 WHERE 子句"""
    clauses: List[str] = []
    params: List[Any] = []

    if tenant_id and model_has_tenant:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)

    if filters:
        for field, op, value in filters:
            op = op.upper()
            if op in ("=", "!=", ">", "<", ">=", "<=", "LIKE", "NOT LIKE"):
                clauses.append(f"{field} {op} ?")
                params.append(value)
            elif op == "IN":
                placeholders = ",".join(["?"] * len(value))
                clauses.append(f"{field} IN ({placeholders})")
                params.extend(value)
            elif op == "BETWEEN":
                clauses.append(f"{field} BETWEEN ? AND ?")
                params.extend(value)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


class GenericCRUD:
    """通用 CRUD 操作层"""

    def __init__(self, registry: SchemaRegistry):
        self.reg = registry

    # ── 创建 ──

    def create(self, entity: str, data: dict,
               tenant_id: Optional[str] = None) -> Optional[dict]:
        """创建一条记录"""
        model = self.reg.get_model(entity)
        if not model:
            logger.error(f"Unknown entity: {entity}")
            return None

        now = time.time()
        record_id = data.get("id", f"{entity}_{uuid.uuid4().hex[:12]}")

        cols = ["id"]
        vals = [record_id]
        placeholders = ["?"]

        for f in model.fields:
            if f.name in data:
                cols.append(f.name)
                vals.append(_value_to_sql(data[f.name], f.json_type))
                placeholders.append("?")
            elif f.default is not None:
                cols.append(f.name)
                vals.append(_value_to_sql(f.default, f.json_type))
                placeholders.append("?")

        cols.append("created_at")
        vals.append(now)
        placeholders.append("?")

        cols.append("updated_at")
        vals.append(now)
        placeholders.append("?")

        if model.tenant_isolated:
            tid = tenant_id or data.get("tenant_id", "default")
            cols.append("tenant_id")
            vals.append(tid)
            placeholders.append("?")

        sql = f"INSERT INTO {model.table_name} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        try:
            self.reg.conn.execute(sql, vals)
            self.reg.conn.commit()
            logger.debug(f"Created {entity}: {record_id}")
            return self.read(entity, record_id, tenant_id)
        except Exception as e:
            logger.error(f"Failed to create {entity}: {e}")
            return None

    # ── 读取 ──

    def read(self, entity: str, record_id: str,
             tenant_id: Optional[str] = None) -> Optional[dict]:
        """读取单条记录"""
        model = self.reg.get_model(entity)
        if not model:
            return None

        sql = f"SELECT * FROM {model.table_name} WHERE id = ?"
        params: List[Any] = [record_id]

        if tenant_id and model.tenant_isolated:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)

        row = self.reg.conn.execute(sql, params).fetchone()
        return self._row_to_dict(row, model) if row else None

    # ── 更新 ──

    def update(self, entity: str, record_id: str, data: dict,
               tenant_id: Optional[str] = None) -> Optional[dict]:
        """更新记录"""
        model = self.reg.get_model(entity)
        if not model:
            return None

        sets: List[str] = []
        vals: List[Any] = []
        for f in model.fields:
            if f.name in data:
                sets.append(f"{f.name} = ?")
                vals.append(_value_to_sql(data[f.name], f.json_type))

        if not sets:
            return self.read(entity, record_id, tenant_id)

        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(record_id)

        sql = f"UPDATE {model.table_name} SET {', '.join(sets)} WHERE id = ?"
        if tenant_id and model.tenant_isolated:
            sql += " AND tenant_id = ?"
            vals.append(tenant_id)

        try:
            self.reg.conn.execute(sql, vals)
            self.reg.conn.commit()
            return self.read(entity, record_id, tenant_id)
        except Exception as e:
            logger.error(f"Failed to update {entity}/{record_id}: {e}")
            return None

    # ── 删除 ──

    def delete(self, entity: str, record_id: str,
               tenant_id: Optional[str] = None) -> bool:
        """删除记录"""
        model = self.reg.get_model(entity)
        if not model:
            return False

        sql = f"DELETE FROM {model.table_name} WHERE id = ?"
        params: List[Any] = [record_id]
        if tenant_id and model.tenant_isolated:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)

        try:
            self.reg.conn.execute(sql, params)
            self.reg.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete {entity}/{record_id}: {e}")
            return False

    # ── 查询 ──

    def query(self, entity: str,
              filters: Optional[List[FilterTuple]] = None,
              sort: Optional[str] = None,
              limit: int = 100,
              offset: int = 0,
              tenant_id: Optional[str] = None) -> List[dict]:
        """批量查询"""
        model = self.reg.get_model(entity)
        if not model:
            return []

        where, params = _build_where_clause(
            filters, tenant_id,
            model.tenant_isolated and tenant_id is not None,
        )

        sql = f"SELECT * FROM {model.table_name} WHERE {where}"
        if sort:
            sql += f" ORDER BY {sort}"
        sql += f" LIMIT {limit} OFFSET {offset}"

        rows = self.reg.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r, model) for r in rows]

    # ── 计数 ──

    def count(self, entity: str,
              filters: Optional[List[FilterTuple]] = None,
              tenant_id: Optional[str] = None) -> int:
        model = self.reg.get_model(entity)
        if not model:
            return 0

        where, params = _build_where_clause(
            filters, tenant_id,
            model.tenant_isolated and tenant_id is not None,
        )
        row = self.reg.conn.execute(
            f"SELECT COUNT(*) as cnt FROM {model.table_name} WHERE {where}", params
        ).fetchone()
        return row["cnt"] if row else 0

    # ── 工具 ──

    def _row_to_dict(self, row: sqlite3.Row, model: "ModelDef") -> dict:
        """sqlite3.Row → dict (含类型转换)"""
        result = {}
        field_map = {f.name: f.json_type for f in model.fields}
        for key in row.keys():
            if key in field_map:
                result[key] = _value_from_sql(row[key], field_map[key])
            else:
                result[key] = row[key]
        return result
