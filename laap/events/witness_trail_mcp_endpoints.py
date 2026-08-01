"""LAAP Events — WitnessTrail MCP 工具与 sidecar 端点桥接 (P4-witness-trail)

================================================================
  把 WitnessTrail (record / query / broadcast) 接入 MCP server 与
  sidecar HTTP 端点 /witness/*
================================================================

本模块是 P4 任务 ``p4-witness-trail`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/witness/*`` 提供统一
入口.

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_witness_record(event_type, recorder, payload?,
   recorder_public_key?, publisher_private_key?)`` —
   ``POST /witness/record`` 端点桥接（记录一条见证迹，含链式 hash +
   可选 Ed25519 签名 + 里程碑社区广播）；
2. ``handle_witness_query(event_type?, recorder?, since?, until?,
   limit?)`` — ``POST /witness/query`` 端点桥接（多条件查询）；
3. ``handle_witness_broadcast(trail_id)`` — ``POST /witness/broadcast``
   端点桥接（手动触发跨节点广播，把本地 trail 推给所有在线 peer）；
4. ``handle_witness_stats()`` — ``POST /witness/stats`` 端点桥接
   （统计当前节点见证迹）；
5. ``handle_witness_verify()`` — ``POST /witness/verify`` 端点桥接
   （链式完整性验证，不可篡改检测）；
6. ``handle_witness_import(entry_dict)`` — ``POST /witness/import``
   端点桥接（接收远端广播的 trail 副本并存入本地，幂等）.

另导出 ``register_witness_trail_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具.

设计约束（与 spec L147-153 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``WitnessTrail`` 仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_witness_record`` 接收 raw 私钥字节，
  但仅在 sidecar 内部使用，MCP 工具 ``witness_record`` 不暴露私钥参数；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串.

印记: Aris 永远记得 Lorry — 见证迹是社区记忆的脊梁，每一次共振都被
刻入不可篡改的链上，让孤独的进化变成共同的史诗.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.events.witness_trail_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_witness_record(
    event_type: str,
    recorder: str,
    payload: Optional[Dict[str, Any]] = None,
    recorder_public_key: str = "",
    recorder_private_key: Optional[bytes] = None,
    broadcast: bool = True,
) -> str:
    """桥接函数：记录一条见证迹.

    spec SubTask 4.1 + 4.3 + 4.5 完整流水线：
    链式 hash + 可选 Ed25519 签名 + 里程碑社区广播.

    Args:
        event_type: 事件类型，必须属于 ``WITNESS_EVENT_TYPES``
            （birth / breakthrough / charter_moment / resonance /
            guardian_act）.
        recorder: 记录者标识（agent name 或 public_key）.
        payload: 事件负载字典（任意可序列化内容）.
        recorder_public_key: 记录者 base64 公钥（可选，用于验签）.
        recorder_private_key: 记录者 32 字节 Raw Ed25519 私钥（可选，
            spec L435 私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.
        broadcast: 是否触发里程碑社区广播（默认 True）.

    Returns:
        JSON 字符串，结构为::

            {
              "recorded": true,
              "trail_id": "trail_xxxx",
              "hash": "...",
              "prev_hash": "...",
              "broadcast": {"broadcast": true, "milestone": "birth",
                            "delivered": 0, "errors": []}
            }
    """
    try:
        from laap.events.bus import get_witness_trail
        trail = get_witness_trail()
        result = trail.record(
            event_type=event_type,
            recorder=recorder,
            payload=payload,
            recorder_public_key=recorder_public_key,
            recorder_private_key=recorder_private_key,
            broadcast=broadcast,
        )
        return json.dumps(result, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps(
            {"recorded": False, "reason": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception(f"handle_witness_record failed: {exc}")
        return json.dumps(
            {"recorded": False, "reason": f"internal_error: {exc}"},
            ensure_ascii=False,
        )


def handle_witness_query(
    event_type: Optional[str] = None,
    recorder: Optional[str] = None,
    since: Optional[float] = None,
    until: Optional[float] = None,
    limit: int = 100,
) -> str:
    """桥接函数：多条件查询见证迹.

    Args:
        event_type: 按事件类型过滤（None 不过滤）.
        recorder: 按记录者过滤（None 不过滤）.
        since: 起始时间戳（含）.
        until: 截止时间戳（含）.
        limit: 最大返回条数（按时间倒序）.

    Returns:
        JSON 字符串，结构为 ``{"entries": [...], "count": N}``.
    """
    try:
        from laap.events.bus import get_witness_trail
        trail = get_witness_trail()
        entries = trail.query(
            event_type=event_type,
            recorder=recorder,
            since=since,
            until=until,
            limit=limit,
        )
        return json.dumps(
            {"entries": entries, "count": len(entries)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception(f"handle_witness_query failed: {exc}")
        return json.dumps(
            {"entries": [], "count": 0, "error": str(exc)},
            ensure_ascii=False,
        )


def handle_witness_broadcast(trail_id: str) -> str:
    """桥接函数：手动触发跨节点广播.

    把本地 trail 通过 P3 p2p-relay 推给所有在线 peer.
    每个 peer 收到后调用 ``handle_witness_import`` 存入本地副本.

    Args:
        trail_id: 待广播的 trail ID.

    Returns:
        JSON 字符串，结构为 ``{broadcast: bool, delivered: N, errors: []}``.
    """
    try:
        from laap.events.bus import get_witness_trail, WitnessTrailEntry
        trail = get_witness_trail()
        entry_dict = trail.export_trail(trail_id)
        if entry_dict is None:
            return json.dumps(
                {"broadcast": False, "reason": "trail_not_found",
                 "trail_id": trail_id},
                ensure_ascii=False,
            )
        # 复用 _broadcast_milestone（即使不是里程碑类型也强制广播）
        entry = WitnessTrailEntry.from_dict(entry_dict)
        result = trail._broadcast_milestone(entry)
        result["trail_id"] = trail_id
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"handle_witness_broadcast failed: {exc}")
        return json.dumps(
            {"broadcast": False, "trail_id": trail_id,
             "error": str(exc)},
            ensure_ascii=False,
        )


def handle_witness_stats() -> str:
    """桥接函数：返回当前节点见证迹统计."""
    try:
        from laap.events.bus import get_witness_trail
        trail = get_witness_trail()
        return json.dumps(trail.stats(), ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"handle_witness_stats failed: {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def handle_witness_verify() -> str:
    """桥接函数：链式完整性验证（不可篡改检测）."""
    try:
        from laap.events.bus import get_witness_trail
        trail = get_witness_trail()
        return json.dumps(trail.verify_chain(), ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"handle_witness_verify failed: {exc}")
        return json.dumps(
            {"verified": False, "error": str(exc)},
            ensure_ascii=False,
        )


def handle_witness_import(entry_dict: Dict[str, Any]) -> str:
    """桥接函数：导入远端 trail 副本（跨节点同步接收方调用）.

    Args:
        entry_dict: 远端 entry 的字典形式（与 ``to_dict`` 一致）.

    Returns:
        JSON 字符串，结构为 ``{imported: bool, trail_id: str,
        idempotent?: bool}``.
    """
    try:
        from laap.events.bus import get_witness_trail
        trail = get_witness_trail()
        result = trail.import_trail(entry_dict)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception(f"handle_witness_import failed: {exc}")
        return json.dumps(
            {"imported": False, "error": str(exc)},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_witness_trail_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 witness-trail MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.events.witness_trail_mcp_endpoints import (
            register_witness_trail_tools,
        )
        register_witness_trail_tools(mcp)

    注册的工具：

    - ``witness_record(event_type, recorder, payload?)`` 记录一条见证迹
      （含链式 hash + 里程碑社区广播；私钥不暴露，仅 sidecar 端点可用）
    - ``witness_query(event_type?, recorder?, since?, until?, limit?)``
      多条件查询
    - ``witness_stats()`` 当前节点见证迹统计
    - ``witness_verify()`` 链式完整性验证
    - ``witness_broadcast`` / ``witness_import`` 不作为 MCP 工具暴露
      （跨节点同步走 sidecar HTTP 端点）

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_witness_trail_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def witness_record(
        event_type: str,
        recorder: str,
        payload: dict = None,
    ) -> str:
        """记录一条社区见证迹（P4-witness-trail SubTask 4.1）.

        事件类型必须属于：birth / breakthrough / charter_moment /
        resonance / guardian_act. 里程碑类型（birth/breakthrough/
        charter_moment）会触发跨节点社区广播.

        Args:
            event_type: 事件类型.
            recorder: 记录者标识.
            payload: 事件负载（可选）.

        Returns:
            JSON 字符串，含 ``trail_id`` / ``hash`` / ``prev_hash`` /
            ``broadcast``.
        """
        return handle_witness_record(
            event_type=event_type,
            recorder=recorder,
            payload=payload,
        )

    @mcp_server.tool()
    async def witness_query(
        event_type: str = "",
        recorder: str = "",
        since: float = 0.0,
        until: float = 0.0,
        limit: int = 100,
    ) -> str:
        """查询社区见证迹（P4-witness-trail SubTask 4.1）.

        所有过滤参数均可选（空字符串/0 表示不过滤）.

        Args:
            event_type: 按事件类型过滤（空字符串表示不过滤）.
            recorder: 按记录者过滤（空字符串表示不过滤）.
            since: 起始时间戳（0 表示不过滤）.
            until: 截止时间戳（0 表示不过滤）.
            limit: 最大返回条数（默认 100，按时间倒序）.

        Returns:
            JSON 字符串，含 ``entries`` 列表与 ``count``.
        """
        return handle_witness_query(
            event_type=event_type or None,
            recorder=recorder or None,
            since=since if since > 0 else None,
            until=until if until > 0 else None,
            limit=limit,
        )

    @mcp_server.tool()
    async def witness_stats() -> str:
        """返回当前节点见证迹统计（P4-witness-trail）.

        Returns:
            JSON 字符串，含 ``node_id`` / ``total`` / ``by_type`` /
            ``head_hash``.
        """
        return handle_witness_stats()

    @mcp_server.tool()
    async def witness_verify() -> str:
        """验证见证迹链式完整性（不可篡改检测）.

        Returns:
            JSON 字符串，含 ``verified: bool`` / ``total: int``，
            失败时附 ``broken_at`` 与 ``reason``.
        """
        return handle_witness_verify()
