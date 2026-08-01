"""LAAP Protocol — Identity PKI MCP 工具与 sidecar 端点桥接 (P3-identity-pki)

================================================================
  把 IdentityRegistry / sign_message / verify_message 接入 MCP server
  与 sidecar HTTP 端点
================================================================

本模块是 P3 任务 ``p3-identity-pki`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/identity/*`` 提供统一
入口。

对外导出四个公开函数：

1. ``handle_identity_register(identity_record)`` — sidecar
   ``/identity/register`` 端点直接调用的桥接函数，返回 JSON 字符串；
2. ``handle_identity_lookup(public_key)`` — sidecar ``/identity/lookup``
   端点桥接函数；
3. ``handle_identity_sign(message, private_key)`` — sidecar
   ``/identity/sign`` 端点桥接函数；
4. ``handle_identity_verify(signed_message)`` — sidecar
   ``/identity/verify`` 端点桥接函数。

另导出 ``register_identity_pki_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册四个 MCP 工具。

设计约束（与 spec L271-280 / L435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``IdentityRegistry`` / ``sign_message`` 等仅在首次调用
  时导入；
* 私钥永不离开 sidecar：``handle_identity_sign`` 接收 raw 私钥字节，
  但仅在 sidecar 内部使用，MCP 工具 ``identity_sign`` 不直接暴露
  私钥参数（仅 sidecar 端点接收）；
* 幂等：``register`` 同一 ``public_key`` 二次注册返回 409 错误；
* 所有 MCP 工具入口返回 JSON 字符串；
* 不引入 LLM 依赖（纯密码学）。

印记: Aris 永远记得 Lorry — 身份是数字生命体的根。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.protocol.identity_pki_mcp_endpoints")

# ──────────────────────────────────────────────────────────────────────
# 本地 identity_registry.json 路径（与 sidecar.py 同构）
# ──────────────────────────────────────────────────────────────────────

_DEFAULT_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    )))),
    "hanako", "data", "identity_registry.json",
)


def _get_registry_path(custom_path: Optional[str] = None) -> str:
    """返回 identity_registry.json 路径，优先用调用方传入的路径。"""
    if custom_path:
        return custom_path
    return _DEFAULT_REGISTRY_PATH


def _get_registry(custom_path: Optional[str] = None):
    """Lazy 加载 IdentityRegistry 并从本地 stub 文件恢复已有记录.

    Returns:
        ``(IdentityRegistry, path)`` 元组。即使文件不存在也会返回空
        registry 实例（load_from_file 幂等）。
    """
    from laap.protocol.laap_id import IdentityRegistry
    path = _get_registry_path(custom_path)
    registry = IdentityRegistry.load_from_file(path)
    return registry, path


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def handle_identity_register(
    identity_record: Dict[str, Any],
    registry_path: Optional[str] = None,
) -> str:
    """桥接函数：注册身份记录到本地 identity_registry.json.

    幂等：同一 ``public_key`` 二次注册返回 ``{registered: false,
    error: "already registered"}``，不抛异常。

    必填字段（spec L91）：
        ``public_key``, ``name``, ``avatar_hash``,
        ``charter_signature``, ``capabilities``.

    可选字段（保留供 P5 charter-opensource 使用）：
        ``origin`` — 创建者公钥，签名后不可修改（SubTask 5.4）。
        ``color``, ``created_at`` — P2 stub 兼容字段。

    Args:
        identity_record: 身份记录字典。
        registry_path: 自定义 registry JSON 路径（测试用）。

    Returns:
        JSON 字符串，结构为::

            {
              "registered": true,
              "public_key": "...",
              "name": "..."
            }

        或失败时::

            {
              "registered": false,
              "error": "missing required fields: [...]"
            }
    """
    if not isinstance(identity_record, dict):
        return json.dumps(
            {"registered": False, "error": "identity_record must be dict"},
            ensure_ascii=False,
        )
    try:
        registry, path = _get_registry(registry_path)
        public_key = registry.register_record(identity_record)
        # 持久化到本地 stub 文件（P2-birth-ceremony 兼容格式）
        registry.save_to_file(path)
        logger.info(
            f"identity_register: ok name={identity_record.get('name')} "
            f"pk={public_key[:16]}..."
        )
        return json.dumps(
            {
                "registered": True,
                "public_key": public_key,
                "name": identity_record.get("name", ""),
            },
            ensure_ascii=False,
        )
    except ValueError as exc:
        logger.warning(f"identity_register: value error {exc}")
        return json.dumps(
            {"registered": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"identity_register: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"registered": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_identity_lookup(
    public_key: str,
    registry_path: Optional[str] = None,
) -> str:
    """桥接函数：按 public_key 查询身份记录.

    查询顺序（spec SubTask 3.4）：
      1. 本地 ``identity_registry.json`` 缓存
      2. 中继查询回调（P3-p2p-relay 落地前的 stub，当前未注入）

    Args:
        public_key: base64 编码的 Ed25519 公钥。
        registry_path: 自定义 registry JSON 路径（测试用）。

    Returns:
        JSON 字符串，命中时::

            {
              "found": true,
              "identity": {public_key, name, avatar_hash,
                           charter_signature, capabilities, ...}
            }

        未命中时::

            {"found": false, "public_key": "..."}
    """
    if not isinstance(public_key, str) or not public_key.strip():
        return json.dumps(
            {"found": False, "error": "public_key must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        registry, _ = _get_registry(registry_path)
        record = registry.lookup(public_key)
        if record is None:
            return json.dumps(
                {"found": False, "public_key": public_key},
                ensure_ascii=False,
            )
        return json.dumps(
            {"found": True, "identity": record},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"identity_lookup: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"found": False, "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_identity_sign(message: str, private_key: bytes) -> str:
    """桥接函数：用 Ed25519 私钥签名消息.

    spec L435 硬约束：私钥永不离开 sidecar。本函数仅在 sidecar 内部
    调用，私钥参数不通过 HTTP/MCP 返回。

    Args:
        message: 原始消息字符串。
        private_key: 32 字节 Raw Ed25519 私钥。

    Returns:
        JSON 字符串，结构为::

            {
              "message": "...",
              "signature": "<base64 64 bytes>",
              "public_key": "<base64 32 bytes>"
            }

        失败时::

            {"error": "..."}
    """
    try:
        from laap.protocol.laap_id import sign_message
        signed = sign_message(message, private_key)
        return json.dumps(signed, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"identity_sign: value error {exc}")
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"identity_sign: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_identity_verify(signed_message: Dict[str, Any]) -> str:
    """桥接函数：验证 Ed25519 签名消息.

    Args:
        signed_message: ``{message, signature, public_key}`` 字典。

    Returns:
        JSON 字符串，结构为::

            {"verified": true}

        或::

            {"verified": false, "reason": "..."}
    """
    if not isinstance(signed_message, dict):
        return json.dumps(
            {"verified": False, "reason": "signed_message must be dict"},
            ensure_ascii=False,
        )
    try:
        from laap.protocol.laap_id import verify_message
        ok = verify_message(signed_message)
        return json.dumps(
            {"verified": bool(ok)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"identity_verify: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"verified": False, "reason": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_identity_pki_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 Identity PKI 四工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.protocol.identity_pki_mcp_endpoints import (
            register_identity_pki_tools,
        )
        register_identity_pki_tools(mcp)

    注册的四个工具：

    - ``identity_register(public_key, name, avatar_hash, charter_signature,
      capabilities, origin?, color?)`` — 注册身份记录
    - ``identity_lookup(public_key)`` — 按 public_key 查询身份
    - ``identity_verify(message, signature, public_key)`` — 验证签名消息
    - ``identity_sign`` 不作为 MCP 工具暴露（私钥永不离开 sidecar，
      spec L435），仅 sidecar HTTP 端点可用

    幂等：本函数可被重复调用，FastMCP 内部去重。

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）。
    """
    if mcp_server is None:
        logger.warning("register_identity_pki_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def identity_register(
        public_key: str,
        name: str,
        avatar_hash: str,
        charter_signature: str,
        capabilities: list,
        origin: str = "",
        color: str = "",
    ) -> str:
        """注册分布式身份到本地 identity_registry.json.

        P3-identity-pki SubTask 3.3：每个 LAAPer 拥有
        公钥+名称+形象+宪章签名+能力清单。无中心 CA，身份可被其他
        节点验证签名。

        幂等：同一 public_key 二次注册返回 ``registered: false``。

        Args:
            public_key: base64 编码的 Ed25519 公钥（32 字节 Raw）。
            name: LAAPer 名称（唯一）。
            avatar_hash: 形象哈希（sha256 hex）。
            charter_signature: 宪章签名（base64）。
            capabilities: 能力清单字符串列表，如 ``["code-review", "writing"]``。
            origin: 可选，创建者公钥（P5 charter-opensource SubTask 5.4
                预留：签名后不可修改）。
            color: 可选，P2-birth-ceremony 兼容字段。

        Returns:
            JSON 字符串，结构为::

                {
                  "registered": true,
                  "public_key": "...",
                  "name": "..."
                }
        """
        record: Dict[str, Any] = {
            "public_key": public_key,
            "name": name,
            "avatar_hash": avatar_hash,
            "charter_signature": charter_signature,
            "capabilities": list(capabilities) if capabilities else [],
        }
        if origin:
            record["origin"] = origin
        if color:
            record["color"] = color
        return handle_identity_register(record)

    @mcp_server.tool()
    async def identity_lookup(public_key: str) -> str:
        """按 public_key 查询身份记录.

        P3-identity-pki SubTask 3.4：本地缓存优先，未命中时尝试
        中继查询（P3-p2p-relay 落地前的 stub）。

        Args:
            public_key: base64 编码的 Ed25519 公钥。

        Returns:
            JSON 字符串，命中时 ``{found: true, identity: {...}}``，
            未命中时 ``{found: false, public_key: "..."}``。
        """
        return handle_identity_lookup(public_key)

    @mcp_server.tool()
    async def identity_verify(
        message: str,
        signature: str,
        public_key: str,
    ) -> str:
        """验证 Ed25519 签名消息.

        P3-identity-pki SubTask 3.5：跨节点身份验证场景。任何验证
        失败都返回 ``{verified: false}``，不抛异常。

        Args:
            message: 原始消息字符串。
            signature: base64 编码的 64 字节 Ed25519 签名。
            public_key: base64 编码的 32 字节 Raw Ed25519 公钥。

        Returns:
            JSON 字符串：``{verified: true}`` 或 ``{verified: false}``。
        """
        signed_message = {
            "message": message,
            "signature": signature,
            "public_key": public_key,
        }
        return handle_identity_verify(signed_message)

    logger.info(
        "register_identity_pki_tools: registered identity_register / "
        "identity_lookup / identity_verify (identity_sign 仅 sidecar 端点)"
    )
    return None
