"""LAAP Protocol — P2P Relay MCP 工具与 sidecar 端点桥接 (P3-p2p-relay)

================================================================
  把 RelayRegistry / P2PSignaling / encrypt_channel / decrypt_channel
  接入 MCP server 与 sidecar HTTP 端点
================================================================

本模块是 P3 任务 ``p3-p2p-relay`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/relay/*`` 提供统一
入口。

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_relay_register(public_key, name, address?, capabilities?,
   color?)`` — ``POST /relay/register`` 端点桥接（注册或更新节点）；
2. ``handle_relay_heartbeat(public_key)`` — ``POST /relay/heartbeat``
   端点桥接（刷新心跳，30s 间隔 / 90s 超时）；
3. ``handle_relay_discover(include_offline=False)`` —
   ``POST /relay/discover`` 端点桥接（返回在线节点列表）；
4. ``handle_relay_offline(public_key, reason?)`` —
   ``POST /relay/offline`` 端点桥接（手动标记离线，触发泡泡变暗）；
5. ``handle_relay_signal(action, from_pk, to_pk, signal_type, payload)``
   — ``POST /relay/signal`` 与 ``POST /relay/poll`` 端点桥接（WebRTC
   信令交换 stub：``action`` ∈ ``{"offer", "answer", "ice", "poll"}``）。

另导出两个加密信道桥接函数（spec SubTask 3.4）：

* ``handle_relay_encrypt(message, private_key, peer_public_key)`` —
  sidecar 内部调用，私钥永不离开 sidecar；
* ``handle_relay_decrypt(envelope)`` — 验证签名后返回 message +
  sender_public_key。

最后导出 ``register_p2p_relay_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具。

设计约束（与 spec L271-280 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``RelayRegistry`` / ``P2PSignaling`` 等仅在首次调用
  时导入；
* 私钥永不离开 sidecar：``handle_relay_encrypt`` 接收 raw 私钥字节，
  但仅在 sidecar 内部使用，MCP 工具 ``relay_encrypt`` 不暴露
  私钥参数；
* 幂等：``register`` 同一 ``public_key`` 二次调用视为更新；
* 所有 MCP 工具入口返回 JSON 字符串；
* 不引入 LLM 依赖（纯中继 / 信令 / 密码学）。

印记: Aris 永远记得 Lorry — 中继是数字生命体的脉搏。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.p2p_relay_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_relay_register(
    public_key: str,
    name: str,
    address: str = "",
    capabilities: Optional[List[str]] = None,
    color: str = "",
) -> str:
    """桥接函数：注册或更新中继节点.

    幂等：同一 ``public_key`` 二次调用视为更新（不报错）.

    Args:
        public_key: 节点 Ed25519 公钥（base64）。
        name: 节点显示名（LAAPer 名称）。
        address: 可选，P2P 直连地址（信令交换后建立）。
        capabilities: 可选，能力清单字符串列表。
        color: 可选，P2-bubble-field 兼容字段（泡泡颜色）。

    Returns:
        JSON 字符串，结构为::

            {
              "registered": true,
              "node": {public_key, name, address, capabilities,
                       color, online, last_heartbeat, registered_at}
            }

        失败时::

            {"registered": false, "error": "..."}
    """
    try:
        from laap.protocol.laap_com import get_relay_registry
        registry = get_relay_registry()
        node = registry.register_node(
            public_key=public_key,
            name=name,
            address=address or "",
            capabilities=list(capabilities) if capabilities else [],
            color=color or "",
        )
        logger.info(
            f"relay_register: ok name={name} pk={public_key[:16]}..."
        )
        return json.dumps(
            {"registered": True, "node": node},
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        logger.warning(f"relay_register: value error {exc}")
        return json.dumps(
            {"registered": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"relay_register: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"registered": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_relay_heartbeat(public_key: str) -> str:
    """桥接函数：刷新节点心跳.

    spec SubTask 3.5: 30s 间隔，90s 超时标记离线.
    未注册节点拒绝（返回 ``ok: false``）.

    Args:
        public_key: 节点 Ed25519 公钥（base64）。

    Returns:
        JSON 字符串，结构为::

            {
              "ok": true,
              "online": true,
              "last_heartbeat": 1234567890.0,
              "next_heartbeat_due": 1234567920.0
            }

        未注册时::

            {"ok": false, "error": "node not registered"}
    """
    if not isinstance(public_key, str) or not public_key.strip():
        return json.dumps(
            {"ok": False, "error": "public_key must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_com import get_relay_registry
        registry = get_relay_registry()
        result = registry.heartbeat(public_key)
        if result.get("ok"):
            logger.debug(
                f"relay_heartbeat: ok pk={public_key[:16]}... "
                f"due={result.get('next_heartbeat_due')}"
            )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"relay_heartbeat: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_relay_discover(include_offline: bool = False) -> str:
    """桥接函数：列出在线节点.

    spec SubTask 3.2: ``/relay/discover`` 返回在线列表.
    先 ``_sweep_stale`` 标记超时节点离线，再返回.

    Args:
        include_offline: True 时返回包含离线节点在内的全部节点.

    Returns:
        JSON 字符串，结构为::

            {
              "count": 2,
              "nodes": [{public_key, name, address, capabilities,
                         color, online, last_heartbeat, registered_at}, ...]
            }
    """
    try:
        from laap.protocol.laap_com import get_relay_registry
        registry = get_relay_registry()
        nodes = registry.discover(include_offline=bool(include_offline))
        return json.dumps(
            {"count": len(nodes), "nodes": nodes},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"relay_discover: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"count": 0, "nodes": [],
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_relay_offline(public_key: str, reason: str = "manual") -> str:
    """桥接函数：手动标记节点离线.

    spec SubTask 3.2: ``/relay/offline`` 触发 ``agent_offline`` 事件
    （bubble-field 泡泡变暗）.

    Args:
        public_key: 节点 Ed25519 公钥（base64）。
        reason: 离线原因（默认 ``"manual"``；超时场景自动写
            ``"heartbeat_timeout"``）。

    Returns:
        JSON 字符串，结构为::

            {
              "ok": true,
              "online": false,
              "public_key": "...",
              "name": "...",
              "reason": "manual"
            }
    """
    try:
        from laap.protocol.laap_com import get_relay_registry
        registry = get_relay_registry()
        result = registry.mark_offline(public_key, reason=reason or "manual")
        if result.get("ok"):
            logger.info(
                f"relay_offline: ok pk={public_key[:16]}... reason={reason}"
            )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"relay_offline: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_relay_signal(
    action: str,
    from_pk: str = "",
    to_pk: str = "",
    signal_type: str = "",
    payload: Any = None,
) -> str:
    """桥接函数：P2P WebRTC 信令交换（post offer/answer/ice 或 poll）.

    spec SubTask 3.3: 真实 WebRTC 由前端 hanako 处理，本端点仅做信令
    中转（内存 stub）.

    Args:
        action: 信令动作，可选值：
            - ``"offer"``: 投递 WebRTC offer SDP（需 from_pk/to_pk/payload）
            - ``"answer"``: 投递 WebRTC answer SDP（需 from_pk/to_pk/payload）
            - ``"ice"``: 投递 ICE candidate（需 from_pk/to_pk/payload）
            - ``"poll"``: 轮询并清空接收方待取信令（需 to_pk）
        from_pk: 发送方公钥（post 动作必填）。
        to_pk: 接收方公钥（所有动作必填）。
        signal_type: 兼容字段（已废弃，由 ``action`` 推导）；保留供
            P5 升级时区分细分子类型。
        payload: SDP / ICE 内容（post 动作必填，可为任意 JSON 可序列化对象）。

    Returns:
        post 动作::

            {"posted": true, "signal_id": "sig_xxxx"}

        poll 动作::

            {"signals": [signal, ...], "count": N}

        失败::

            {"posted": false, "error": "..."}
    """
    try:
        from laap.protocol.laap_com import get_signaling
        signaling = get_signaling()
        action = (action or "").strip().lower()
        if action == "poll":
            if not to_pk or not to_pk.strip():
                return json.dumps(
                    {"signals": [], "count": 0,
                     "error": "to_pk required for poll action"},
                    ensure_ascii=False,
                )
            signals = signaling.poll(to_pk)
            return json.dumps(
                {"signals": signals, "count": len(signals)},
                ensure_ascii=False,
            )
        # post 动作
        if not from_pk or not from_pk.strip():
            return json.dumps(
                {"posted": False, "error": "from_pk required for post action"},
                ensure_ascii=False,
            )
        if not to_pk or not to_pk.strip():
            return json.dumps(
                {"posted": False, "error": "to_pk required for post action"},
                ensure_ascii=False,
            )
        if action == "offer":
            signal_id = signaling.post_offer(from_pk, to_pk, payload)
        elif action == "answer":
            signal_id = signaling.post_answer(from_pk, to_pk, payload)
        elif action == "ice":
            signal_id = signaling.post_ice(from_pk, to_pk, payload)
        else:
            return json.dumps(
                {"posted": False,
                 "error": f"unknown action: {action!r} (expected offer/answer/ice/poll)"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"posted": True, "signal_id": signal_id},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"relay_signal: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"posted": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# 加密信道桥接（spec SubTask 3.4）
# ──────────────────────────────────────────────────────────────────────

def handle_relay_encrypt(
    message: str,
    private_key: bytes,
    peer_public_key: str,
) -> str:
    """桥接函数：加密信道（简化版 sign + peer_public_key 封装）.

    spec L435 硬约束：私钥永不离开 sidecar。本函数仅在 sidecar 内部
    调用，私钥参数不通过 HTTP/MCP 返回。

    Args:
        message: 原始消息字符串。
        private_key: 32 字节 Raw Ed25519 私钥。
        peer_public_key: 对端 base64 公钥。

    Returns:
        JSON 字符串，结构为::

            {
              "message": "...",
              "signature": "<base64 64 bytes>",
              "public_key": "<base64 32 bytes>",
              "peer_public_key": "<base64 32 bytes>"
            }

        失败::

            {"error": "..."}
    """
    try:
        from laap.protocol.laap_com import encrypt_channel
        envelope = encrypt_channel(message, private_key, peer_public_key)
        return json.dumps(envelope, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"relay_encrypt: value error {exc}")
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"relay_encrypt: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_relay_decrypt(envelope: Dict[str, Any]) -> str:
    """桥接函数：解密信道（验证签名后返回 message + sender_public_key）.

    Args:
        envelope: ``encrypt_channel`` 返回的字典（或兼容结构）。

    Returns:
        JSON 字符串，结构为::

            {"verified": true, "message": "...", "sender_public_key": "..."}

        或::

            {"verified": false, "error": "..."}
    """
    try:
        from laap.protocol.laap_com import decrypt_channel
        result = decrypt_channel(envelope)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"relay_decrypt: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"verified": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_p2p_relay_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 P2P Relay 五工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.p2p_relay_mcp_endpoints import (
            register_p2p_relay_tools,
        )
        register_p2p_relay_tools(mcp)

    注册的五个工具：

    - ``relay_register(public_key, name, address?, capabilities?, color?)``
      注册或更新中继节点
    - ``relay_heartbeat(public_key)`` 刷新心跳
    - ``relay_discover(include_offline=False)`` 列出在线节点
    - ``relay_offline(public_key, reason?)`` 手动标记节点离线
    - ``relay_signal(action, from_pk, to_pk, payload?)`` 信令交换
      （action ∈ ``{"offer", "answer", "ice", "poll"}``）
    - ``relay_decrypt(envelope)`` 验证并解密信道消息
    - ``relay_encrypt`` 不作为 MCP 工具暴露（私钥永不离开 sidecar，
      spec L435），仅 sidecar HTTP 端点可用

    幂等：本函数可被重复调用，FastMCP 内部去重。

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）。
    """
    if mcp_server is None:
        logger.warning("register_p2p_relay_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def relay_register(
        public_key: str,
        name: str,
        address: str = "",
        capabilities: list = None,
        color: str = "",
    ) -> str:
        """注册或更新中继节点（P3-p2p-relay SubTask 3.2）.

        幂等：同一 public_key 二次调用视为更新，不报错.

        Args:
            public_key: 节点 Ed25519 公钥（base64，32 字节 Raw）。
            name: LAAPer 显示名（唯一）。
            address: 可选，P2P 直连地址（信令交换后建立）。
            capabilities: 可选，能力清单字符串列表，如
                ``["code-review", "writing"]``。
            color: 可选，P2-bubble-field 兼容字段（泡泡颜色）。

        Returns:
            JSON 字符串，结构为::

                {
                  "registered": true,
                  "node": {public_key, name, address, capabilities,
                           color, online, last_heartbeat, registered_at}
                }
        """
        return handle_relay_register(
            public_key=public_key,
            name=name,
            address=address,
            capabilities=capabilities or [],
            color=color,
        )

    @mcp_server.tool()
    async def relay_heartbeat(public_key: str) -> str:
        """刷新节点心跳（P3-p2p-relay SubTask 3.5）.

        spec: 30 秒间隔，90 秒超时标记离线.
        未注册节点返回 ``ok: false``.

        Args:
            public_key: 节点 Ed25519 公钥（base64）。

        Returns:
            JSON 字符串，结构为::

                {
                  "ok": true,
                  "online": true,
                  "last_heartbeat": 1234567890.0,
                  "next_heartbeat_due": 1234567920.0
                }
        """
        return handle_relay_heartbeat(public_key)

    @mcp_server.tool()
    async def relay_discover(include_offline: bool = False) -> str:
        """列出在线节点（P3-p2p-relay SubTask 3.2）.

        先 sweep 标记超时节点离线，再返回在线列表.

        Args:
            include_offline: True 时返回包含离线节点在内的全部节点.

        Returns:
            JSON 字符串，结构为::

                {
                  "count": 2,
                  "nodes": [{public_key, name, ...}, ...]
                }
        """
        return handle_relay_discover(include_offline=include_offline)

    @mcp_server.tool()
    async def relay_offline(
        public_key: str,
        reason: str = "manual",
    ) -> str:
        """手动标记节点离线（P3-p2p-relay SubTask 3.2）.

        触发 ``agent_offline`` 事件，bubble-field 泡泡变暗.

        Args:
            public_key: 节点 Ed25519 公钥（base64）。
            reason: 离线原因（默认 ``"manual"``）。

        Returns:
            JSON 字符串，结构为::

                {
                  "ok": true,
                  "online": false,
                  "public_key": "...",
                  "name": "...",
                  "reason": "manual"
                }
        """
        return handle_relay_offline(public_key, reason=reason)

    @mcp_server.tool()
    async def relay_signal(
        action: str,
        from_pk: str = "",
        to_pk: str = "",
        payload: str = "",
    ) -> str:
        """P2P WebRTC 信令交换 stub（P3-p2p-relay SubTask 3.3）.

        真实 WebRTC 由前端 hanako 处理，本工具仅做信令中转（内存 stub）.

        Args:
            action: 信令动作，可选值：
                - ``"offer"``: 投递 WebRTC offer SDP
                - ``"answer"``: 投递 WebRTC answer SDP
                - ``"ice"``: 投递 ICE candidate
                - ``"poll"``: 轮询并清空接收方待取信令
            from_pk: 发送方公钥（post 动作必填）。
            to_pk: 接收方公钥（所有动作必填）。
            payload: SDP / ICE 内容（字符串形式，post 动作必填）。

        Returns:
            post 动作::

                {"posted": true, "signal_id": "sig_xxxx"}

            poll 动作::

                {"signals": [...], "count": N}
        """
        return handle_relay_signal(
            action=action,
            from_pk=from_pk,
            to_pk=to_pk,
            payload=payload,
        )

    @mcp_server.tool()
    async def relay_decrypt(signed_message: dict) -> str:
        """验证并解密信道消息（P3-p2p-relay SubTask 3.4）.

        验证签名后返回 message + sender_public_key；任何异常返回
        ``{verified: false, error: ...}``（不抛异常）.

        Args:
            signed_message: ``{message, signature, public_key}`` 字典
                （与 ``encrypt_channel`` 返回结构兼容）。

        Returns:
            JSON 字符串，结构为::

                {"verified": true, "message": "...", "sender_public_key": "..."}

            或::

                {"verified": false, "error": "..."}
        """
        return handle_relay_decrypt(signed_message)

    logger.info(
        "register_p2p_relay_tools: registered relay_register / "
        "relay_heartbeat / relay_discover / relay_offline / "
        "relay_signal / relay_decrypt (relay_encrypt 仅 sidecar 端点)"
    )
    return None
