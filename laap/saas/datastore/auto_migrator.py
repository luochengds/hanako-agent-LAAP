"""LAAP SaaS — 自动 Schema 迁移器

检测 Schema 版本差异, 自动生成和执行迁移计划。
支持: 新增字段, 扩字段长度, 新增索引。

用法:
    migrator = AutoMigrator(registry)
    plan = migrator.diff("product", new_schema)
    migrator.apply(plan)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laap.saas.datastore.schema_registry import SchemaRegistry

logger = logging.getLogger("laap.saas.datastore.migrator")


@dataclass
class MigrationStep:
    """单步迁移操作"""
    op: str              # "add_column" | "drop_column" | "create_index" | "drop_index"
    table: str
    column: str = ""
    column_def: str = ""
    index_name: str = ""
    index_cols: List[str] = field(default_factory=list)


@dataclass
class MigrationPlan:
    """完整迁移计划"""
    entity: str
    from_version: int
    to_version: int
    steps: List[MigrationStep] = field(default_factory=list)
    is_compatible: bool = True
    warning: str = ""


class AutoMigrator:
    """Schema 迁移器"""

    def __init__(self, registry: SchemaRegistry):
        self.reg = registry

    def diff(self, entity: str, new_schema: dict) -> MigrationPlan:
        """比较当前 Schema 与新 Schema → 生成迁移计划"""
        model = self.reg.get_model(entity)
        if not model:
            return MigrationPlan(
                entity=entity,
                from_version=0,
                to_version=1,
                warning="Entity not registered, will be created",
            )

        old_fields = {f.name: f for f in model.fields}
        new_fields: Dict[str, Any] = new_schema.get("properties", {})

        plan = MigrationPlan(
            entity=entity,
            from_version=model.version,
            to_version=model.version,
        )

        # 检查新增字段
        for fname, fdef in new_fields.items():
            if fname not in old_fields:
                ftype = fdef.get("type", "string")
                nullable = fname not in new_schema.get("required", [])
                col_def = f"{fname} TEXT"
                if ftype == "integer":
                    col_def = f"{fname} INTEGER"
                elif ftype == "number":
                    col_def = f"{fname} REAL"
                elif ftype == "boolean":
                    col_def = f"{fname} INTEGER"
                if not nullable:
                    col_def += " NOT NULL DEFAULT 0"

                plan.steps.append(MigrationStep(
                    op="add_column",
                    table=model.table_name,
                    column=fname,
                    column_def=col_def,
                ))

        # 检查删除字段 (不兼容)
        deleted = set(old_fields.keys()) - set(new_fields.keys())
        if deleted:
            plan.is_compatible = False
            plan.warning = f"不可逆操作: 字段 {deleted} 将被删除"
            for fname in deleted:
                plan.steps.append(MigrationStep(
                    op="drop_column",
                    table=model.table_name,
                    column=fname,
                ))

        if plan.steps:
            plan.to_version = model.version + 1

        return plan

    def apply(self, plan: MigrationPlan) -> bool:
        """执行迁移计划"""
        if not plan.steps:
            return True

        if not plan.is_compatible:
            logger.warning(f"不兼容迁移: {plan.warning}")
            return False

        conn = self.reg.conn
        for step in plan.steps:
            try:
                if step.op == "add_column":
                    conn.execute(f"ALTER TABLE {step.table} ADD COLUMN {step.column_def}")
                    logger.info(f"  + {step.table}.{step.column}")
                elif step.op == "create_index":
                    cols = ", ".join(step.index_cols)
                    conn.execute(f"CREATE INDEX IF NOT EXISTS {step.index_name} ON {step.table}({cols})")
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    continue
                logger.error(f"Migration failed: {e}")
                return False

        # 更新版本号
        conn.execute(
            "UPDATE __schema_meta SET version = ? WHERE name = ?",
            (plan.to_version, plan.entity),
        )
        conn.commit()
        logger.info(f"Migration complete: {plan.entity} v{plan.from_version}→v{plan.to_version}")
        return True

    def validate(self, entity: str, data: dict) -> List[str]:
        """校验数据是否符合 Schema"""
        model = self.reg.get_model(entity)
        if not model:
            return ["Entity not found"]

        errors = []
        field_map = {f.name: f for f in model.fields}

        # 必填字段
        for fname in model.required:
            if fname not in data:
                errors.append(f"Missing required field: {fname}")

        # 类型检查
        for fname, value in data.items():
            field = field_map.get(fname)
            if not field:
                continue
            if value is None:
                if not field.nullable:
                    errors.append(f"Field {fname} cannot be null")
                continue
            if field.json_type == "string" and not isinstance(value, str):
                errors.append(f"Field {fname} should be string, got {type(value).__name__}")
            elif field.json_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"Field {fname} should be number, got {type(value).__name__}")
            elif field.json_type == "integer" and not isinstance(value, int):
                errors.append(f"Field {fname} should be integer, got {type(value).__name__}")
            elif field.json_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Field {fname} should be boolean, got {type(value).__name__}")

            # 范围检查
            if isinstance(value, (int, float)):
                if field.minimum is not None and value < field.minimum:
                    errors.append(f"Field {fname} < minimum ({field.minimum})")
                if field.maximum is not None and value > field.maximum:
                    errors.append(f"Field {fname} > maximum ({field.maximum})")

        return errors
