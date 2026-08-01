"""LAAP AGI — World Model MCP Tools (P1-world-model).

为 ``LAAPMCPServer`` 提供 ``world_perceive`` / ``world_predict`` /
``world_calibrate`` 三个 MCP 工具的注册函数。注册函数接受一个
FastMCP 实例，在其上用 ``@mcp_server.tool()`` 装饰注册工具。

工具内部使用 ``UnifiedWorldModel`` 实例（per agent 缓存）+
``VaultManager`` 的 ``_open_vault_connection`` 把预测记录持久化到
``{agent}_vault.db`` 的 ``prediction_log`` 表，实现 agent 隔离。

预测调度器 ``maybe_schedule_prediction`` 在每 N 轮对话触发一次
``world_predict``，供 hanako aris-plugin 的对话钩子调用。

设计要点：
  - **不破坏既有方法**：``UnifiedWorldModel`` 仅新增 ``perceive`` /
    ``calibrate`` facade，``predict`` 沿用既有签名。
  - **幂等**：``prediction_log`` 表 ``CREATE TABLE IF NOT EXISTS``，
    ``INSERT OR REPLACE``。
  - **agent 隔离**：每个 agent 的预测记录只写入自己的 vault 文件。
  - **lazy import**：world_model / self_model / vault_manager 全部
    延迟导入，避免模块加载循环与可选依赖缺失导致注册失败。
  - **返回 JSON 字符串**：与既有 MCP 工具风格一致。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.agi.world_model_mcp_tools")

# ═══════════════════════════════════════════════════════════════
# Per-agent 缓存（world_model + self_model）
# ═══════════════════════════════════════════════════════════════

_WORLD_MODELS: Dict[str, Any] = {}
_SELF_MODELS: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def _get_world_model(agent_name: str) -> Any:
    """获取（必要时创建）agent 专属 UnifiedWorldModel 实例。"""
    with _CACHE_LOCK:
        wm = _WORLD_MODELS.get(agent_name)
        if wm is not None:
            return wm
    # 延迟导入：world_model 依赖 numpy / liquid memory field 等可选组件
    from laap.agi.world_model import UnifiedWorldModel
    wm = UnifiedWorldModel(name=f"world-{agent_name}")
    with _CACHE_LOCK:
        existing = _WORLD_MODELS.get(agent_name)
        if existing is not None:
            # 并发情形下复用已创建实例
            return existing
        _WORLD_MODELS[agent_name] = wm
    return wm


def _get_self_model(agent_name: str) -> Any:
    """获取（必要时创建）agent 专属 EmergentSelfModel 实例。"""
    with _CACHE_LOCK:
        sm = _SELF_MODELS.get(agent_name)
        if sm is not None:
            return sm
    from laap.agi.self_model import EmergentSelfModel
    sm = EmergentSelfModel(agent_name=agent_name)
    with _CACHE_LOCK:
        existing = _SELF_MODELS.get(agent_name)
        if existing is not None:
            return existing
        _SELF_MODELS[agent_name] = sm
    return sm


# ═══════════════════════════════════════════════════════════════
# Vault 集成（prediction_log 表）
# ═══════════════════════════════════════════════════════════════

def _get_vault_manager() -> Any:
    """获取全局 VaultManager 单例。测试可 monkeypatch 此函数。"""
    from laap.memory_vault.vault_manager import vault_manager
    return vault_manager


def _ensure_prediction_log_table(conn: Any) -> None:
    """幂等创建 prediction_log 表。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prediction_log (
            prediction_id     TEXT PRIMARY KEY,
            agent_name        TEXT NOT NULL,
            entity            TEXT,
            horizon           INTEGER,
            predicted_outcome TEXT,
            confidence        REAL,
            created_at        TEXT NOT NULL,
            calibrated        INTEGER DEFAULT 0,
            actual_outcome    TEXT,
            outcome_score     REAL,
            bias              REAL,
            hit               INTEGER,
            error             REAL,
            calibrated_at     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_prediction_log_agent
            ON prediction_log(agent_name);
        CREATE INDEX IF NOT EXISTS idx_prediction_log_calibrated
            ON prediction_log(calibrated);
    """)


def _store_prediction(agent_name: str, prediction: Dict[str, Any]) -> None:
    """把一条预测记录写入 agent 的 prediction_log 表（INSERT OR REPLACE）。"""
    vault_manager = _get_vault_manager()
    db_path, key_hex = vault_manager._get_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_prediction_log_table(conn)
        conn.execute(
            """INSERT OR REPLACE INTO prediction_log
               (prediction_id, agent_name, entity, horizon,
                predicted_outcome, confidence, created_at, calibrated)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                prediction["prediction_id"],
                agent_name,
                prediction.get("entity"),
                int(prediction.get("horizon", 1)),
                json.dumps(prediction.get("predicted_outcome"),
                           ensure_ascii=False),
                float(prediction.get("confidence", 0.0)),
                prediction.get("created_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_prediction(agent_name: str, prediction_id: str) -> Optional[Dict[str, Any]]:
    """从 agent 的 prediction_log 表取回一条预测记录。"""
    vault_manager = _get_vault_manager()
    db_path, key_hex = vault_manager._get_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_prediction_log_table(conn)
        row = conn.execute(
            "SELECT * FROM prediction_log WHERE prediction_id = ? AND agent_name = ?",
            (prediction_id, agent_name),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["predicted_outcome"] = json.loads(d.get("predicted_outcome") or "null")
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            d["actual_outcome"] = json.loads(d.get("actual_outcome") or "null")
        except (json.JSONDecodeError, TypeError):
            pass
        return d
    finally:
        conn.close()


def _list_predictions(agent_name: str, only_uncalibrated: bool = False,
                      limit: int = 100) -> List[Dict[str, Any]]:
    """列出 agent 的预测记录（最新优先）。"""
    vault_manager = _get_vault_manager()
    db_path, key_hex = vault_manager._get_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_prediction_log_table(conn)
        clause = "WHERE agent_name = ?"
        params: list = [agent_name]
        if only_uncalibrated:
            clause += " AND calibrated = 0"
        rows = conn.execute(
            f"SELECT * FROM prediction_log {clause} "
            f"ORDER BY created_at DESC LIMIT ?",
            params + [int(limit)],
        ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["predicted_outcome"] = json.loads(d.get("predicted_outcome") or "null")
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                d["actual_outcome"] = json.loads(d.get("actual_outcome") or "null")
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results
    finally:
        conn.close()


def _mark_calibrated(agent_name: str, prediction_id: str,
                     error_record: Dict[str, Any], actual: Dict[str, Any]) -> None:
    """把一条预测记录标记为已校准，写入真实结果与误差。"""
    vault_manager = _get_vault_manager()
    db_path, key_hex = vault_manager._get_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_prediction_log_table(conn)
        conn.execute(
            """UPDATE prediction_log
               SET calibrated = 1,
                   actual_outcome = ?,
                   outcome_score = ?,
                   bias = ?,
                   hit = ?,
                   error = ?,
                   calibrated_at = ?
               WHERE prediction_id = ? AND agent_name = ?""",
            (
                json.dumps(actual, ensure_ascii=False),
                error_record.get("outcome_score"),
                error_record.get("bias"),
                None if error_record.get("hit") is None else (1 if error_record["hit"] else 0),
                error_record.get("error"),
                datetime.now(timezone.utc).isoformat(),
                prediction_id,
                agent_name,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _parse_json_arg(arg: str) -> Dict[str, Any]:
    """把 MCP 工具收到的 JSON 字符串参数解析为 dict，容错。"""
    if isinstance(arg, dict):
        return arg
    if not isinstance(arg, str):
        raise ValueError(f"expected JSON string, got {type(arg).__name__}")
    return json.loads(arg) if arg.strip() else {}


def _simulation_to_prediction_outcome(sim_result: Any) -> Dict[str, Any]:
    """把 UnifiedWorldModel.predict 返回的 SimulationResult 序列化为可 JSON 化的 dict。"""
    # SimulationResult 是 dataclass，字段：possible_outcomes / probabilities /
    # confidence / simulation_time / counterfactuals / details / steps / assumptions
    try:
        outcomes = list(sim_result.possible_outcomes)
    except Exception:
        outcomes = []
    try:
        probs = [float(p) for p in sim_result.probabilities]
    except Exception:
        probs = []
    counterfactuals = []
    try:
        for cf in sim_result.counterfactuals:
            if hasattr(cf, "to_dict"):
                counterfactuals.append(cf.to_dict())
            elif isinstance(cf, dict):
                counterfactuals.append(cf)
    except Exception:
        pass
    return {
        "possible_outcomes": outcomes,
        "probabilities": probs,
        "confidence": float(getattr(sim_result, "confidence", 0.0) or 0.0),
        "simulation_time": float(getattr(sim_result, "simulation_time", 0.0) or 0.0),
        "counterfactuals": counterfactuals,
        "details": getattr(sim_result, "details", None),
    }


# ═══════════════════════════════════════════════════════════════
# MCP 工具注册函数
# ═══════════════════════════════════════════════════════════════

def register_world_model_tools(mcp_server: Any) -> None:
    """在指定 FastMCP 实例上注册 world_perceive / world_predict /
    world_calibrate 三个 MCP 工具。

    Args:
        mcp_server: FastMCP 实例（或任何提供 ``tool()`` 装饰器的对象）。
    """
    @mcp_server.tool()
    async def world_perceive(event: str, agent_name: str = "aris") -> str:
        """感知一个事件并更新 agent 的世界状态。

        把上一轮对话结果或环境事件作为 ``event`` 喂给
        ``UnifiedWorldModel.perceive``，触发实体状态更新与时间线记录。

        Args:
            event: JSON 字符串，形如
                ``{"type":"deployment","entity":"服务X","env":"prod","to_state":"生产"}``。
                ``type`` 缺省为 ``event``；``entity`` 缺省时仅写入世界时间线。
            agent_name: Agent 名称，决定使用哪个 agent 的世界模型实例。

        Returns:
            JSON 字符串，含 ``perceived`` / ``event_type`` / ``entity`` /
            ``state_transition`` 字段。
        """
        try:
            event_dict = _parse_json_arg(event)
            wm = _get_world_model(agent_name)
            result = wm.perceive(event_dict)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.exception("world_perceive failed")
            return json.dumps({"perceived": False, "error": str(e)},
                              ensure_ascii=False)

    @mcp_server.tool()
    async def world_predict(entity: str, horizon: int = 1,
                            agent_name: str = "aris") -> str:
        """预测一个实体在未来 horizon 步的状态，并持久化到 prediction_log。

        调用 ``UnifiedWorldModel.predict(entity_id, horizon)``，把
        ``SimulationResult`` 序列化后写入 ``{agent}_vault.db`` 的
        ``prediction_log`` 表，返回 ``prediction_id`` 供后续校准使用。

        Args:
            entity: 实体 ID 或名称（如 ``服务X`` / ``aris``）。
            horizon: 预测步长，默认 1。
            agent_name: Agent 名称，决定写入哪个 agent 的 vault。

        Returns:
            JSON 字符串，含 ``prediction_id`` / ``entity`` / ``horizon`` /
            ``predicted_outcome`` / ``confidence`` / ``created_at`` 字段。
        """
        try:
            wm = _get_world_model(agent_name)
            sim_result = wm.predict(entity, float(horizon))
            outcome = _simulation_to_prediction_outcome(sim_result)
            prediction_id = f"pred_{uuid.uuid4().hex[:12]}"
            created_at = datetime.now(timezone.utc).isoformat()
            record = {
                "prediction_id": prediction_id,
                "agent_name": agent_name,
                "entity": entity,
                "horizon": int(horizon),
                "predicted_outcome": outcome,
                "confidence": outcome.get("confidence", 0.0),
                "created_at": created_at,
            }
            _store_prediction(agent_name, record)
            return json.dumps(record, ensure_ascii=False)
        except Exception as e:
            logger.exception("world_predict failed")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp_server.tool()
    async def world_calibrate(prediction_id: str, actual: str,
                              agent_name: str = "aris") -> str:
        """用真实结果校准一条预测，误差写入元认知反思队列。

        从 ``prediction_log`` 取回 ``prediction_id`` 对应的预测记录，
        调用 ``UnifiedWorldModel.calibrate(prediction, actual)`` 计算误差，
        把误差记录写入 ``EmergentSelfModel.queue_reflection`` 并把
        ``prediction_log`` 中该条标记为已校准。

        Args:
            prediction_id: ``world_predict`` 返回的预测 ID。
            actual: JSON 字符串，描述真实结果，形如
                ``{"outcome":"生产","outcome_score":0.9,"evidence":"..."}``。
            agent_name: Agent 名称。

        Returns:
            JSON 字符串，含 ``calibrated`` / ``prediction_id`` /
            ``error_record`` 字段。
        """
        try:
            actual_dict = _parse_json_arg(actual)
            prediction_row = _get_prediction(agent_name, prediction_id)
            if prediction_row is None:
                return json.dumps(
                    {"calibrated": False,
                     "error": f"prediction {prediction_id} not found in "
                              f"{agent_name} vault"},
                    ensure_ascii=False,
                )

            # 还原 prediction dict 给 calibrate facade 使用
            prediction_for_calibrate = {
                "prediction_id": prediction_row["prediction_id"],
                "entity": prediction_row.get("entity"),
                "predicted_outcome": prediction_row.get("predicted_outcome"),
                "confidence": prediction_row.get("confidence"),
            }

            wm = _get_world_model(agent_name)
            error_record = wm.calibrate(prediction_for_calibrate, actual_dict)

            # 写入 prediction_log（标记已校准 + 真实结果 + 误差）
            _mark_calibrated(agent_name, prediction_id, error_record, actual_dict)

            # 写入元认知反思队列
            sm = _get_self_model(agent_name)
            sm.queue_reflection(error_record)

            return json.dumps(
                {"calibrated": True,
                 "prediction_id": prediction_id,
                 "error_record": error_record},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("world_calibrate failed")
            return json.dumps({"calibrated": False, "error": str(e)},
                              ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 预测调度器 (SubTask 1.4)
# ═══════════════════════════════════════════════════════════════

def maybe_schedule_prediction(agent_name: str, turn_count: int,
                              n: int = 5,
                              entity: Optional[str] = None,
                              horizon: int = 1) -> Optional[Dict[str, Any]]:
    """每 N 轮对话触发一次 world_predict 的预测调度器。

    在 hanako aris-plugin 的 ``session:after.message`` 钩子中调用，
    把当前 ``turn_count`` 传入。当 ``turn_count % n == 0`` 时触发一次
    ``world_predict``（默认预测 agent 自身实体的下一状态），把预测
    写入 ``prediction_log`` 表。否则返回 ``None``。

    Args:
        agent_name: Agent 名称。
        turn_count: 当前对话轮次（从 1 开始递增）。
        n: 调度周期，默认 5。
        entity: 预测目标实体。None 时默认为 agent 自身（``agent_name``）。
        horizon: 预测步长，默认 1。

    Returns:
        预测记录 dict（含 ``prediction_id``）或 ``None``。
    """
    if n <= 0:
        return None
    if turn_count <= 0 or turn_count % n != 0:
        return None
    target_entity = entity or agent_name

    wm = _get_world_model(agent_name)
    sim_result = wm.predict(target_entity, float(horizon))
    outcome = _simulation_to_prediction_outcome(sim_result)
    prediction_id = f"pred_{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "prediction_id": prediction_id,
        "agent_name": agent_name,
        "entity": target_entity,
        "horizon": int(horizon),
        "predicted_outcome": outcome,
        "confidence": outcome.get("confidence", 0.0),
        "created_at": created_at,
        "scheduled": True,
        "turn_count": turn_count,
        "schedule_n": n,
    }
    try:
        _store_prediction(agent_name, record)
    except Exception as e:
        logger.warning(f"maybe_schedule_prediction store failed: {e}")
        record["store_error"] = str(e)
    return record


__all__ = [
    "register_world_model_tools",
    "maybe_schedule_prediction",
    "_get_world_model",
    "_get_self_model",
    "_get_vault_manager",
    "_store_prediction",
    "_get_prediction",
    "_list_predictions",
    "_mark_calibrated",
    "_ensure_prediction_log_table",
]
