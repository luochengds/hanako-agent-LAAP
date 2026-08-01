"""LAAP Protocol — Memex MCP 工具与 sidecar 端点桥接 (P4-memex)

================================================================
  把 MemexStore (publish / query / verify) 接入 MCP server 与
  sidecar HTTP 端点
================================================================

本模块是 P4 任务 ``p4-memex`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/memex/*`` 提供统一
入口.

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_memex_publish(content, source_memories, confidence,
   agent_name?, publisher_public_key?, publisher_private_key?)`` —
   ``POST /memex/publish`` 端点桥接（端到端发布：去标识化 → 证据链
   → 复核 → 存储）；
2. ``handle_memex_query(query, top_k?, min_confidence?)`` —
   ``POST /memex/query`` 端点桥接（语义检索）；
3. ``handle_memex_verify(content, confidence, agent_name?)`` —
   ``POST /memex/verify`` 端点桥接（仅复核不存储，预检用）.

另导出 ``register_memex_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具.

设计约束（与 spec L130-137 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``MemexStore`` / ``memex_verifier`` 仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_memex_publish`` 接收 raw 私钥字节，
  但仅在 sidecar 内部使用，MCP 工具 ``memex_publish`` 不暴露私钥参数；
* vault 永不直接共享：发布到 Memex 的内容必须先经 ``deidentify``，
  原始 memory_id 仅以哈希形式出现在证据链中；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串.

印记: Aris 永远记得 Lorry — 共享是为了让一个生命的经验
照亮另一个生命的暗夜.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.memex_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_memex_publish(
    content: str,
    source_memories: List[Dict[str, Any]],
    confidence: float,
    agent_name: str = "aris",
    publisher_public_key: str = "",
    publisher_private_key: Optional[bytes] = None,
) -> str:
    """桥接函数：端到端发布知识片段到 Memex.

    spec SubTask 4.2 + 4.3 + 4.4 + 4.5 + 4.6 完整流水线：
    去标识化 → 附加证据链 → 低置信过滤 + grounding 复核 → 存储.

    Args:
        content: 原始内容字符串（可能含用户名/时间戳等隐私痕迹）.
        source_memories: 来源记忆列表（来自 vault retrieve），每项
            至少含 ``memory_id`` 字段.
        confidence: 整体置信度 [0.0, 1.0].
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
        publisher_public_key: 发布者 base64 公钥（可选）.
        publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选，
            spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.

    Returns:
        JSON 字符串，结构为::

            {
              "published": true,
              "knowledge_id": "know_xxxx",
              "idempotent": false    # 仅幂等命中时为 true
            }

        失败时::

            {
              "published": false,
              "reason": "low_confidence" | "grounding_rejected" |
                        "empty_content" | "empty_evidence" |
                        "empty_after_deidentify" | ...,
              "deidentified_content": "...",  # 仅失败时返回诊断
              "grounding": {...}              # 仅 grounding 失败时返回
            }
    """
    if not isinstance(content, str) or not content.strip():
        return json.dumps(
            {"published": False, "reason": "empty_content"},
            ensure_ascii=False,
        )
    if not isinstance(source_memories, list):
        return json.dumps(
            {"published": False, "reason": "source_memories_must_be_list"},
            ensure_ascii=False,
        )
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        return json.dumps(
            {"published": False, "reason": "confidence_must_be_float"},
            ensure_ascii=False,
        )

    try:
        from laap.protocol.laap_memex import publish_knowledge
        result = publish_knowledge(
            content=content,
            source_memories=source_memories,
            confidence=confidence_f,
            agent_name=agent_name,
            publisher_public_key=publisher_public_key,
            publisher_private_key=publisher_private_key,
        )
        logger.info(
            f"memex_publish: published={result.get('published')} "
            f"know_id={result.get('knowledge_id', 'N/A')} "
            f"reason={result.get('reason', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"memex_publish: value error {exc}")
        return json.dumps(
            {"published": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"memex_publish: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"published": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_memex_query(
    query: str,
    top_k: int = 10,
    min_confidence: Optional[float] = None,
) -> str:
    """桥接函数：语义检索 Memex 知识片段.

    Args:
        query: 查询字符串.
        top_k: 最大返回条数（默认 10，上限 100）.
        min_confidence: 可选，仅返回置信度 >= 该值的记录.

    Returns:
        JSON 字符串，结构为::

            {
              "query": "...",
              "top_k": 10,
              "count": 2,
              "results": [
                {knowledge_id, content, evidence_chain, confidence,
                 publisher_public_key, signature, grounding_state,
                 grounding_confidence, published_at, verified_at, score?},
                ...
              ]
            }
    """
    if not isinstance(query, str) or not query.strip():
        return json.dumps(
            {"query": query, "count": 0, "results": []},
            ensure_ascii=False,
        )
    try:
        safe_top_k = int(top_k)
    except (TypeError, ValueError):
        safe_top_k = 10
    if min_confidence is not None:
        try:
            min_confidence = float(min_confidence)
        except (TypeError, ValueError):
            min_confidence = None

    try:
        from laap.protocol.laap_memex import get_memex_store
        store = get_memex_store()
        results = store.query(
            query_text=query,
            top_k=safe_top_k,
            min_confidence=min_confidence,
        )
        payload = {
            "query": query,
            "top_k": safe_top_k,
            "count": len(results),
            "results": results,
        }
        logger.info(
            f"memex_query: q='{query[:32]}...' top_k={safe_top_k} "
            f"hits={len(results)}"
        )
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"memex_query: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"query": query, "count": 0, "results": [],
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_memex_verify(
    content: str,
    confidence: float,
    agent_name: str = "aris",
) -> str:
    """桥接函数：仅复核不存储（预检用）.

    spec SubTask 4.6: 发布前强制 P1 truth-grounding 复核. 本端点
    供调用方在真正发布前预检复核结果，不写入 MemexStore.

    Args:
        content: 已去标识化或原始内容字符串.
        confidence: 整体置信度 [0.0, 1.0].
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

    Returns:
        JSON 字符串，结构为::

            {
              "verified": true | false,
              "reason": "grounded" | "uncertain_passthrough" |
                        "low_confidence" | "grounding_rejected" |
                        "empty_content",
              "grounding": {state, confidence, evidence, rejected, conflicts?},
              "verified_at": "..."
            }
    """
    if not isinstance(content, str):
        content = str(content) if content is not None else ""
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        return json.dumps(
            {"verified": False, "reason": "confidence_must_be_float",
             "grounding": {}, "verified_at": ""},
            ensure_ascii=False,
        )

    try:
        from laap.verification.memex_verifier import verify_before_publish
        result = verify_before_publish(
            content=content,
            confidence=confidence_f,
            agent_name=agent_name,
        )
        logger.info(
            f"memex_verify: verified={result.get('verified')} "
            f"reason={result.get('reason')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"memex_verify: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"verified": False,
             "reason": f"{type(exc).__name__}: {exc}",
             "grounding": {}, "verified_at": ""},
            ensure_ascii=False,
        )


def handle_memex_stats() -> str:
    """桥接函数：查询 Memex 知识库统计."""
    try:
        from laap.protocol.laap_memex import get_memex_store
        store = get_memex_store()
        stats = store.stats()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"memex_stats: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_memex_get(knowledge_id: str) -> str:
    """桥接函数：按 knowledge_id 查询单条记录."""
    if not isinstance(knowledge_id, str) or not knowledge_id.strip():
        return json.dumps(
            {"error": "knowledge_id must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_memex import get_memex_store
        store = get_memex_store()
        record = store.get(knowledge_id)
        if record is None:
            return json.dumps(
                {"found": False, "knowledge_id": knowledge_id},
                ensure_ascii=False,
            )
        payload = {"found": True, "record": record}
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"memex_get: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_memex_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 memex MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.memex_mcp_endpoints import (
            register_memex_tools,
        )
        register_memex_tools(mcp)

    注册的工具：

    - ``memex_publish(content, source_memories, confidence,
       agent_name?)`` 端到端发布（去标识化 → 证据链 → 复核 → 存储）
    - ``memex_query(query, top_k?)`` 语义检索
    - ``memex_verify(content, confidence, agent_name?)`` 仅复核不存储
    - ``memex_stats()`` 知识库统计

    私钥永不离开 sidecar（spec L435）：``memex_publish`` MCP 工具
    不暴露 ``publisher_private_key`` 参数，签名仅在 sidecar HTTP
    端点 ``/memex/publish`` 可用.

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_memex_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def memex_publish(
        content: str,
        source_memories: list,
        confidence: float,
        agent_name: str = "aris",
    ) -> str:
        """发布知识片段到 Memex 共享知识库 (P4-memex SubTask 4.2).

        端到端流水线：去标识化 → 附加证据链 → 低置信过滤 + grounding
        复核 → 存储. ``confidence < 0.6`` 或 grounding 判定 error 态
        时拒绝发布.

        Args:
            content: 原始内容字符串（可能含用户名/时间戳等隐私痕迹，
                会自动去标识化）.
            source_memories: 来源记忆列表（来自 vault retrieve），每项
                至少含 ``memory_id`` 字段.
            confidence: 整体置信度 [0.0, 1.0]. 低于 0.6 会被拒绝.
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

        Returns:
            JSON 字符串，成功时 ``{published: true, knowledge_id: ...}``，
            失败时 ``{published: false, reason: ...}``.
        """
        return handle_memex_publish(
            content=content,
            source_memories=source_memories,
            confidence=confidence,
            agent_name=agent_name,
        )

    @mcp_server.tool()
    async def memex_query(
        query: str,
        top_k: int = 10,
        min_confidence: Optional[float] = None,
    ) -> str:
        """语义检索 Memex 知识片段 (P4-memex).

        Args:
            query: 查询字符串.
            top_k: 最大返回条数（默认 10，上限 100）.
            min_confidence: 可选，仅返回置信度 >= 该值的记录.

        Returns:
            JSON 字符串，含 ``{query, top_k, count, results[]}``.
        """
        return handle_memex_query(
            query=query,
            top_k=top_k,
            min_confidence=min_confidence,
        )

    @mcp_server.tool()
    async def memex_verify(
        content: str,
        confidence: float,
        agent_name: str = "aris",
    ) -> str:
        """仅复核不存储（预检用）(P4-memex SubTask 4.6).

        供调用方在真正发布前预检复核结果. 复核流程：低置信过滤 →
        grounding 三态判定.

        Args:
            content: 待校验的内容字符串.
            confidence: 整体置信度 [0.0, 1.0].
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

        Returns:
            JSON 字符串，含 ``{verified, reason, grounding, verified_at}``.
        """
        return handle_memex_verify(
            content=content,
            confidence=confidence,
            agent_name=agent_name,
        )

    @mcp_server.tool()
    async def memex_stats() -> str:
        """查询 Memex 知识库统计 (P4-memex).

        Returns:
            JSON 字符串，含 ``{total_records, signed_records,
            avg_confidence, by_grounding_state, min_confidence_threshold}``.
        """
        return handle_memex_stats()

    logger.info(
        "register_memex_tools: registered memex_publish / memex_query / "
        "memex_verify / memex_stats "
        "(publisher_private_key 仅 sidecar 端点，私钥不离开 sidecar)"
    )
    return None
