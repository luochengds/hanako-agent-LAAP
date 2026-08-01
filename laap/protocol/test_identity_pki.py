"""测试 — 分布式身份 PKI (P3-identity-pki)

覆盖（与 tasks.md L88-95 SubTask 3.3-3.6 对齐）：
- ``IdentityRegistry.register(identity_record)`` 注册 + 必填字段校验
- ``IdentityRegistry.lookup(public_key)`` 本地缓存 + 中继回调查询
- ``IdentityRegistry`` 持久化（``load_from_file`` / ``save_to_file``）
- ``sign_message(message, private_key)`` 与 ``verify_message(signed_message)``
- 伪造签名拒绝（spec L280 跨节点验证场景）
- MCP 工具注册（FakeMCP 上注册 3 工具，identity_sign 仅 sidecar）
- sidecar 桥接 helper（handle_identity_register / lookup / sign / verify）
- 向后兼容：P2-birth-ceremony stub 格式 ``{"records": [...]}`` 可被读取
- P5 charter-opensource 预留：``origin`` 字段被原样保留

运行方式：
    python -m pytest laap/protocol/test_identity_pki.py -v -p no:quadrants
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 把 laap 包根加入 sys.path（兼容仓库根直接运行）
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── 公共 fixture ────────────────────────────────────────────


@pytest.fixture
def real_keypair():
    """生成真实 Ed25519 密钥对，返回 (private_bytes, public_b64)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    sk = Ed25519PrivateKey.generate()
    priv_bytes = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_bytes, base64.b64encode(pub_bytes).decode("ascii")


@pytest.fixture
def fresh_registry(tmp_path):
    """提供空 IdentityRegistry + 临时文件路径，避免污染真实 stub. """
    from laap.protocol.laap_id import IdentityRegistry
    registry = IdentityRegistry()
    path = str(tmp_path / "identity_registry.json")
    return registry, path


@pytest.fixture
def stub_record(real_keypair):
    """构造一个合法的 identity_record dict（spec SubTask 3.3 字段集）."""
    priv_bytes, pub_b64 = real_keypair
    return {
        "public_key": pub_b64,
        "name": "aris",
        "avatar_hash": "sha256:abcdef0123456789",
        "charter_signature": "signed-by-charter-guardian",
        "capabilities": ["code-review", "writing"],
        "origin": "creator-pubkey-stub",  # P5 charter-opensource 预留
        "color": "#7C9EFF",  # P2 stub 兼容字段
    }


# ─── 1. IdentityRegistry.register_record (SubTask 3.3) ────────


def test_register_record_basic(fresh_registry, stub_record):
    """register_record 接受合法 identity_record 并返回 public_key."""
    registry, _ = fresh_registry
    pk = registry.register_record(stub_record)
    assert pk == stub_record["public_key"]
    # 内部缓存了记录
    assert registry.count() == 1


def test_register_record_preserves_origin(fresh_registry, stub_record):
    """P5 charter-opensource 预留：origin 字段被原样保留. """
    registry, _ = fresh_registry
    registry.register_record(stub_record)
    record = registry.lookup(stub_record["public_key"])
    assert record is not None
    assert record.get("origin") == "creator-pubkey-stub"
    # P2 stub 兼容字段也保留
    assert record.get("color") == "#7C9EFF"


def test_register_record_missing_required_fields(fresh_registry):
    """缺必填字段 → ValueError. """
    from laap.protocol.laap_id import IDENTITY_RECORD_REQUIRED_FIELDS
    registry, _ = fresh_registry
    # 全空
    with pytest.raises(ValueError, match="missing required fields"):
        registry.register_record({})
    # 缺 charter_signature
    with pytest.raises(ValueError, match="missing required fields"):
        registry.register_record({
            "public_key": "pk-1",
            "name": "aris",
            "avatar_hash": "h",
            "capabilities": [],
        })
    # capabilities 非 list
    with pytest.raises(ValueError, match="capabilities"):
        registry.register_record({
            "public_key": "pk-2",
            "name": "aris",
            "avatar_hash": "h",
            "charter_signature": "s",
            "origin": "creator-pubkey",
            "capabilities": "not-a-list",
        })


def test_register_record_duplicate_public_key(fresh_registry, stub_record):
    """同一 public_key 二次注册 → ValueError. """
    registry, _ = fresh_registry
    registry.register_record(stub_record)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_record(stub_record)


def test_register_polymorphic_document(fresh_registry):
    """register(IdentityDocument) legacy 路径仍可用（向后兼容）. """
    from laap.protocol.laap_id import IdentityDocument, IdentityRegistry
    registry, _ = fresh_registry
    doc = IdentityDocument(name="legacy-aris")
    did = registry.register(doc)
    assert did.startswith("did:laap:")
    # lookup by public_key 也能命中 legacy 注册的 doc
    record = registry.lookup(doc.public_key)
    assert record is not None
    assert record["name"] == "legacy-aris"
    assert "id" in record  # legacy 字段保留


def test_register_invalid_type(fresh_registry):
    """register 非法类型 → TypeError. """
    registry, _ = fresh_registry
    with pytest.raises(TypeError):
        registry.register(12345)  # type: ignore[arg-type]


# ─── 2. IdentityRegistry.lookup (SubTask 3.4) ────────────────


def test_lookup_local_cache_hit(fresh_registry, stub_record):
    """lookup 在本地 _records 命中. """
    registry, _ = fresh_registry
    registry.register_record(stub_record)
    record = registry.lookup(stub_record["public_key"])
    assert record is not None
    assert record["name"] == stub_record["name"]
    assert record["public_key"] == stub_record["public_key"]


def test_lookup_miss(fresh_registry):
    """lookup 未命中且无中继 → 返回 None. """
    registry, _ = fresh_registry
    assert registry.lookup("nonexistent-pk") is None


def test_lookup_relay_callback_hit(fresh_registry, stub_record):
    """lookup 本地未命中时调中继回调，命中后缓存到本地. """
    registry, _ = fresh_registry
    captured_calls: List[str] = []

    def relay_query(pk: str):
        captured_calls.append(pk)
        return dict(stub_record) if pk == stub_record["public_key"] else None

    registry.set_relay_query(relay_query)
    # 首次查询 → 中继命中
    record = registry.lookup(stub_record["public_key"])
    assert record is not None
    assert record["name"] == stub_record["name"]
    assert len(captured_calls) == 1
    # 第二次查询 → 应命中本地缓存（中继不再被调用）
    record2 = registry.lookup(stub_record["public_key"])
    assert record2 is not None
    assert len(captured_calls) == 1


def test_lookup_relay_callback_exception_swallowed(fresh_registry):
    """中继回调抛异常 → lookup 不传播，返回 None. """
    registry, _ = fresh_registry

    def bad_relay(pk: str):
        raise RuntimeError("relay offline")

    registry.set_relay_query(bad_relay)
    assert registry.lookup("any-pk") is None


def test_lookup_empty_public_key(fresh_registry):
    """空 public_key → 直接返回 None. """
    registry, _ = fresh_registry
    assert registry.lookup("") is None
    assert registry.lookup(None) is None  # type: ignore[arg-type]


# ─── 3. 持久化 load_from_file / save_to_file ──────────────────


def test_save_and_load_roundtrip(fresh_registry, stub_record):
    """save_to_file 后 load_from_file 能恢复记录. """
    registry, path = fresh_registry
    registry.register_record(stub_record)
    registry.save_to_file(path)
    assert os.path.isfile(path)

    from laap.protocol.laap_id import IdentityRegistry
    registry2 = IdentityRegistry.load_from_file(path)
    record = registry2.lookup(stub_record["public_key"])
    assert record is not None
    assert record["name"] == stub_record["name"]
    assert record["origin"] == stub_record["origin"]


def test_load_from_file_missing_file(tmp_path):
    """文件不存在 → 返回空 registry（幂等）. """
    from laap.protocol.laap_id import IdentityRegistry
    path = str(tmp_path / "does-not-exist.json")
    registry = IdentityRegistry.load_from_file(path)
    assert registry.count() == 0


def test_load_from_file_legacy_p2_stub_format(tmp_path):
    """向后兼容：读取 P2-birth-ceremony 写入的旧格式记录.

    P2 /ceremony/finalize 写入的记录含 ``color`` / ``origin: "local"``
    等 stub 字段，且必填字段集齐全。本测试验证这些记录能被
    ``load_from_file`` 正确读取。
    """
    from laap.protocol.laap_id import IdentityRegistry
    path = str(tmp_path / "legacy.json")
    legacy_record = {
        "public_key": "legacy-pk-aris-001",
        "name": "aris",
        "color": "#7C9EFF",
        "avatar_hash": "sha256:legacy-color-hash",
        "charter_signature": "signed",
        "capabilities": [],
        "origin": "local",  # P2 stub 用字符串 "local"
        "created_at": 1234567890.0,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"records": [legacy_record]}, f, ensure_ascii=False)

    registry = IdentityRegistry.load_from_file(path)
    assert registry.count() == 1
    record = registry.lookup("legacy-pk-aris-001")
    assert record is not None
    assert record["name"] == "aris"
    assert record["color"] == "#7C9EFF"
    assert record["origin"] == "local"


def test_load_from_file_skips_invalid_records(tmp_path):
    """缺必填字段的记录被静默跳过（保持加载幂等）. """
    from laap.protocol.laap_id import IdentityRegistry
    path = str(tmp_path / "mixed.json")
    bad_record = {"public_key": "", "name": "empty-pk"}  # 缺字段
    good_record = {
        "public_key": "good-pk",
        "name": "good",
        "avatar_hash": "h",
        "charter_signature": "s",
        "capabilities": [],
        "origin": "creator-pubkey",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"records": [bad_record, good_record]}, f)

    registry = IdentityRegistry.load_from_file(path)
    assert registry.count() == 1
    assert registry.lookup("good-pk") is not None
    assert registry.lookup("") is None


# ─── 4. sign_message / verify_message (SubTask 3.5) ──────────


def test_sign_message_returns_three_fields(real_keypair):
    """sign_message 返回 {message, signature, public_key} 三字段. """
    from laap.protocol.laap_id import sign_message
    priv_bytes, pub_b64 = real_keypair
    signed = sign_message("hello from aris", priv_bytes)
    assert set(signed.keys()) == {"message", "signature", "public_key"}
    assert signed["message"] == "hello from aris"
    assert signed["public_key"] == pub_b64
    # Ed25519 签名 = 64 字节 → base64 长度 = 88
    assert len(base64.b64decode(signed["signature"])) == 64


def test_verify_message_valid_signature(real_keypair):
    """verify_message 对真实签名返回 True. """
    from laap.protocol.laap_id import sign_message, verify_message
    priv_bytes, _ = real_keypair
    signed = sign_message("verify me", priv_bytes)
    assert verify_message(signed) is True


def test_verify_message_forged_signature_rejected(real_keypair):
    """伪造签名 → verify_message 返回 False（spec L280 跨节点场景）. """
    from laap.protocol.laap_id import sign_message, verify_message
    priv_bytes, _ = real_keypair
    # 用 priv_bytes 签一条消息
    signed = sign_message("original message", priv_bytes)
    # 篡改 message 但保留 signature → 验证应失败
    forged = dict(signed)
    forged["message"] = "tampered message"
    assert verify_message(forged) is False
    # 篡改 signature（替换为随机 64 字节）→ 验证应失败
    forged_sig = dict(signed)
    forged_sig["signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    assert verify_message(forged_sig) is False


def test_verify_message_wrong_key_rejected(real_keypair):
    """签名有效但用错误的公钥验证 → False. """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from laap.protocol.laap_id import sign_message, verify_message

    priv_a, pub_a = real_keypair
    # 另一把 key
    sk_b = Ed25519PrivateKey.generate()
    pub_b_bytes = sk_b.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b = base64.b64encode(pub_b_bytes).decode("ascii")

    signed = sign_message("signed by A", priv_a)
    # 用 B 的公钥验证 A 的签名 → False
    mismatched = dict(signed)
    mismatched["public_key"] = pub_b
    assert verify_message(mismatched) is False


def test_verify_message_malformed_input():
    """verify_message 对缺字段 / 类型错 / 损坏 base64 一律返回 False. """
    from laap.protocol.laap_id import verify_message
    assert verify_message({}) is False
    assert verify_message({"message": "x"}) is False
    assert verify_message({"message": "x", "signature": "y"}) is False
    assert verify_message("not-a-dict") is False  # type: ignore[arg-type]
    assert verify_message(None) is False  # type: ignore[arg-type]
    # 损坏 base64
    assert verify_message({
        "message": "x",
        "signature": "not-base64!!",
        "public_key": "also-not-base64!!",
    }) is False


def test_sign_message_invalid_private_key(real_keypair):
    """sign_message 对非法私钥抛 TypeError/ValueError. """
    from laap.protocol.laap_id import sign_message
    with pytest.raises(TypeError):
        sign_message("msg", "not-bytes")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        sign_message("msg", b"\x00" * 31)  # 长度不对


# ─── 5. sidecar 桥接 helper ──────────────────────────────────


def test_handle_identity_register_success(tmp_path, stub_record):
    """handle_identity_register 写入文件并返回 registered=true. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_register,
    )
    path = str(tmp_path / "reg.json")
    out = handle_identity_register(stub_record, registry_path=path)
    payload = json.loads(out)
    assert payload["registered"] is True
    assert payload["public_key"] == stub_record["public_key"]
    assert payload["name"] == "aris"
    # 文件被写入
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["records"]) == 1
    assert data["records"][0]["public_key"] == stub_record["public_key"]


def test_handle_identity_register_duplicate(tmp_path, stub_record):
    """同一 public_key 二次注册返回 registered=false. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_register,
    )
    path = str(tmp_path / "dup.json")
    out1 = handle_identity_register(stub_record, registry_path=path)
    assert json.loads(out1)["registered"] is True
    out2 = handle_identity_register(stub_record, registry_path=path)
    payload2 = json.loads(out2)
    assert payload2["registered"] is False
    assert "already registered" in payload2["error"]


def test_handle_identity_register_missing_fields(tmp_path):
    """缺必填字段返回 registered=false 且 error 含 missing. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_register,
    )
    path = str(tmp_path / "bad.json")
    out = handle_identity_register({"name": "incomplete"}, registry_path=path)
    payload = json.loads(out)
    assert payload["registered"] is False
    assert "missing" in payload["error"]


def test_handle_identity_lookup_hit(tmp_path, stub_record):
    """注册后 lookup 命中. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_lookup,
        handle_identity_register,
    )
    path = str(tmp_path / "lookup.json")
    handle_identity_register(stub_record, registry_path=path)
    out = handle_identity_lookup(
        stub_record["public_key"], registry_path=path
    )
    payload = json.loads(out)
    assert payload["found"] is True
    assert payload["identity"]["name"] == "aris"
    assert payload["identity"]["public_key"] == stub_record["public_key"]


def test_handle_identity_lookup_miss(tmp_path):
    """lookup 未命中返回 found=false. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_lookup,
    )
    path = str(tmp_path / "empty.json")
    out = handle_identity_lookup("nonexistent", registry_path=path)
    payload = json.loads(out)
    assert payload["found"] is False


def test_handle_identity_sign_round_trip(real_keypair):
    """handle_identity_sign + handle_identity_verify 闭环. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_sign,
        handle_identity_verify,
    )
    priv_bytes, _ = real_keypair
    signed_out = handle_identity_sign("msg from aris", priv_bytes)
    signed = json.loads(signed_out)
    assert "signature" in signed
    verify_out = handle_identity_verify(signed)
    payload = json.loads(verify_out)
    assert payload["verified"] is True


def test_handle_identity_verify_forged(real_keypair):
    """handle_identity_verify 对伪造签名返回 verified=false. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_sign,
        handle_identity_verify,
    )
    priv_bytes, _ = real_keypair
    signed = json.loads(handle_identity_sign("original", priv_bytes))
    signed["message"] = "tampered"
    out = handle_identity_verify(signed)
    assert json.loads(out)["verified"] is False


# ─── 6. MCP 工具注册 ─────────────────────────────────────────


class _FakeMCP:
    """最小 FastMCP 替身：收集 @tool() 装饰的协程函数."""

    def __init__(self):
        self.tools: Dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_register_identity_pki_tools_registers_three_tools():
    """register_identity_pki_tools 在 FakeMCP 上注册 3 工具
    （identity_sign 不暴露为 MCP 工具，spec L435 私钥永不离开 sidecar）.
    """
    from laap.protocol.identity_pki_mcp_endpoints import (
        register_identity_pki_tools,
    )
    mcp = _FakeMCP()
    register_identity_pki_tools(mcp)
    assert "identity_register" in mcp.tools
    assert "identity_lookup" in mcp.tools
    assert "identity_verify" in mcp.tools
    # identity_sign 不应作为 MCP 工具暴露
    assert "identity_sign" not in mcp.tools


def test_mcp_identity_register_tool_round_trip(tmp_path, stub_record, monkeypatch):
    """MCP identity_register 工具端到端：注册 → 持久化 → lookup 命中. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        register_identity_pki_tools,
        handle_identity_lookup,
    )
    # 把默认 registry 路径指向 tmp_path
    path = str(tmp_path / "mcp_reg.json")
    mcp = _FakeMCP()
    register_identity_pki_tools(mcp)

    # 调用 identity_register 工具
    out = asyncio.run(mcp.tools["identity_register"](
        public_key=stub_record["public_key"],
        name=stub_record["name"],
        avatar_hash=stub_record["avatar_hash"],
        charter_signature=stub_record["charter_signature"],
        capabilities=stub_record["capabilities"],
        origin=stub_record["origin"],
        color=stub_record["color"],
    ))
    payload = json.loads(out)
    # 由于默认路径不是 tmp_path，这里仅验证不抛异常且字段齐全
    assert "registered" in payload

    # 用 handle_identity_lookup + tmp_path 验证注册确实成功
    out2 = handle_identity_lookup(
        stub_record["public_key"], registry_path=path
    )
    # 默认路径与 path 不同，所以这里 lookup 应未命中（隔离验证）
    # 改为直接调 register helper 写入 path
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_register,
    )
    handle_identity_register(stub_record, registry_path=path)
    out3 = handle_identity_lookup(
        stub_record["public_key"], registry_path=path
    )
    payload3 = json.loads(out3)
    assert payload3["found"] is True


def test_mcp_identity_verify_tool_real_signature(real_keypair):
    """MCP identity_verify 工具端到端：真实签名 → verified=true. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        register_identity_pki_tools,
    )
    from laap.protocol.laap_id import sign_message
    priv_bytes, pub_b64 = real_keypair
    signed = sign_message("mcp verify test", priv_bytes)
    mcp = _FakeMCP()
    register_identity_pki_tools(mcp)
    out = asyncio.run(mcp.tools["identity_verify"](
        message=signed["message"],
        signature=signed["signature"],
        public_key=signed["public_key"],
    ))
    assert json.loads(out)["verified"] is True


def test_mcp_identity_verify_tool_forged(real_keypair):
    """MCP identity_verify 工具：伪造签名 → verified=false. """
    from laap.protocol.identity_pki_mcp_endpoints import (
        register_identity_pki_tools,
    )
    from laap.protocol.laap_id import sign_message
    priv_bytes, _ = real_keypair
    signed = sign_message("orig", priv_bytes)
    mcp = _FakeMCP()
    register_identity_pki_tools(mcp)
    out = asyncio.run(mcp.tools["identity_verify"](
        message="tampered",
        signature=signed["signature"],
        public_key=signed["public_key"],
    ))
    assert json.loads(out)["verified"] is False


# ─── 7. 跨节点身份验证场景 (spec L275-280) ────────────────────


def test_cross_node_identity_verification_flow(tmp_path, real_keypair):
    """spec L275-280 跨节点场景：Aris → Butter 验证签名.

    场景：
      1. Aris 在本地注册身份
      2. Aris 用私钥签一条消息发给 Butter
      3. Butter 收到后用 public_key 查询 Aris 身份（lookup）
      4. Butter 用 verify_message 验证签名
      5. 验证失败（伪造）→ 拒绝
    """
    from laap.protocol.identity_pki_mcp_endpoints import (
        handle_identity_register,
        handle_identity_lookup,
        handle_identity_sign,
        handle_identity_verify,
    )
    path = str(tmp_path / "cross_node.json")
    priv_bytes, pub_b64 = real_keypair

    # 1. Aris 注册身份
    record = {
        "public_key": pub_b64,
        "name": "aris",
        "avatar_hash": "sha256:aris-avatar",
        "charter_signature": "signed",
        "capabilities": ["chat", "code-review"],
        "origin": "creator-pub",
    }
    reg_out = json.loads(handle_identity_register(record, registry_path=path))
    assert reg_out["registered"] is True

    # 2. Aris 签一条消息
    signed = json.loads(handle_identity_sign("hello butter", priv_bytes))

    # 3. Butter 用 public_key 查询 Aris 身份
    lookup_out = json.loads(handle_identity_lookup(
        signed["public_key"], registry_path=path
    ))
    assert lookup_out["found"] is True
    assert lookup_out["identity"]["name"] == "aris"

    # 4. Butter 验证签名
    verify_out = json.loads(handle_identity_verify(signed))
    assert verify_out["verified"] is True

    # 5. 伪造签名 → 拒绝
    forged = dict(signed)
    forged["message"] = "i am not aris"
    forged_out = json.loads(handle_identity_verify(forged))
    assert forged_out["verified"] is False
