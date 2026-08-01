"""LAAP AGI — 因果引擎 MCP 工具 (P1-causal-engine)

本模块为 p1-causal-engine 任务的核心产出物，提供三个稳定 MCP 工具：

  - ``causal_infer(cause, effect, do=False)``      执行 do-演算反事实推理
  - ``causal_query(graph_id=None, agent_name=...)`` 查询 agent 私有因果图
  - ``causal_learn(observations, agent_name=...)``  从对话观察归纳因果边

设计要点
========

1. **agent 隔离**：每个 agent 的因果图存入 ``{agent}_vault.db`` 的 ``causal_graph``
   表，跨 agent 严格隔离。复用 ``laap.memory_vault.vault_manager`` 的加密连接。
2. **不修改共享文件**：本模块导出 ``register_causal_tools(mcp_server)``，由
   ``laap/mcp/server.py`` 的 ``build_server()`` 调用以注册三工具；本模块自身不
   依赖 server.py。
3. **因果线索检测**：``detect_causal_clues(content, metadata)`` 与
   ``causal_learn_from_clues(agent_name, content, metadata)`` 用于在
   ``memory_store`` 工具体末尾调用，自动从含 ``cause/effect`` 元数据的内容中
   增量更新因果图。检测逻辑独立为本模块函数，避免修改 server.py 的核心逻辑。
4. **幂等**：所有建表用 ``CREATE TABLE IF NOT EXISTS``，写库用 ``INSERT OR
   REPLACE``，重复执行不报错不破坏数据。
5. **不引入 LLM 依赖**：P1 阶段因果图归纳由 ``CausalDiscovery.fit``（模板/
   规则）完成，无外部 LLM 调用。

印记: Aris 永远记得 Lorry — 因果图生长在 Aris 自己的 vault 里。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.agi.causal_mcp_tools")


# ─── 因果图 vault 表 ────────────────────────────────────────────
#
# 表 schema 设计：
#   - edge_id        主键（确定性 hash，保证幂等）
#   - agent_name     归属 agent
#   - cause / effect 因果边端点
#   - confidence     置信度 0~1
#   - source         来源（learn / clue / fit / discovery）
#   - observations   观测次数
#   - metadata_json  额外元数据
#   - created_at     首次写入时间
#   - updated_at     最近更新时间
#
# 跨 agent 隔离由 vault_manager 的 per-agent db 文件保证：每个 agent 拥有独立
# 的 {agent}_vault.db，本表只在该 agent 的 vault 内创建。

_CAUSAL_GRAPH_DDL = """
CREATE TABLE IF NOT EXISTS causal_graph (
    edge_id        TEXT PRIMARY KEY,
    agent_name     TEXT NOT NULL,
    cause          TEXT NOT NULL,
    effect         TEXT NOT NULL,
    confidence     REAL DEFAULT 0.5,
    source         TEXT DEFAULT 'learn',
    observations   INTEGER DEFAULT 1,
    metadata_json  TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_causal_graph_agent
    ON causal_graph(agent_name);
CREATE INDEX IF NOT EXISTS idx_causal_graph_cause
    ON causal_graph(cause);
CREATE INDEX IF NOT EXISTS idx_causal_graph_effect
    ON causal_graph(effect);
"""


def _now_iso() -> str:
    """当前 UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _edge_id(cause: str, effect: str) -> str:
    """由 (cause, effect) 确定性生成的稳定 edge_id，保证幂等。

    同一对 (cause, effect) 永远映射到同一 edge_id，使 ``INSERT OR REPLACE``
    真正实现 upsert 语义。
    """
    raw = f"{cause.strip()}→{effect.strip()}".lower()
    return "cg_" + uuid.uuid5(uuid.NAMESPACE_OID, raw).hex[:16]


def _open_agent_vault(agent_name: str) -> Tuple[str, str]:
    """打开 agent 的 vault，返回 (db_path, key_hex)。

    复用 ``vault_manager._get_vault``（幂等：若 vault 不存在则自动初始化）。
    """
    from laap.memory_vault.vault_manager import vault_manager
    return vault_manager._get_vault(agent_name)


def _ensure_causal_graph_table(conn: sqlite3.Connection) -> None:
    """在给定连接上幂等创建 causal_graph 表与索引。"""
    conn.executescript(_CAUSAL_GRAPH_DDL)
    conn.commit()


def _get_agent_vault_dir() -> Optional[str]:
    """返回 vault_manager 当前的 vault_dir（供测试 monkeypatch）。"""
    try:
        from laap.memory_vault.vault_manager import vault_manager
        return getattr(vault_manager, "vault_dir", None)
    except Exception:
        return None


# ─── 因果图读写核心 API ─────────────────────────────────────────


def causal_graph_upsert_edge(
    agent_name: str,
    cause: str,
    effect: str,
    confidence: float = 0.5,
    source: str = "learn",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """向 agent 的 causal_graph 表 upsert 一条因果边。

    幂等：同一 (agent, cause, effect) 重复写入时只增加 observations 计数与
    滚动更新 confidence，不重复添加行。

    Args:
        agent_name: Agent 名称
        cause: 原因变量名
        effect: 效应变量名
        confidence: 置信度 [0, 1]
        source: 来源标签 (learn / clue / fit / discovery)
        metadata: 额外元数据

    Returns:
        ``{"edge_id": str, "cause": str, "effect": str,
           "confidence": float, "observations": int, "upserted": True}``
    """
    if not cause or not effect or cause.strip() == effect.strip():
        raise ValueError("cause and effect must be non-empty and distinct")
    confidence = max(0.0, min(1.0, float(confidence)))
    db_path, key_hex = _open_agent_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    eid = _edge_id(cause, effect)
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    try:
        _ensure_causal_graph_table(conn)
        # 查询是否已存在
        row = conn.execute(
            "SELECT edge_id, confidence, observations FROM causal_graph WHERE edge_id = ?",
            (eid,),
        ).fetchone()
        now = _now_iso()
        if row is None:
            conn.execute(
                """INSERT INTO causal_graph
                   (edge_id, agent_name, cause, effect, confidence, source,
                    observations, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, agent_name, cause.strip(), effect.strip(),
                 confidence, source, 1, meta_json, now, now),
            )
            conn.commit()
            return {
                "edge_id": eid,
                "cause": cause.strip(),
                "effect": effect.strip(),
                "confidence": confidence,
                "observations": 1,
                "upserted": True,
            }
        else:
            old_conf = float(row["confidence"])
            old_obs = int(row["observations"])
            new_obs = old_obs + 1
            # 滚动平均置信度
            new_conf = round((old_conf * old_obs + confidence) / new_obs, 4)
            # 合并 metadata（新 metadata 覆盖旧 metadata 的同名字段）
            try:
                old_meta = json.loads(
                    conn.execute(
                        "SELECT metadata_json FROM causal_graph WHERE edge_id = ?",
                        (eid,),
                    ).fetchone()["metadata_json"]
                    or "{}"
                )
            except (json.JSONDecodeError, TypeError):
                old_meta = {}
            merged_meta = {**old_meta, **(metadata or {})}
            conn.execute(
                """UPDATE causal_graph
                   SET confidence = ?, observations = ?, metadata_json = ?,
                       updated_at = ?, source = ?
                   WHERE edge_id = ?""",
                (new_conf, new_obs,
                 json.dumps(merged_meta, ensure_ascii=False),
                 now, source, eid),
            )
            conn.commit()
            return {
                "edge_id": eid,
                "cause": cause.strip(),
                "effect": effect.strip(),
                "confidence": new_conf,
                "observations": new_obs,
                "upserted": True,
            }
    finally:
        conn.close()


def causal_graph_query(
    agent_name: str,
    graph_id: Optional[str] = None,
    cause: Optional[str] = None,
    effect: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """查询 agent 的 causal_graph 表。

    跨 agent 隔离：只返回该 agent vault 中的边。

    Args:
        agent_name: Agent 名称
        graph_id: 可选，预留参数（P1 阶段每 agent 单图，忽略）
        cause: 可选，按 cause 模糊过滤
        effect: 可选，按 effect 模糊过滤
        limit: 最大返回条数

    Returns:
        因果边 dict 列表
    """
    db_path, key_hex = _open_agent_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_causal_graph_table(conn)
        clauses: List[str] = []
        params: List[Any] = []
        if cause:
            clauses.append("cause LIKE ?")
            params.append(f"%{cause}%")
        if effect:
            clauses.append("effect LIKE ?")
            params.append(f"%{effect}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        safe_limit = max(1, min(int(limit), 500))
        params.append(safe_limit)
        rows = conn.execute(
            f"""SELECT edge_id, agent_name, cause, effect, confidence,
                       source, observations, metadata_json,
                       created_at, updated_at
                FROM causal_graph{where}
                ORDER BY updated_at DESC LIMIT ?""",
            params,
        ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            results.append(d)
        return results
    finally:
        conn.close()


def causal_graph_stats(agent_name: str) -> Dict[str, Any]:
    """返回 agent 因果图统计信息。"""
    db_path, key_hex = _open_agent_vault(agent_name)
    from laap.memory_vault.vault_manager import _open_vault_connection
    conn = _open_vault_connection(db_path, key_hex)
    try:
        _ensure_causal_graph_table(conn)
        total = conn.execute(
            "SELECT COUNT(*) as c FROM causal_graph"
        ).fetchone()["c"]
        by_source: Dict[str, int] = {}
        for row in conn.execute(
            "SELECT source, COUNT(*) as c FROM causal_graph GROUP BY source"
        ).fetchall():
            by_source[row["source"]] = int(row["c"])
        latest = conn.execute(
            "SELECT MAX(updated_at) as t FROM causal_graph"
        ).fetchone()["t"]
        return {
            "agent_name": agent_name,
            "total_edges": int(total),
            "by_source": by_source,
            "latest_update": latest,
        }
    finally:
        conn.close()


# ─── 因果线索检测（供 memory_store 工具联动） ──────────────────


# 线索关键词：content 或 metadata 中出现这些字段的 cause/effect 配对时触发
_CAUSE_KEYS = ("cause", "原因", "因为", "由于", "起因")
_EFFECT_KEYS = ("effect", "结果", "所以", "导致", "效应")
# 显式箭头模式：cause->effect / cause=>effect / cause→effect
# cause 部分排除常见中英文标点，避免匹配到 "用户提到：熬夜" 这种前缀
_ARROW_RE = re.compile(
    r"([^\s\-：，。；,;:()\[\]【】\"']+?)\s*(?:->|=>|→|::)\s*"
    r"([^\s,;：，。；\n]+)"
)


def detect_causal_clues(
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """从 content / metadata 中检测因果线索。

    检测规则（任一命中即产生一条线索）：

    1. metadata 显式声明 ``{"cause": ..., "effect": ...}``（或同义词）
    2. content 含 ``cause->effect`` / ``cause=>effect`` / ``cause→effect`` 箭头
    3. content 含 ``因为X所以Y`` / ``由于X导致Y`` 中文模式

    Args:
        content: 文本内容
        metadata: 可选元数据 dict

    Returns:
        线索列表，每项 ``{"cause": str, "effect": str, "source": str,
        "confidence": float}``。无线索时返回 ``[]``。
    """
    clues: List[Dict[str, str]] = []
    if not isinstance(content, str):
        content = str(content) if content is not None else ""
    if metadata is None:
        metadata = {}

    # 规则 1: metadata 显式声明
    cause_val = effect_val = None
    for k in _CAUSE_KEYS:
        if k in metadata and metadata[k]:
            cause_val = str(metadata[k]).strip()
            break
    for k in _EFFECT_KEYS:
        if k in metadata and metadata[k]:
            effect_val = str(metadata[k]).strip()
            break
    if cause_val and effect_val and cause_val != effect_val:
        try:
            conf = float(metadata.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        clues.append({
            "cause": cause_val,
            "effect": effect_val,
            "source": "metadata",
            "confidence": max(0.0, min(1.0, conf)),
        })

    # 规则 2: 箭头模式
    for m in _ARROW_RE.finditer(content):
        c = m.group(1).strip(" \t\"'()[]【】")
        e = m.group(2).strip(" \t\"'()[]【】,.;")
        if c and e and c != e and len(c) < 80 and len(e) < 80:
            clues.append({
                "cause": c,
                "effect": e,
                "source": "arrow",
                "confidence": 0.6,
            })

    # 规则 3: 中文因果模式
    # "因为X所以Y" / "由于X导致Y" / "X导致Y" / "X引起Y"
    cn_patterns = [
        re.compile(r"因为\s*([^\s,；。]{1,40}?)\s*所以\s*([^\s,；。]{1,40})"),
        re.compile(r"由于\s*([^\s,；。]{1,40}?)\s*(?:导致|引起|使得)\s*([^\s,；。]{1,40})"),
        re.compile(r"([^\s,；。因为由于]{1,30}?)\s*导致\s*([^\s,；。]{1,40})"),
        re.compile(r"([^\s,；。因为由于]{1,30}?)\s*引起\s*([^\s,；。]{1,40})"),
    ]
    for pat in cn_patterns:
        for m in pat.finditer(content):
            c = m.group(1).strip(" \t\"'()[]【】")
            e = m.group(2).strip(" \t\"'()[]【】,.;")
            if c and e and c != e:
                # 去重（与已有线索比对，忽略 source/confidence 差异）
                if not any(
                    x["cause"] == c and x["effect"] == e for x in clues
                ):
                    clues.append({
                        "cause": c,
                        "effect": e,
                        "source": "pattern_cn",
                        "confidence": 0.55,
                    })

    return clues


def causal_learn_from_clues(
    agent_name: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从 content + metadata 检测因果线索并写入 agent 因果图。

    供 ``memory_store`` 工具体末尾调用：每次写入记忆后顺便检测线索，
    若有则增量更新因果图。

    Args:
        agent_name: Agent 名称
        content: 记忆内容文本
        metadata: 记忆元数据

    Returns:
        ``{"clues_detected": int, "edges_upserted": int,
           "edges": [...], "agent_name": str}``
    """
    clues = detect_causal_clues(content, metadata)
    upserted: List[Dict[str, Any]] = []
    for clue in clues:
        try:
            result = causal_graph_upsert_edge(
                agent_name=agent_name,
                cause=clue["cause"],
                effect=clue["effect"],
                confidence=clue.get("confidence", 0.5),
                source="clue",
                metadata={"detected_by": clue["source"]},
            )
            upserted.append(result)
        except Exception as e:
            logger.warning(
                "causal_learn_from_clues upsert failed for %s→%s: %s",
                clue.get("cause"), clue.get("effect"), e,
            )
    return {
        "clues_detected": len(clues),
        "edges_upserted": len(upserted),
        "edges": upserted,
        "agent_name": agent_name,
    }


# ─── 因果引擎实例缓存 ───────────────────────────────────────────
#
# 每个 agent 持有一个 UnifiedCausalEngine 实例（内存态），与 vault 中
# causal_graph 表协同：fit/infer 操作在内存引擎上执行，learn 操作同时写
# vault 与内存引擎。P1 阶段简化处理：每次工具调用按需重建引擎并从 vault
# 重新加载 edges，避免引入跨调用状态。

_ENGINE_CACHE: Dict[str, Any] = {}
_ENGINE_CACHE_TS: Dict[str, float] = {}
_ENGINE_TTL = 60.0  # 60 秒内复用同一实例


def _get_engine_for_agent(agent_name: str):
    """获取 agent 的 UnifiedCausalEngine 实例（带 TTL 缓存）。

    若 causal.py 不可用（依赖缺失），返回 None。
    """
    now = time.time()
    cached = _ENGINE_CACHE.get(agent_name)
    cached_ts = _ENGINE_CACHE_TS.get(agent_name, 0.0)
    if cached is not None and (now - cached_ts) < _ENGINE_TTL:
        return cached
    try:
        from laap.agi.causal import UnifiedCausalEngine
        engine = UnifiedCausalEngine(name=f"causal_{agent_name}")
    except Exception as e:
        logger.warning("UnifiedCausalEngine init failed for %s: %s", agent_name, e)
        return None
    # 从 vault 加载已有 edges 到引擎的 bonds（用于 predict/intervene）
    try:
        edges = causal_graph_query(agent_name, limit=500)
        for e in edges:
            try:
                engine.learn_bond(
                    action=e["cause"],
                    target=agent_name,
                    effect=e["effect"],
                    matched=True,
                    domain="learned",
                )
            except Exception:
                pass
    except Exception as e:
        logger.debug("load edges to engine failed: %s", e)
    _ENGINE_CACHE[agent_name] = engine
    _ENGINE_CACHE_TS[agent_name] = now
    return engine


# ─── MCP 工具注册 ───────────────────────────────────────────────


def register_causal_tools(mcp_server) -> None:
    """向 FastMCP 实例注册因果引擎三工具。

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.agi.causal_mcp_tools import register_causal_tools
        register_causal_tools(mcp)

    注册的三个工具：

    - ``causal_infer(cause, effect, do=False)``       do-演算反事实推理
    - ``causal_query(graph_id=None, agent_name="aris")`` 查询 agent 因果图
    - ``causal_learn(observations, agent_name="aris")``  从观察列表归纳边

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）
    """
    @mcp_server.tool()
    async def causal_infer(cause: str, effect: str, do: bool = False) -> str:
        """执行 do-演算反事实推理。

        基于 agent 私有因果图，对 ``cause → effect`` 关系进行推理。当
        ``do=True`` 时执行 Pearl do-演算（干预），返回 ``p(effect|do(cause))``；
        否则仅观察性查询 ``p(effect|cause)``。

        Args:
            cause: 原因变量名（如 "熬夜"）
            effect: 效应变量名（如 "bug"）
            do: 是否执行 do-演算干预，默认 False

        Returns:
            JSON 字符串，结构为::

                {
                  "cause": "...",
                  "effect": "...",
                  "do": true,
                  "p_effect_given_do": 0.78,
                  "confidence": 0.65,
                  "reasoning_path": ["do(...)", ...],
                  "intervention": "do(cause=True)"
                }
        """
        try:
            from laap.agi.causal import do_calculus
            # 默认 agent = "aris"（P1 阶段单 agent；可通过 metadata 扩展）
            agent_name = "aris"
            engine = _get_engine_for_agent(agent_name)
            if engine is None:
                return json.dumps({
                    "cause": cause,
                    "effect": effect,
                    "do": do,
                    "p_effect_given_do": 0.0,
                    "confidence": 0.0,
                    "reasoning_path": ["engine unavailable"],
                    "error": "UnifiedCausalEngine not available",
                }, ensure_ascii=False)
            result = do_calculus(engine, cause, effect, do=do)
            result["cause"] = cause
            result["effect"] = effect
            result["do"] = do
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "cause": cause,
                "effect": effect,
                "do": do,
                "p_effect_given_do": 0.0,
                "confidence": 0.0,
                "reasoning_path": [f"causal_infer failed: {e}"],
                "error": str(e),
            }, ensure_ascii=False)

    @mcp_server.tool()
    async def causal_query(
        graph_id: Optional[str] = None,
        agent_name: str = "aris",
    ) -> str:
        """查询 agent 私有因果图。

        返回该 agent vault 中 ``causal_graph`` 表的全部边与统计信息。跨 agent
        严格隔离：调用方指定 ``agent_name="butter"`` 时只返回 butter 的图。

        Args:
            graph_id: 可选，预留参数（P1 阶段每 agent 单图，忽略）
            agent_name: Agent 名称，默认 "aris"

        Returns:
            JSON 字符串，结构为::

                {
                  "agent_name": "aris",
                  "graph_id": null,
                  "edges": [{"edge_id", "cause", "effect",
                            "confidence", "observations", ...}, ...],
                  "stats": {"total_edges": int, "by_source": {...}}
                }
        """
        try:
            edges = causal_graph_query(agent_name, limit=500)
            stats = causal_graph_stats(agent_name)
            return json.dumps({
                "agent_name": agent_name,
                "graph_id": graph_id,
                "edges": edges,
                "stats": stats,
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "agent_name": agent_name,
                "graph_id": graph_id,
                "edges": [],
                "error": str(e),
            }, ensure_ascii=False)

    @mcp_server.tool()
    async def causal_learn(
        observations: str,
        agent_name: str = "aris",
    ) -> str:
        """从观察列表归纳因果边并写入 agent 私有因果图。

        每条观察会被转换为 ``cause → effect`` 边，upsert 到
        ``{agent}_vault.db`` 的 ``causal_graph`` 表。重复观察只增加
        ``observations`` 计数与滚动更新 confidence，不重复添加行。

        Args:
            observations: JSON 数组字符串，元素形如
                ``{"cause": "...", "effect": "...", "confidence"?: 0.5}``，
                也接受 ``["cause->effect", ...]`` 或
                ``[["cause", "effect"], ...]`` 形式。
            agent_name: Agent 名称，默认 "aris"

        Returns:
            JSON 字符串，结构为::

                {
                  "agent_name": "aris",
                  "edges_added": 3,
                  "graph_version": "v1",
                  "edges": [...]
                }
        """
        try:
            parsed = json.loads(observations) if isinstance(observations, str) else observations
            if not isinstance(parsed, list):
                return json.dumps({
                    "agent_name": agent_name,
                    "edges_added": 0,
                    "error": "observations must be a JSON array",
                }, ensure_ascii=False)
            # 调用 CausalDiscovery.fit（facade）做内存态归纳
            edges_added = 0
            try:
                from laap.agi.causal import CausalDiscovery
                cd = CausalDiscovery()
                fit_result = cd.fit(parsed)
                edges_added = fit_result.get("edges_added", 0)
            except Exception as e:
                logger.debug("CausalDiscovery.fit failed: %s", e)
            # 同步到 agent vault 的 causal_graph 表
            upserted: List[Dict[str, Any]] = []
            for obs in parsed:
                cause = effect = None
                confidence = 0.5
                if isinstance(obs, dict):
                    cause = str(obs.get("cause", "")).strip()
                    effect = str(obs.get("effect", "")).strip()
                    try:
                        confidence = float(obs.get("confidence", 0.5))
                    except (TypeError, ValueError):
                        confidence = 0.5
                elif isinstance(obs, (list, tuple)) and len(obs) >= 2:
                    cause = str(obs[0]).strip()
                    effect = str(obs[1]).strip()
                    if len(obs) > 2:
                        try:
                            confidence = float(obs[2])
                        except (TypeError, ValueError):
                            pass
                elif isinstance(obs, str) and "->" in obs:
                    parts = obs.split("->", 1)
                    cause = parts[0].strip()
                    effect = parts[1].strip()
                if not cause or not effect or cause == effect:
                    continue
                try:
                    r = causal_graph_upsert_edge(
                        agent_name=agent_name,
                        cause=cause,
                        effect=effect,
                        confidence=confidence,
                        source="learn",
                    )
                    upserted.append(r)
                except Exception as e:
                    logger.warning(
                        "causal_learn upsert failed %s→%s: %s",
                        cause, effect, e,
                    )
            # 失效引擎缓存，使下次 infer 重新加载
            _ENGINE_CACHE.pop(agent_name, None)
            _ENGINE_CACHE_TS.pop(agent_name, None)
            return json.dumps({
                "agent_name": agent_name,
                "edges_added": len(upserted),
                "fit_edges_added": edges_added,
                "graph_version": f"v{int(time.time())}",
                "edges": upserted,
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "agent_name": agent_name,
                "edges_added": 0,
                "error": str(e),
            }, ensure_ascii=False)

    logger.info(
        "register_causal_tools: registered causal_infer / causal_query / causal_learn"
    )
    return None
