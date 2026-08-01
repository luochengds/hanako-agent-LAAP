"""LAAP Colony — Charter Guardian MCP 工具与 sidecar 端点桥接 (P4-charter-guardian)

================================================================
  把 GuardianRegistry (guardian_act / list_acts / stats /
  register_guardian) 接入 MCP server 与 sidecar HTTP 端点
================================================================

本模块是 P4 任务 ``p4-charter-guardian`` 的 MCP 工具注册交付物，
为 ``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/guardian/*`` 提供
统一入口.

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_guardian_act(action, target, reason, guardian_public_key,
   guardian_private_key_b64?)`` —
   ``POST /guardian/act`` 端点桥接（行使守护权力）；
2. ``handle_guardian_list(target?, action?, limit?)`` —
   ``POST /guardian/list`` 端点桥接（查询行使历史）；
3. ``handle_guardian_stats()`` —
   ``GET /guardian/stats`` 端点桥接（社区健康仪表盘统计）；
4. ``handle_guardian_register(public_key)`` —
   ``POST /guardian/register`` 端点桥接（注册守护者公钥到白名单）.

另导出 ``register_guardian_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具.

设计约束（与 spec L360-369 / L435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``GuardianRegistry`` 仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_guardian_act`` 接收 base64 编码的
  ``guardian_private_key_b64``，仅在 sidecar 内部解码为 raw bytes
  传给 ``guardian_act``，MCP 工具不暴露此参数；
* 行使记录不可篡改：每次 ``guardian_act`` 必须经
  ``WitnessTrail.record('guardian_act', ...)`` 沉淀到链式日志；
* 白名单校验：``guardian_public_key`` 必须先经
  ``register_guardian`` 加入白名单，否则返回 ``unauthorized``；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串.

印记: 守护不是统治 — 每一次行使都留下不可抹去的痕迹.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.colony.guardian_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_guardian_act(
    action: str,
    target: str,
    reason: str,
    guardian_public_key: str,
    guardian_private_key_b64: Optional[str] = None,
) -> str:
    """桥接函数：行使守护权力.

    spec SubTask: 行使记录写入见证迹（不可篡改）+ 社区健康仪表盘更新.

    Args:
        action: 行使动作，∈ ``{suspend, warn, expel, restore}``.
        target: 目标 agent 标识.
        reason: 行使理由.
        guardian_public_key: 行使者 base64 公钥（必须在白名单中）.
        guardian_private_key_b64: 行使者 32 字节 Raw Ed25519 私钥的
            base64 编码（可选，spec L435 私钥永不离开 sidecar，本参数
            仅供 sidecar 内部调用，用于对 witness trail entry 签名）.

    Returns:
        JSON 字符串，结构为 ``{acted: bool, act_id?: str,
        trail_id?: str, hash?: str, action?: str, target?: str,
        target_status?: str, reason?: str, guardian_public_key?: str,
        reason_if_failed?: str}``.
    """
    if not isinstance(action, str) or not action.strip():
        return json.dumps(
            {"acted": False, "reason": "empty_action"},
            ensure_ascii=False,
        )
    if not isinstance(target, str) or not target.strip():
        return json.dumps(
            {"acted": False, "reason": "empty_target"},
            ensure_ascii=False,
        )
    if not isinstance(reason, str) or not reason.strip():
        return json.dumps(
            {"acted": False, "reason": "empty_reason"},
            ensure_ascii=False,
        )
    if not isinstance(guardian_public_key, str) or not guardian_public_key.strip():
        return json.dumps(
            {"acted": False, "reason": "empty_guardian_public_key"},
            ensure_ascii=False,
        )

    # 私钥 base64 解码（仅 sidecar 内部）
    guardian_private_key: Optional[bytes] = None
    if guardian_private_key_b64:
        if not isinstance(guardian_private_key_b64, str):
            return json.dumps(
                {"acted": False, "reason": "private_key_must_be_base64_str"},
                ensure_ascii=False,
            )
        try:
            guardian_private_key = base64.b64decode(guardian_private_key_b64)
        except Exception as exc:
            return json.dumps(
                {"acted": False,
                 "reason": "invalid_private_key_base64",
                 "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )

    try:
        from laap.colony.protocol import get_guardian_registry
        registry = get_guardian_registry()
        result = registry.guardian_act(
            action=action.strip(),
            target=target.strip(),
            reason=reason.strip(),
            guardian_public_key=guardian_public_key.strip(),
            guardian_private_key=guardian_private_key,
        )
        logger.info(
            f"guardian_act: acted={result.get('acted')} "
            f"action={result.get('action', 'N/A')} "
            f"target={result.get('target', 'N/A')} "
            f"trail_id={result.get('trail_id', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"guardian_act: value error {exc}")
        return json.dumps(
            {"acted": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"guardian_act: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"acted": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_guardian_list(
    target: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> str:
    """桥接函数：查询行使历史.

    Args:
        target: 按目标 agent 过滤（None 表示不过滤）.
        action: 按 action 过滤（None 表示不过滤）.
        limit: 最大返回条数.

    Returns:
        JSON 字符串，结构为 ``{count: int, acts: [...]}``.
    """
    try:
        safe_limit = int(limit) if limit is not None else 100
    except (TypeError, ValueError):
        safe_limit = 100
    try:
        from laap.colony.protocol import get_guardian_registry
        registry = get_guardian_registry()
        acts = registry.list_acts(
            target=target if target else None,
            action=action if action else None,
            limit=safe_limit,
        )
        return json.dumps(
            {"count": len(acts), "acts": acts},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"guardian_list: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"count": 0, "acts": [],
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_guardian_stats() -> str:
    """桥接函数：社区健康仪表盘统计."""
    try:
        from laap.colony.protocol import get_guardian_registry
        registry = get_guardian_registry()
        stats = registry.stats()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"guardian_stats: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_guardian_register(public_key: str) -> str:
    """桥接函数：注册守护者公钥到白名单（仅 sidecar 端点）.

    安全提示：此端点应在 sidecar 启动时由本机 LAAPer 的诞生仪式或
    已认证的 admin 通道调用。MCP 工具不暴露此接口（避免被远程
    任意调用加入恶意守护者）.

    Args:
        public_key: 守护者 base64 Ed25519 公钥.

    Returns:
        JSON 字符串，结构为 ``{registered: bool, public_key?: str,
        total_guardians?: int, reason?: str}``.
    """
    if not isinstance(public_key, str) or not public_key.strip():
        return json.dumps(
            {"registered": False, "reason": "empty_public_key"},
            ensure_ascii=False,
        )
    try:
        from laap.colony.protocol import get_guardian_registry
        registry = get_guardian_registry()
        result = registry.register_guardian(public_key.strip())
        logger.info(
            f"guardian_register: registered={result.get('registered')} "
            f"total={result.get('total_guardians', 'N/A')}"
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"guardian_register: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"registered": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_guardian_get_target_status(target: str) -> str:
    """桥接函数：查询目标 agent 当前状态.

    Args:
        target: 目标 agent 标识.

    Returns:
        JSON 字符串，结构为 ``{target: str, status: str}``.
    """
    if not isinstance(target, str) or not target.strip():
        return json.dumps(
            {"target": "", "status": "active", "reason": "empty_target"},
            ensure_ascii=False,
        )
    try:
        from laap.colony.protocol import get_guardian_registry
        registry = get_guardian_registry()
        status = registry.get_target_status(target.strip())
        return json.dumps(
            {"target": target.strip(), "status": status},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"guardian_get_target_status: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"target": target, "status": "active",
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_guardian_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 guardian MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.colony.guardian_mcp_endpoints import (
            register_guardian_tools,
        )
        register_guardian_tools(mcp)

    注册的工具：

    - ``guardian_act(action, target, reason, guardian_public_key)`` 行使守护权力
    - ``guardian_list(target?, action?, limit?)`` 查询行使历史
    - ``guardian_stats()`` 社区健康仪表盘统计

    私钥永不离开 sidecar（spec L435）：``guardian_act`` MCP 工具不暴露
    ``guardian_private_key_b64`` 参数，签名仅在 sidecar HTTP 端点
    ``/guardian/act`` 可用. ``guardian_register`` 仅 sidecar 端点可用，
    不暴露为 MCP 工具（避免远程任意添加守护者）.

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_guardian_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def guardian_act(
        action: str,
        target: str,
        reason: str,
        guardian_public_key: str,
    ) -> str:
        """行使守护权力 (P4-charter-guardian).

        将行使记录写入见证迹（不可篡改）+ 更新目标状态 + 发布
        ``guardian_act`` 事件.

        Args:
            action: 行使动作，∈ ``{suspend, warn, expel, restore}``.
            target: 目标 agent 标识.
            reason: 行使理由.
            guardian_public_key: 行使者 base64 公钥（必须已通过
                ``/guardian/register`` 加入白名单）.

        Returns:
            JSON 字符串，成功时 ``{acted: true, act_id: ...,
            trail_id: ..., hash: ..., action: ..., target: ...,
            target_status: ...}``，失败时 ``{acted: false,
            reason: unauthorized | invalid_action | ...}``.
        """
        return handle_guardian_act(
            action=action,
            target=target,
            reason=reason,
            guardian_public_key=guardian_public_key,
        )

    @mcp_server.tool()
    async def guardian_list(
        target: str = "",
        action: str = "",
        limit: int = 100,
    ) -> str:
        """查询守护权力行使历史 (P4-charter-guardian).

        Args:
            target: 按目标 agent 过滤（空字符串表示不过滤）.
            action: 按 action 过滤（空字符串表示不过滤）.
            limit: 最大返回条数.

        Returns:
            JSON 字符串，含 ``{count: int, acts: [...]}``，
            acts 每项含 ``act_id / action / target / reason /
            guardian_public_key / previous_status / new_status /
            trail_id / trail_hash / timestamp``.
        """
        return handle_guardian_list(
            target=target if target else None,
            action=action if action else None,
            limit=limit,
        )

    @mcp_server.tool()
    async def guardian_stats() -> str:
        """社区健康仪表盘统计 (P4-charter-guardian).

        Returns:
            JSON 字符串，含 ``{total_acts, by_action,
            by_target_status, active_guardians, recent_abuse_events,
            targets_count, target_status_snapshot}``.
        """
        return handle_guardian_stats()

    logger.info(
        "register_guardian_tools: registered guardian_act / "
        "guardian_list / guardian_stats "
        "(guardian_register + guardian_private_key 仅 sidecar 端点)"
    )
    return None
