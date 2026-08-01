"""LAAP Protocol — Coevolution MCP 工具与 sidecar 端点桥接 (P4-coevolution-loop)

================================================================
  把 CoevolutionLoop (share / absorb / feedback / graph) 接入
  MCP server 与 sidecar HTTP 端点
================================================================

本模块是 P4 任务 ``p4-coevolution-loop`` 的 MCP 工具注册交付物，
为 ``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/coevolution/*``
提供统一入口.

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_coevolution_share(agent, content, source_memories,
   confidence, agent_name?, publisher_public_key?,
   publisher_private_key?)`` —
   ``POST /coevolution/share`` 端点桥接（分享经验到共同进化图）；
2. ``handle_coevolution_absorb(agent, shared_id, agent_name?,
   publisher_public_key?, publisher_private_key?)`` —
   ``POST /coevolution/absorb`` 端点桥接（吸收经验并派生新经验）；
3. ``handle_coevolution_feedback(new_experience_id, derived_from)`` —
   ``POST /coevolution/feedback`` 端点桥接（经验回传通知原分享者）；
4. ``handle_coevolution_graph(limit?)`` —
   ``GET /coevolution/graph`` 端点桥接（导出共同进化图）；
5. ``handle_coevolution_stats()`` —
   ``GET /coevolution/stats`` 端点桥接（图统计）；
6. ``handle_coevolution_get(experience_id)`` —
   ``GET /coevolution/get`` 端点桥接（按 ID 查节点）.

另导出 ``register_coevolution_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具.

设计约束（与 spec L139-145 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``CoevolutionLoop`` 仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_coevolution_share/absorb`` 接收
  raw 私钥字节，仅在 sidecar 内部使用，MCP 工具不暴露私钥参数；
* vault 永不直接共享：经验必须先经 Memex ``deidentify``；
* LLM 调用必经 truth-grounding 管线（``absorb`` 内部已强制）；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串.

印记: 经验在两个生命之间流转，从此不再是孤岛.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.coevolution_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_coevolution_share(
    agent: str,
    content: str,
    source_memories: List[Dict[str, Any]],
    confidence: float,
    agent_name: str = "coevo",
    publisher_public_key: str = "",
    publisher_private_key: Optional[bytes] = None,
) -> str:
    """桥接函数：分享一条个人经验到共同进化图.

    spec SubTask 4.1 端到端：去标识化 → 证据链 → grounding 复核 →
    存储 → 共同进化图根节点.

    Args:
        agent: 分享者 agent 标识.
        content: 原始经验内容字符串（会自动去标识化）.
        source_memories: 来源记忆列表，每项至少含 ``memory_id`` 字段.
        confidence: 整体置信度 [0.0, 1.0]. 低于 0.6 会被 Memex 拒绝.
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
        publisher_public_key: 发布者 base64 公钥（可选）.
        publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选，
            spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.

    Returns:
        JSON 字符串，结构为 ``{shared: bool, reason?: str,
        shared_id?: str, knowledge_id?: str}``.
    """
    if not isinstance(agent, str) or not agent.strip():
        return json.dumps(
            {"shared": False, "reason": "empty_agent"},
            ensure_ascii=False,
        )
    if not isinstance(content, str) or not content.strip():
        return json.dumps(
            {"shared": False, "reason": "empty_content"},
            ensure_ascii=False,
        )
    if not isinstance(source_memories, list):
        return json.dumps(
            {"shared": False, "reason": "source_memories_must_be_list"},
            ensure_ascii=False,
        )
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        return json.dumps(
            {"shared": False, "reason": "confidence_must_be_float"},
            ensure_ascii=False,
        )

    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent=agent,
            content=content,
            source_memories=source_memories,
            confidence=confidence_f,
            agent_name=agent_name,
            publisher_public_key=publisher_public_key,
            publisher_private_key=publisher_private_key,
        )
        logger.info(
            f"coevolution_share: shared={result.get('shared')} "
            f"shared_id={result.get('shared_id', 'N/A')} "
            f"reason={result.get('reason', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"coevolution_share: value error {exc}")
        return json.dumps(
            {"shared": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"coevolution_share: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"shared": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_absorb(
    agent: str,
    shared_id: str,
    agent_name: str = "coevo",
    publisher_public_key: str = "",
    publisher_private_key: Optional[bytes] = None,
) -> str:
    """桥接函数：吸收共享经验并派生新经验.

    spec SubTask 4.2 端到端：取父经验 → LLM 提炼吸收摘要
    （必经 truth-grounding 管线）→ 派生经验发布回 Memex →
    共同进化图子节点.

    Args:
        agent: 吸收方 agent 标识.
        shared_id: 父经验节点 ID.
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
        publisher_public_key: 发布者 base64 公钥（可选）.
        publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选，
            spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.

    Returns:
        JSON 字符串，结构为 ``{absorbed: bool, reason?: str,
        new_experience_id?: str, knowledge_id?: str,
        derived_from?: str, absorption_summary?: str,
        grounding?: dict, idempotent?: bool}``.
    """
    if not isinstance(agent, str) or not agent.strip():
        return json.dumps(
            {"absorbed": False, "reason": "empty_agent"},
            ensure_ascii=False,
        )
    if not isinstance(shared_id, str) or not shared_id.strip():
        return json.dumps(
            {"absorbed": False, "reason": "empty_shared_id"},
            ensure_ascii=False,
        )

    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        result = loop.absorb_experience(
            agent=agent,
            shared_id=shared_id,
            agent_name=agent_name,
            publisher_public_key=publisher_public_key,
            publisher_private_key=publisher_private_key,
        )
        logger.info(
            f"coevolution_absorb: absorbed={result.get('absorbed')} "
            f"new_id={result.get('new_experience_id', 'N/A')} "
            f"reason={result.get('reason', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"coevolution_absorb: value error {exc}")
        return json.dumps(
            {"absorbed": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"coevolution_absorb: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"absorbed": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_feedback(
    new_experience_id: str,
    derived_from: str,
) -> str:
    """桥接函数：经验回传到原始分享者.

    spec SubTask 4.3：在共同进化图中标记 ``derived_from`` 关系并
    发布 ``coevolution_feedback`` 事件通知原分享者.

    Args:
        new_experience_id: 派生经验节点 ID.
        derived_from: 父经验节点 ID.

    Returns:
        JSON 字符串，结构为 ``{fed_back: bool, reason?: str,
        target_agent?: str, new_experience_id?: str,
        derived_from?: str, source_agent?: str}``.
    """
    if not isinstance(new_experience_id, str) or not new_experience_id.strip():
        return json.dumps(
            {"fed_back": False, "reason": "empty_new_experience_id"},
            ensure_ascii=False,
        )
    if not isinstance(derived_from, str) or not derived_from.strip():
        return json.dumps(
            {"fed_back": False, "reason": "empty_derived_from"},
            ensure_ascii=False,
        )

    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        result = loop.feedback_experience(
            new_experience_id=new_experience_id,
            derived_from=derived_from,
        )
        logger.info(
            f"coevolution_feedback: fed_back={result.get('fed_back')} "
            f"target={result.get('target_agent', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"coevolution_feedback: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"fed_back": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_graph(limit: int = 200) -> str:
    """桥接函数：导出共同进化图（节点 + 边）."""
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = 200
    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        result = loop.get_graph(limit=safe_limit)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"coevolution_graph: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_stats() -> str:
    """桥接函数：共同进化图统计."""
    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        stats = loop.stats()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"coevolution_stats: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_get(experience_id: str) -> str:
    """桥接函数：按 experience_id 查询单条经验节点."""
    if not isinstance(experience_id, str) or not experience_id.strip():
        return json.dumps(
            {"found": False, "reason": "empty_experience_id"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        node = loop.get_experience(experience_id)
        if node is None:
            return json.dumps(
                {"found": False, "experience_id": experience_id},
                ensure_ascii=False,
            )
        return json.dumps(
            {"found": True, "experience": node},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"coevolution_get: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"found": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_coevolution_list(
    agent: Optional[str] = None,
    derived_only: bool = False,
    limit: int = 100,
) -> str:
    """桥接函数：列出经验节点（可按 agent / 派生节点过滤）."""
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = 100
    try:
        from laap.protocol.laap_coevolution import get_coevolution_loop
        loop = get_coevolution_loop()
        nodes = loop.list_experiences(
            agent=agent,
            derived_only=bool(derived_only),
            limit=safe_limit,
        )
        return json.dumps(
            {"count": len(nodes), "experiences": nodes},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"coevolution_list: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"count": 0, "experiences": [],
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_coevolution_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 coevolution MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.coevolution_mcp_endpoints import (
            register_coevolution_tools,
        )
        register_coevolution_tools(mcp)

    注册的工具：

    - ``coevolution_share(agent, content, source_memories, confidence,
       agent_name?)`` 分享经验
    - ``coevolution_absorb(agent, shared_id, agent_name?)`` 吸收经验
    - ``coevolution_feedback(new_experience_id, derived_from)`` 经验回传
    - ``coevolution_graph(limit?)`` 导出共同进化图
    - ``coevolution_stats()`` 图统计

    私钥永不离开 sidecar（spec L435）：``coevolution_share`` /
    ``coevolution_absorb`` MCP 工具不暴露 ``publisher_private_key``
    参数，签名仅在 sidecar HTTP 端点 ``/coevolution/share`` /
    ``/coevolution/absorb`` 可用.

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_coevolution_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def coevolution_share(
        agent: str,
        content: str,
        source_memories: list,
        confidence: float,
        agent_name: str = "coevo",
    ) -> str:
        """分享一条个人经验到共同进化图 (P4-coevolution SubTask 4.1).

        端到端：去标识化 → 证据链 → grounding 复核 → Memex 存储 →
        共同进化图根节点.

        Args:
            agent: 分享者 agent 标识.
            content: 原始经验内容字符串（会自动去标识化）.
            source_memories: 来源记忆列表，每项至少含 ``memory_id`` 字段.
            confidence: 整体置信度 [0.0, 1.0]. 低于 0.6 会被拒绝.
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

        Returns:
            JSON 字符串，成功时 ``{shared: true, shared_id: ...,
            knowledge_id: ...}``，失败时 ``{shared: false, reason: ...}``.
        """
        return handle_coevolution_share(
            agent=agent,
            content=content,
            source_memories=source_memories,
            confidence=confidence,
            agent_name=agent_name,
        )

    @mcp_server.tool()
    async def coevolution_absorb(
        agent: str,
        shared_id: str,
        agent_name: str = "coevo",
    ) -> str:
        """吸收一条共享经验并派生新经验 (P4-coevolution SubTask 4.2).

        端到端：取父经验 → LLM 提炼吸收摘要（必经 truth-grounding
        管线）→ 派生经验发布回 Memex → 共同进化图子节点.

        Args:
            agent: 吸收方 agent 标识.
            shared_id: 父经验节点 ID.
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

        Returns:
            JSON 字符串，成功时 ``{absorbed: true, new_experience_id: ...,
            knowledge_id: ..., derived_from: ..., absorption_summary: ...,
            grounding: {...}}``，失败时 ``{absorbed: false, reason: ...}``.
        """
        return handle_coevolution_absorb(
            agent=agent,
            shared_id=shared_id,
            agent_name=agent_name,
        )

    @mcp_server.tool()
    async def coevolution_feedback(
        new_experience_id: str,
        derived_from: str,
    ) -> str:
        """经验回传到原始分享者 (P4-coevolution SubTask 4.3).

        在共同进化图中标记 ``derived_from`` 关系并发布
        ``coevolution_feedback`` 事件通知原分享者.

        Args:
            new_experience_id: 派生经验节点 ID.
            derived_from: 父经验节点 ID.

        Returns:
            JSON 字符串，含 ``{fed_back: bool, target_agent?: str,
            source_agent?: str, ...}``.
        """
        return handle_coevolution_feedback(
            new_experience_id=new_experience_id,
            derived_from=derived_from,
        )

    @mcp_server.tool()
    async def coevolution_graph(limit: int = 200) -> str:
        """导出共同进化图 (P4-coevolution SubTask 4.4).

        Args:
            limit: 最多返回的节点数（按创建时间倒序）.

        Returns:
            JSON 字符串，含 ``{nodes: [...], edges: [...],
            total_nodes, total_edges}``.
        """
        return handle_coevolution_graph(limit=limit)

    @mcp_server.tool()
    async def coevolution_stats() -> str:
        """共同进化图统计 (P4-coevolution).

        Returns:
            JSON 字符串，含 ``{total_experiences, shared_roots,
            derived, total_edges, by_agent, roots_count,
            leaves_count, max_depth}``.
        """
        return handle_coevolution_stats()

    logger.info(
        "register_coevolution_tools: registered coevolution_share / "
        "coevolution_absorb / coevolution_feedback / coevolution_graph / "
        "coevolution_stats "
        "(publisher_private_key 仅 sidecar 端点，私钥不离开 sidecar)"
    )
    return None
