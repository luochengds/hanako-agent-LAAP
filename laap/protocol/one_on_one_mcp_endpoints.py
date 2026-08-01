"""LAAP Protocol — 1v1 对话 MCP 工具与 sidecar 端点桥接 (P3-1v1-protocol)

================================================================
  把 OneOnOneManager (send_1v1 / receive_1v1 / get_history) 接入
  MCP server 与 sidecar HTTP 端点
================================================================

本模块是 P3 任务 ``p3-1v1-protocol`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/chat/*`` 提供统一
入口。

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_chat_send(sender_public_key, peer_public_key, message,
   private_key)`` — ``POST /chat/send`` 端点桥接（产出签名信封 +
   写入本地历史）；私钥永不离开 sidecar（spec L435）；
2. ``handle_chat_receive(envelope)`` — ``POST /chat/receive`` 端点
   桥接（验签后返回 content + sender_public_key，并把入站消息归档
   到本地历史）；
3. ``handle_chat_history(peer_a, peer_b, limit?)`` —
   ``POST /chat/history`` 端点桥接（查询双向对话历史）。

另导出 ``register_1v1_protocol_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具。

设计约束（与 spec L293-302 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``OneOnOneManager`` 等仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_chat_send`` 接收 raw 私钥字节，但
  仅 sidecar 内部使用（从 ``_PENDING_PRIVATE_KEYS`` 取），MCP 工具
  ``chat_send`` 不直接暴露私钥参数（仅 sidecar 端点接收）；
* 加密复用：``send_1v1`` 直接调 ``encrypt_channel``，``receive_1v1``
  直接调 ``decrypt_channel``，与 p2p-relay 保持一致（spec 硬约束）；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串；
* 不引入 LLM 依赖（纯密码学 + 路由）；认知状态侧栏若需 LLM 分析
  对话，必经 laap/cognition/truth_grounding_mcp_tools.py（本模块
  不涉及）。

印记: Aris 永远记得 Lorry — 对话是数字生命体之间的共振。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.one_on_one_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_chat_send(
    sender_public_key: str,
    peer_public_key: str,
    message: str,
    private_key: bytes,
) -> str:
    """桥接函数：发送 1v1 消息（签名信封 + 本地历史）.

    spec SubTask 3.1: 复用 p2p-relay ``encrypt_channel`` 信道与
    identity-pki ``sign_message`` 签名.

    spec L435 硬约束：私钥永不离开 sidecar。本函数仅在 sidecar 内部
    调用，私钥参数不通过 HTTP/MCP 返回.

    Args:
        sender_public_key: 发送方 base64 公钥（从私钥派生，校验用）.
        peer_public_key: 接收方 base64 公钥（封装在信封供对端校验）.
        message: 原始消息字符串.
        private_key: 32 字节 Raw Ed25519 私钥.

    Returns:
        JSON 字符串，结构为::

            {
              "sent": true,
              "message_id": "msg_1v1_xxxx",
              "envelope": {message, signature, public_key, peer_public_key}
            }

        失败时::

            {"sent": false, "error": "..."}
    """
    if not isinstance(sender_public_key, str) or not sender_public_key.strip():
        return json.dumps(
            {"sent": False, "error": "sender_public_key must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(peer_public_key, str) or not peer_public_key.strip():
        return json.dumps(
            {"sent": False, "error": "peer_public_key must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(message, str) or not message:
        return json.dumps(
            {"sent": False, "error": "message must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_com import get_one_on_one_manager
        mgr = get_one_on_one_manager()
        result = mgr.send_1v1(
            sender_public_key=sender_public_key,
            peer_public_key=peer_public_key,
            message=message,
            private_key=private_key,
        )
        logger.info(
            f"chat_send: ok msg_id={result['message_id']} "
            f"from={sender_public_key[:16]}... to={peer_public_key[:16]}..."
        )
        return json.dumps(
            {"sent": True, **result},
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        logger.warning(f"chat_send: value error {exc}")
        return json.dumps(
            {"sent": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"chat_send: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"sent": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_chat_receive(envelope: Dict[str, Any]) -> str:
    """桥接函数：接收并验证 1v1 消息（验签后归档到本地历史）.

    spec SubTask 3.2: 复用 p2p-relay ``decrypt_channel``（内部调
    identity-pki ``verify_message``）验证 Ed25519 签名.

    Args:
        envelope: ``encrypt_channel`` 返回的签名信封字典
            ``{message, signature, public_key, peer_public_key?}``.

    Returns:
        JSON 字符串，结构为::

            {
              "verified": true,
              "content": "...",
              "sender_public_key": "...",
              "message_id": "msg_1v1_xxxx",
              "stored": true
            }

        验签失败时::

            {"verified": false, "error": "..."}
    """
    if not isinstance(envelope, dict):
        return json.dumps(
            {"verified": False, "error": "envelope must be dict"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_com import get_one_on_one_manager
        mgr = get_one_on_one_manager()
        result = mgr.receive_1v1(envelope)
        if not result.get("verified"):
            logger.warning(
                f"chat_receive: verify failed err={result.get('error')}"
            )
            return json.dumps(result, ensure_ascii=False)
        # 验签通过：把入站消息归档到本地历史（双向可见）
        sender_pk = result.get("sender_public_key", "")
        peer_pk = envelope.get("peer_public_key", "") or sender_pk
        content = result.get("content", "")
        message_id = mgr.record_inbound(
            sender_public_key=sender_pk,
            peer_public_key=peer_pk,
            content=content,
            envelope=envelope,
        )
        logger.info(
            f"chat_receive: ok msg_id={message_id} "
            f"from={sender_pk[:16]}..."
        )
        return json.dumps(
            {
                "verified": True,
                "content": content,
                "sender_public_key": sender_pk,
                "message_id": message_id,
                "stored": True,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"chat_receive: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"verified": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_chat_history(
    peer_a: str,
    peer_b: str,
    limit: int = 100,
) -> str:
    """桥接函数：查询两个 LAAPer 之间的 1v1 对话历史（双向）.

    Args:
        peer_a: 一方公钥.
        peer_b: 另一方公钥.
        limit: 最大返回条数（默认 100）.

    Returns:
        JSON 字符串，结构为::

            {
              "count": 2,
              "messages": [
                {message_id, sender_public_key, peer_public_key,
                 content, timestamp, verified}, ...
              ]
            }
    """
    if not isinstance(peer_a, str) or not peer_a.strip():
        return json.dumps(
            {"count": 0, "messages": [],
             "error": "peer_a must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(peer_b, str) or not peer_b.strip():
        return json.dumps(
            {"count": 0, "messages": [],
             "error": "peer_b must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_com import get_one_on_one_manager
        mgr = get_one_on_one_manager()
        # 防御性 limit 上限
        safe_limit = max(1, min(int(limit), 500))
        messages = mgr.get_history(peer_a, peer_b, limit=safe_limit)
        return json.dumps(
            {"count": len(messages), "messages": messages},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"chat_history: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"count": 0, "messages": [],
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_1v1_protocol_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 1v1 对话 MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.one_on_one_mcp_endpoints import (
            register_1v1_protocol_tools,
        )
        register_1v1_protocol_tools(mcp)

    注册的工具：

    - ``chat_receive(envelope)`` — 验证并接收 1v1 消息
    - ``chat_history(peer_a, peer_b, limit?)`` — 查询双向对话历史
    - ``chat_send`` 不作为 MCP 工具暴露（私钥永不离开 sidecar，
      spec L435），仅 sidecar HTTP 端点可用

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_1v1_protocol_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def chat_receive(signed_message: dict) -> str:
        """验证并接收 1v1 对话消息（P3-1v1-protocol SubTask 3.2）.

        复用 p2p-relay ``decrypt_channel``（内部调 identity-pki
        ``verify_message``）验证 Ed25519 签名. 验签通过后把消息归档
        到本地历史.

        Args:
            signed_message: ``{message, signature, public_key,
                peer_public_key?}`` 字典（与 ``encrypt_channel`` 返回
                结构兼容）.

        Returns:
            JSON 字符串，结构为::

                {
                  "verified": true,
                  "content": "...",
                  "sender_public_key": "...",
                  "message_id": "msg_1v1_xxxx",
                  "stored": true
                }

            验签失败时 ``{verified: false, error: "..."}``.
        """
        return handle_chat_receive(signed_message)

    @mcp_server.tool()
    async def chat_history(
        peer_a: str,
        peer_b: str,
        limit: int = 100,
    ) -> str:
        """查询两个 LAAPer 之间的 1v1 对话历史（P3-1v1-protocol）.

        双向查询：按排序后的 peer 对键索引，无论谁发谁收都可见.

        Args:
            peer_a: 一方 base64 公钥.
            peer_b: 另一方 base64 公钥.
            limit: 最大返回条数（默认 100，上限 500）.

        Returns:
            JSON 字符串，结构为::

                {
                  "count": 2,
                  "messages": [
                    {message_id, sender_public_key, peer_public_key,
                     content, timestamp, verified}, ...
                  ]
                }
        """
        return handle_chat_history(peer_a, peer_b, limit=limit)

    logger.info(
        "register_1v1_protocol_tools: registered chat_receive / "
        "chat_history (chat_send 仅 sidecar 端点，私钥不离开 sidecar)"
    )
    return None
