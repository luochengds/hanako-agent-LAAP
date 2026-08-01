"""测试 — 1v1 跨实例对话协议 (P3-1v1-protocol)

覆盖（与 tasks.md L104-109 SubTask 3.1-3.5 对齐）：
- ``OneOnOneManager.send_1v1`` 产出签名信封 + 写入历史
- ``OneOnOneManager.receive_1v1`` 验签后返回 content + sender_public_key
- ``OneOnOneManager.get_history`` 双向历史查询
- 伪造签名 / 篡改消息被拒绝
- MCP 工具注册（FakeMCP 上注册 chat_receive / chat_history，
  chat_send 仅 sidecar）
- sidecar 桥接 helper（handle_chat_send / receive / history）
- 冒烟测试：本地模拟两个 LAAPer 实例 1v1 消息往返签名验证通过
  （spec L427）

运行方式：
    python -m pytest laap/protocol/test_1v1_protocol.py -v -p no:quadrants
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

# 把 laap 包根加入 sys.path（兼容仓库根直接运行）
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── 公共 fixture ────────────────────────────────────────────


def _make_keypair() -> tuple:
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
def alice_keypair():
    """LAAPer Alice 的真实 Ed25519 密钥对."""
    return _make_keypair()


@pytest.fixture
def bob_keypair():
    """LAAPer Bob 的真实 Ed25519 密钥对."""
    return _make_keypair()


@pytest.fixture
def fresh_manager():
    """重置全局 OneOnOneManager，避免跨用例污染."""
    from laap.protocol.laap_com import reset_one_on_one_manager_for_test
    return reset_one_on_one_manager_for_test()


# ─── FakeMCP（用于测试 MCP 工具注册） ─────────────────────


class _FakeTool:
    def __init__(self, name, func):
        self.name = name
        self.func = func

    async def call(self, **kwargs):
        return await self.func(**kwargs)


class FakeMCP:
    """最小 FastMCP 替身，记录 tool() 装饰过的函数."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


# ─── SubTask 3.1/3.2: send_1v1 / receive_1v1 闭环 ─────────


class TestSendReceiveRoundTrip:
    """send_1v1 → receive_1v1 签名验证闭环."""

    def test_send_returns_signed_envelope_and_message_id(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]

        result = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="Hello Bob from Alice",
            private_key=alice_priv,
        )
        assert result["stored"] is True
        assert result["message_id"].startswith("msg_1v1_")
        envelope = result["envelope"]
        assert envelope["message"] == "Hello Bob from Alice"
        assert envelope["signature"]
        assert envelope["public_key"] == alice_pub
        assert envelope["peer_public_key"] == bob_pub

    def test_receive_verifies_signature_and_returns_content(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]

        send_result = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="Signed message",
            private_key=alice_priv,
        )
        recv_result = fresh_manager.receive_1v1(send_result["envelope"])
        assert recv_result["verified"] is True
        assert recv_result["content"] == "Signed message"
        assert recv_result["sender_public_key"] == alice_pub

    def test_tampered_message_rejected(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        """篡改 envelope.message 后验签必须失败."""
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]

        send_result = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="original",
            private_key=alice_priv,
        )
        tampered = dict(send_result["envelope"])
        tampered["message"] = "tampered content"
        recv_result = fresh_manager.receive_1v1(tampered)
        assert recv_result["verified"] is False
        assert "error" in recv_result

    def test_forged_signature_rejected(self, fresh_manager, bob_keypair):
        """完全伪造的签名验签失败."""
        bob_pub = bob_keypair[1]
        forged = {
            "message": "I am fake",
            "signature": base64.b64encode(b"\x00" * 64).decode("ascii"),
            "public_key": bob_pub,
            "peer_public_key": bob_pub,
        }
        recv_result = fresh_manager.receive_1v1(forged)
        assert recv_result["verified"] is False

    def test_malformed_envelope_rejected(self, fresh_manager):
        """非 dict / 缺字段 / 空签名均返回 verified=False."""
        assert fresh_manager.receive_1v1("not a dict")["verified"] is False
        assert fresh_manager.receive_1v1({})["verified"] is False
        assert fresh_manager.receive_1v1(
            {"message": "x", "signature": "", "public_key": "y"}
        )["verified"] is False

    def test_invalid_private_key_raises(self, fresh_manager, bob_keypair):
        """私钥格式错误透传异常（TypeError/ValueError）."""
        bob_pub = bob_keypair[1]
        with pytest.raises((TypeError, ValueError)):
            fresh_manager.send_1v1(
                sender_public_key="pk_alice",
                peer_public_key=bob_pub,
                message="x",
                private_key=b"short",
            )


# ─── SubTask 3.1: get_history 双向查询 ─────────────────────


class TestHistory:
    """1v1 对话历史双向查询."""

    def test_history_empty_for_unknown_pair(self, fresh_manager):
        msgs = fresh_manager.get_history("pk_a", "pk_b")
        assert msgs == []

    def test_history_bidirectional_after_send(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        """发送后双方视角的历史都能查到该消息."""
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]

        fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="msg1",
            private_key=alice_priv,
        )
        # 从 Alice 视角查
        history_a = fresh_manager.get_history(alice_pub, bob_pub)
        assert len(history_a) == 1
        assert history_a[0]["content"] == "msg1"
        assert history_a[0]["sender_public_key"] == alice_pub
        # 从 Bob 视角查（双向）
        history_b = fresh_manager.get_history(bob_pub, alice_pub)
        assert len(history_b) == 1
        assert history_b[0]["content"] == "msg1"

    def test_history_records_inbound_for_full_round_trip(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        """send + record_inbound 后历史含两条（出+入）."""
        alice_priv, alice_pub = alice_keypair
        bob_priv, bob_pub = bob_keypair

        # Alice 发给 Bob
        send_res = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="Hi Bob",
            private_key=alice_priv,
        )
        # Bob 收到并验签 → 归档入站（模拟 sidecar /chat/receive 调 record_inbound）
        fresh_manager.record_inbound(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            content="Hi Bob",
            envelope=send_res["envelope"],
        )
        history = fresh_manager.get_history(alice_pub, bob_pub)
        assert len(history) == 2

    def test_count(self, fresh_manager, alice_keypair, bob_keypair):
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        assert fresh_manager.count() == 0
        fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="x",
            private_key=alice_priv,
        )
        assert fresh_manager.count() == 1


# ─── SubTask 3.5: 两实例往返冒烟测试 ─────────────────────


class TestTwoInstanceSmoke:
    """本地模拟两个 LAAPer 实例 1v1 消息往返签名验证通过.

    spec L427: 冒烟测试即可.
    """

    def test_alice_bob_round_trip_both_directions(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        alice_priv, alice_pub = alice_keypair
        bob_priv, bob_pub = bob_keypair

        # Alice → Bob
        a2b = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="Hello Bob",
            private_key=alice_priv,
        )
        bob_recv = fresh_manager.receive_1v1(a2b["envelope"])
        assert bob_recv["verified"] is True
        assert bob_recv["content"] == "Hello Bob"
        assert bob_recv["sender_public_key"] == alice_pub

        # Bob → Alice（回复）
        b2a = fresh_manager.send_1v1(
            sender_public_key=bob_pub,
            peer_public_key=alice_pub,
            message="Hi Alice, message received",
            private_key=bob_priv,
        )
        alice_recv = fresh_manager.receive_1v1(b2a["envelope"])
        assert alice_recv["verified"] is True
        assert alice_recv["content"] == "Hi Alice, message received"
        assert alice_recv["sender_public_key"] == bob_pub

        # 双向历史
        history = fresh_manager.get_history(alice_pub, bob_pub)
        assert len(history) == 2
        contents = [m["content"] for m in history]
        assert "Hello Bob" in contents
        assert "Hi Alice, message received" in contents


# ─── MCP 工具注册 ─────────────────────────────────────────


class TestMCPRegistration:
    """register_1v1_protocol_tools 在 FakeMCP 上注册工具."""

    def test_registers_two_tools(self):
        from laap.protocol.one_on_one_mcp_endpoints import (
            register_1v1_protocol_tools,
        )
        mcp = FakeMCP()
        register_1v1_protocol_tools(mcp)
        # chat_send 不作为 MCP 工具暴露（私钥不离开 sidecar）
        assert "chat_receive" in mcp.tools
        assert "chat_history" in mcp.tools
        assert "chat_send" not in mcp.tools

    def test_none_mcp_is_noop(self):
        from laap.protocol.one_on_one_mcp_endpoints import (
            register_1v1_protocol_tools,
        )
        # 不抛异常
        register_1v1_protocol_tools(None)

    def test_chat_receive_tool_verifies(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        from laap.protocol.one_on_one_mcp_endpoints import (
            register_1v1_protocol_tools,
        )
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        send_res = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message="tool test",
            private_key=alice_priv,
        )
        mcp = FakeMCP()
        register_1v1_protocol_tools(mcp)
        out = json.loads(
            __import__("asyncio").run(
                mcp.tools["chat_receive"](signed_message=send_res["envelope"])
            )
        )
        assert out["verified"] is True
        assert out["content"] == "tool test"


# ─── sidecar 桥接 helper ─────────────────────────────────


class TestSidecarHelpers:
    """handle_chat_send / receive / history 桥接函数."""

    def test_handle_chat_send_success(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        from laap.protocol.one_on_one_mcp_endpoints import handle_chat_send
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        out = json.loads(
            handle_chat_send(alice_pub, bob_pub, "via sidecar", alice_priv)
        )
        assert out["sent"] is True
        assert out["message_id"].startswith("msg_1v1_")
        assert out["envelope"]["message"] == "via sidecar"

    def test_handle_chat_send_validates_inputs(
        self, fresh_manager, bob_keypair
    ):
        from laap.protocol.one_on_one_mcp_endpoints import handle_chat_send
        bob_pub = bob_keypair[1]
        # 空 sender
        out = json.loads(handle_chat_send("", bob_pub, "x", b"k" * 32))
        assert out["sent"] is False
        assert "sender_public_key" in out["error"]
        # 空 message
        out = json.loads(handle_chat_send("pk", bob_pub, "", b"k" * 32))
        assert out["sent"] is False

    def test_handle_chat_receive_success(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        from laap.protocol.one_on_one_mcp_endpoints import (
            handle_chat_receive, handle_chat_send,
        )
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        send_out = json.loads(
            handle_chat_send(alice_pub, bob_pub, "round trip", alice_priv)
        )
        recv_out = json.loads(handle_chat_receive(send_out["envelope"]))
        assert recv_out["verified"] is True
        assert recv_out["content"] == "round trip"
        assert recv_out["sender_public_key"] == alice_pub
        assert recv_out["stored"] is True

    def test_handle_chat_receive_forgery(self, fresh_manager, bob_keypair):
        from laap.protocol.one_on_one_mcp_endpoints import handle_chat_receive
        bob_pub = bob_keypair[1]
        forged = {
            "message": "fake",
            "signature": base64.b64encode(b"\x00" * 64).decode("ascii"),
            "public_key": bob_pub,
        }
        out = json.loads(handle_chat_receive(forged))
        assert out["verified"] is False

    def test_handle_chat_history(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        from laap.protocol.one_on_one_mcp_endpoints import (
            handle_chat_history, handle_chat_send,
        )
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        handle_chat_send(alice_pub, bob_pub, "h1", alice_priv)
        handle_chat_send(alice_pub, bob_pub, "h2", alice_priv)
        out = json.loads(handle_chat_history(alice_pub, bob_pub))
        assert out["count"] == 2
        contents = [m["content"] for m in out["messages"]]
        assert "h1" in contents and "h2" in contents

    def test_handle_chat_history_validates_inputs(self, fresh_manager):
        from laap.protocol.one_on_one_mcp_endpoints import handle_chat_history
        out = json.loads(handle_chat_history("", "pk_b"))
        assert out["count"] == 0
        assert "peer_a" in out["error"]


# ─── 加密复用说明验证 ─────────────────────────────────────


class TestEncryptionReuse:
    """验证 send_1v1/receive_1v1 复用 encrypt_channel/decrypt_channel."""

    def test_send_envelope_matches_encrypt_channel(
        self, fresh_manager, alice_keypair, bob_keypair
    ):
        """send_1v1 产出的 envelope 与 encrypt_channel 直接调用一致."""
        from laap.protocol.laap_com import encrypt_channel
        alice_priv, alice_pub = alice_keypair
        bob_pub = bob_keypair[1]
        msg = "reuse check"
        direct = encrypt_channel(msg, alice_priv, bob_pub)
        send_res = fresh_manager.send_1v1(
            sender_public_key=alice_pub,
            peer_public_key=bob_pub,
            message=msg,
            private_key=alice_priv,
        )
        # 同私钥对同消息签名确定性一致（Ed25519）
        assert send_res["envelope"]["signature"] == direct["signature"]
        assert send_res["envelope"]["public_key"] == direct["public_key"]
        assert send_res["envelope"]["peer_public_key"] == bob_pub
