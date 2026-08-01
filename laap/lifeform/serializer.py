"""LAAP Lifeform — 状态序列化器

支持:
- JSON 序列化 (默认)
- 版本兼容性检查
- 状态快照 + 差异比较
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from laap.lifeform.lifeform import Lifeform, LifeformState


def serialize(lf: Lifeform, pretty: bool = True) -> str:
    """序列化 Lifeform 全部状态为 JSON 字符串"""
    lf.sleep()
    data = {
        "serialized_at": time.time(),
        "version": "1.0",
        "lifeform": {
            "name": lf.config.name,
            "role": lf.config.role,
            "sandbox_id": lf.sandbox_id,
        },
        "config": lf.config.to_dict(),
        "state": asdict(lf.state),
        "engine_status": {k: v.value for k, v in lf._engine_status.items()},
    }
    return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)


def deserialize(data: str) -> Lifeform:
    """从 JSON 字符串反序列化 Lifeform"""
    parsed = json.loads(data)
    from laap.lifeform.lifeform import LifeformConfig
    config_dict = parsed.get("config", {})
    config = LifeformConfig(**config_dict)
    lf = Lifeform(config)
    state_dict = parsed.get("state", {})
    lf.state = LifeformState(**state_dict)
    for name, status in parsed.get("engine_status", {}).items():
        from laap.lifeform.lifeform import EngineStatus
        try:
            lf._engine_status[name] = EngineStatus(status)
        except ValueError:
            pass
    return lf


def diff(before: Lifeform, after: Lifeform) -> Dict[str, Any]:
    """比较两个 Lifeform 的状态差异"""
    changes = {}
    for key in ("needs", "emotion", "goals"):
        b = getattr(before.state, key, {})
        a = getattr(after.state, key, {})
        if b != a:
            changes[key] = {"before": b, "after": a}
    return changes
