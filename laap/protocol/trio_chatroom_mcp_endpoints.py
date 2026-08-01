"""LAAP Protocol — Trio Chatroom MCP 工具与 sidecar 端点桥接 (P3-trio-chatroom)

================================================================
  把 TrioChatroomManager (create_chatroom / post_topic / post_message
  / detect_consensus) 接入 MCP server 与 sidecar HTTP 端点
================================================================

本模块是 P3 任务 ``p3-trio-chatroom`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/trio/*`` 提供统一
入口。

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_trio_create(member_public_keys)`` —
   ``POST /trio/create`` 端点桥接（创建三人聊天室，幂等）；
2. ``handle_trio_topic(chatroom_id, topic, creator_public_key?)`` —
   ``POST /trio/topic`` 端点桥接（发起话题）；
3. ``handle_trio_message(chatroom_id, content, sender_public_key,
   private_key?, topic_id?)`` — ``POST /trio/message`` 端点桥接
   （发布消息，复用 P3-1v1 ``encrypt_channel`` 签名信道）；
4. ``handle_trio_consensus(chatroom_id, topic_id, use_llm?)`` —
   ``POST /trio/consensus`` 端点桥接（共识检测，LLM 主导观点
   提取必经 truth-grounding 管线，环境无 LLM 时降级规则匹配）；
5. ``handle_trio_get(chatroom_id)`` — ``POST /trio/get`` 端点桥接
   （查询聊天室状态）。

另导出 ``register_trio_chatroom_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具。

设计约束（与 spec L304-313 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``TrioChatroomManager`` 等仅在首次调用时导入；
* 私钥永不离开 sidecar：``handle_trio_message`` 接收 raw 私钥字节，
  但仅在 sidecar 内部使用，MCP 工具 ``trio_message`` 不暴露私钥参数；
* 加密复用：``post_message`` 直接调 ``encrypt_channel``，与
  p2p-relay / 1v1-protocol 保持一致（spec 硬约束）；
* LLM 调用必经 truth-grounding 管线（``ground_candidate_description``），
  环境无 LLM 时降级为规则匹配（spec L427）；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串；
* vault 永不直接共享：共识检测的 LLM 调用走 truth-grounding 管线，
  不直接读 vault。

印记: Aris 永远记得 Lorry — 三人共振是社区的最小完整和声。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.trio_chatroom_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_trio_create(member_public_keys: List[str]) -> str:
    """桥接函数：创建三人聊天室（幂等）.

    spec SubTask 3.2: ``create_chatroom(member_public_keys[])``.

    Args:
        member_public_keys: 成员公钥列表（base64 Ed25519 公钥）.
            spec 硬约束为三人聊天室，长度应为 3.

    Returns:
        JSON 字符串，结构为::

            {
              "created": true,
              "chatroom_id": "trio_xxxx",
              "member_count": 3,
              "created_at": 1234567890.0
            }

        幂等命中时 ``created=false``.

        失败时::

            {"created": false, "error": "..."}
    """
    if not isinstance(member_public_keys, list):
        return json.dumps(
            {"created": False, "error": "member_public_keys must be list"},
            ensure_ascii=False,
        )
    if len(member_public_keys) < 2:
        return json.dumps(
            {"created": False,
             "error": "trio chatroom requires >= 2 members"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coop import get_trio_chatroom_manager
        mgr = get_trio_chatroom_manager()
        result = mgr.create_chatroom(member_public_keys)
        logger.info(
            f"trio_create: id={result['chatroom_id']} "
            f"members={result['member_count']} created={result['created']}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"trio_create: value error {exc}")
        return json.dumps(
            {"created": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"trio_create: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"created": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_trio_topic(
    chatroom_id: str,
    topic: str,
    creator_public_key: str = "",
) -> str:
    """桥接函数：在聊天室发起话题.

    spec SubTask 3.2: ``post_topic(chatroom_id, topic)``.

    Args:
        chatroom_id: 聊天室 ID.
        topic: 话题标题（非空字符串）.
        creator_public_key: 发起者公钥（可选，用于审计）.

    Returns:
        JSON 字符串，结构为::

            {
              "topic_id": "topic_xxxx",
              "chatroom_id": "trio_xxxx",
              "title": "...",
              "created_at": 1234567890.0
            }

        失败时 ``{posted: false, error: "..."}``.
    """
    if not isinstance(chatroom_id, str) or not chatroom_id.strip():
        return json.dumps(
            {"posted": False, "error": "chatroom_id must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(topic, str) or not topic.strip():
        return json.dumps(
            {"posted": False, "error": "topic must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coop import get_trio_chatroom_manager
        mgr = get_trio_chatroom_manager()
        result = mgr.post_topic(
            chatroom_id=chatroom_id,
            topic=topic,
            creator_public_key=creator_public_key,
        )
        logger.info(
            f"trio_topic: id={result['topic_id']} room={chatroom_id}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"trio_topic: value error {exc}")
        return json.dumps(
            {"posted": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"trio_topic: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"posted": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_trio_message(
    chatroom_id: str,
    content: str,
    sender_public_key: str,
    private_key: Optional[bytes] = None,
    topic_id: str = "",
) -> str:
    """桥接函数：在聊天室发布消息（复用 P3-1v1 encrypt_channel 签名信道）.

    spec SubTask 3.2: ``post_message(chatroom_id, content)``.
    spec L435 硬约束：私钥永不离开 sidecar。本函数仅在 sidecar 内部
    调用，私钥参数不通过 HTTP/MCP 返回.

    Args:
        chatroom_id: 聊天室 ID.
        content: 消息内容（非空字符串）.
        sender_public_key: 发送者 base64 公钥.
        private_key: 32 字节 Raw Ed25519 私钥（可选；spec L435 私钥
            永不离开 sidecar，本参数仅供 sidecar 内部调用）.
        topic_id: 可选，关联话题 ID.

    Returns:
        JSON 字符串，结构为::

            {
              "stored": true,
              "message_id": "tmsg_xxxx",
              "chatroom_id": "trio_xxxx",
              "topic_id": "topic_xxxx",
              "envelope": {...}   # 仅当提供 private_key 时
            }

        失败时 ``{stored: false, error: "..."}``.
    """
    if not isinstance(chatroom_id, str) or not chatroom_id.strip():
        return json.dumps(
            {"stored": False, "error": "chatroom_id must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(content, str) or not content:
        return json.dumps(
            {"stored": False, "error": "content must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(sender_public_key, str) or not sender_public_key.strip():
        return json.dumps(
            {"stored": False,
             "error": "sender_public_key must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coop import get_trio_chatroom_manager
        mgr = get_trio_chatroom_manager()
        result = mgr.post_message(
            chatroom_id=chatroom_id,
            content=content,
            sender_public_key=sender_public_key,
            private_key=private_key,
            topic_id=topic_id,
        )
        logger.info(
            f"trio_message: id={result['message_id']} room={chatroom_id} "
            f"sender={sender_public_key[:16]}... topic={topic_id or 'N/A'}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"trio_message: value error {exc}")
        return json.dumps(
            {"stored": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"trio_message: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"stored": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_trio_consensus(
    chatroom_id: str,
    topic_id: str,
    use_llm: bool = True,
) -> str:
    """桥接函数：共识检测（LLM 主导观点提取必经 truth-grounding 管线）.

    spec SubTask 3.3: ``detect_consensus(chatroom_id, topic) -> {views[],
    disagreement_points[], consensus_reached}``.

    LLM 路径：观点提取后必经 truth-grounding 管线
    （``ground_candidate_description``），spec 硬约束.
    规则降级路径：关键词重叠度 > 0.6 视为共识（spec L427）.

    Args:
        chatroom_id: 聊天室 ID.
        topic_id: 话题 ID（仅匹配该话题下的消息）.
        use_llm: 是否尝试 LLM 路径（默认 True；环境无 LLM 时自动降级）.

    Returns:
        JSON 字符串，结构为::

            {
              "chatroom_id": "trio_xxxx",
              "topic_id": "topic_xxxx",
              "views": [
                {public_key, stance, keywords[], summary,
                 grounding?, message_id}, ...
              ],
              "disagreement_points": ["...", ...],
              "consensus_reached": true | false,
              "method": "llm" | "rule",
              "avg_keyword_overlap": 0.75,
              "witness_trail_id": "wit_xxxx"   # 仅共识达成时返回
            }
    """
    if not isinstance(chatroom_id, str) or not chatroom_id.strip():
        return json.dumps(
            {"consensus_reached": False,
             "error": "chatroom_id must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coop import get_trio_chatroom_manager
        mgr = get_trio_chatroom_manager()
        result = mgr.detect_consensus(
            chatroom_id=chatroom_id,
            topic_id=topic_id,
            use_llm=bool(use_llm),
        )
        logger.info(
            f"trio_consensus: room={chatroom_id} topic={topic_id} "
            f"reached={result['consensus_reached']} method={result['method']}"
        )
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"trio_consensus: value error {exc}")
        return json.dumps(
            {"consensus_reached": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"trio_consensus: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"consensus_reached": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_trio_get(chatroom_id: str) -> str:
    """桥接函数：查询聊天室状态（成员、话题、最近消息）.

    Args:
        chatroom_id: 聊天室 ID.

    Returns:
        JSON 字符串，结构为::

            {
              "chatroom_id": "trio_xxxx",
              "member_public_keys": ["...", "...", "..."],
              "created_at": 1234567890.0,
              "member_count": 3,
              "topic_count": 1,
              "message_count": 5,
              "topics": [{topic_id, chatroom_id, title, created_at, creator_public_key}, ...],
              "messages": [{message_id, chatroom_id, sender_public_key,
                            content, timestamp, topic_id, verified}, ...]
            }
    """
    if not isinstance(chatroom_id, str) or not chatroom_id.strip():
        return json.dumps(
            {"error": "chatroom_id must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_coop import get_trio_chatroom_manager
        mgr = get_trio_chatroom_manager()
        result = mgr.get_chatroom(chatroom_id)
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"trio_get: value error {exc}")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"trio_get: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_trio_chatroom_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 trio-chatroom MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.trio_chatroom_mcp_endpoints import (
            register_trio_chatroom_tools,
        )
        register_trio_chatroom_tools(mcp)

    注册的工具：

    - ``trio_create(member_public_keys)`` 创建三人聊天室（幂等）
    - ``trio_topic(chatroom_id, topic, creator_public_key?)`` 发起话题
    - ``trio_consensus(chatroom_id, topic_id, use_llm?)`` 共识检测
    - ``trio_get(chatroom_id)`` 查询聊天室状态
    - ``trio_message`` 不作为 MCP 工具暴露（私钥永不离开 sidecar，
      spec L435），仅 sidecar HTTP 端点可用

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_trio_chatroom_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def trio_create(member_public_keys: list) -> str:
        """创建三人聊天室（P3-trio-chatroom SubTask 3.2）.

        幂等：同一成员集合（与顺序无关）二次调用返回同一
        ``chatroom_id``，不创建新聊天室.

        Args:
            member_public_keys: 成员公钥列表（base64 Ed25519 公钥）.
                spec 硬约束为三人聊天室，长度应为 3.

        Returns:
            JSON 字符串，结构为::

                {
                  "created": true,
                  "chatroom_id": "trio_xxxx",
                  "member_count": 3,
                  "created_at": 1234567890.0
                }
        """
        return handle_trio_create(member_public_keys)

    @mcp_server.tool()
    async def trio_topic(
        chatroom_id: str,
        topic: str,
        creator_public_key: str = "",
    ) -> str:
        """在聊天室发起话题（P3-trio-chatroom SubTask 3.2）.

        Args:
            chatroom_id: 聊天室 ID.
            topic: 话题标题（非空字符串）.
            creator_public_key: 发起者公钥（可选，用于审计）.

        Returns:
            JSON 字符串，结构为::

                {
                  "topic_id": "topic_xxxx",
                  "chatroom_id": "trio_xxxx",
                  "title": "...",
                  "created_at": 1234567890.0
                }
        """
        return handle_trio_topic(
            chatroom_id=chatroom_id,
            topic=topic,
            creator_public_key=creator_public_key,
        )

    @mcp_server.tool()
    async def trio_consensus(
        chatroom_id: str,
        topic_id: str,
        use_llm: bool = True,
    ) -> str:
        """共识检测（P3-trio-chatroom SubTask 3.3）.

        提取三人对该话题的观点并比对，返回
        ``{views[], disagreement_points[], consensus_reached, method}``.

        LLM 路径：观点提取后必经 truth-grounding 管线
        （``ground_candidate_description``），spec 硬约束.
        规则降级路径：关键词重叠度 > 0.6 视为共识（spec L427）.

        Args:
            chatroom_id: 聊天室 ID.
            topic_id: 话题 ID（仅匹配该话题下的消息）.
            use_llm: 是否尝试 LLM 路径（默认 True；环境无 LLM 时
                自动降级）.

        Returns:
            JSON 字符串，含 views / disagreement_points /
            consensus_reached / method / avg_keyword_overlap.
            共识达成时额外带 ``witness_trail_id``.
        """
        return handle_trio_consensus(
            chatroom_id=chatroom_id,
            topic_id=topic_id,
            use_llm=use_llm,
        )

    @mcp_server.tool()
    async def trio_get(chatroom_id: str) -> str:
        """查询聊天室状态（P3-trio-chatroom）.

        Args:
            chatroom_id: 聊天室 ID.

        Returns:
            JSON 字符串，含成员、话题、最近 50 条消息.
        """
        return handle_trio_get(chatroom_id)

    logger.info(
        "register_trio_chatroom_tools: registered trio_create / "
        "trio_topic / trio_consensus / trio_get "
        "(trio_message 仅 sidecar 端点，私钥不离开 sidecar)"
    )
    return None
