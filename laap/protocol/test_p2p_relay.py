"""测试 — P2P 中继 + WebRTC 信令 + 加密信道 (P3-p2p-relay)

覆盖（与 tasks.md L95-101 SubTask 3.2-3.6 对齐）：
- ``RelayRegistry.register_node`` 注册 + 信息更新 + agent_online 事件
- ``RelayRegistry.heartbeat`` 心跳保活 + 未注册节点拒绝
- ``RelayRegistry.discover`` 在线列表 + ``_sweep_stale`` 超时标记离线
  + ``agent_offline`` 事件触发
- ``RelayRegistry.mark_offline`` 手动离线（spec SubTask 3.2）
- ``P2PSignaling`` post_offer/answer/ice + poll 信令交换 stub
- ``encrypt_channel`` / ``decrypt_channel`` 加密信道闭环 + 伪造签名拒绝
- MCP 工具注册（FakeMCP 上注册 6 工具，relay_encrypt 仅 sidecar）
- sidecar 桥接 helper（handle_relay_register / heartbeat / discover /
  offline / signal / encrypt / decrypt）
- mock clock 注入测试（spec L427 硬约束：禁用 asyncio）

运行方式：
    python -m pytest laap/protocol/test_p2p_relay.py -v -p no:quadrants
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from typing import List

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
def mock_clock():
    """可控时间源：返回闭包，初始 t=1000.0，每次调用自增 1s.

    测试通过 ``c.advance(delta)`` 推进时间，避免依赖 ``time.sleep``.
    """
    state = {"now": 1000.0}

    def now_fn() -> float:
        return state["now"]

    def advance(delta: float) -> None:
        state["now"] += delta

    now_fn.advance = advance  # type: ignore[attr-defined]
    return now_fn


@pytest.fixture
def fresh_registry(mock_clock):
    """提供空 RelayRegistry + mock clock，避免全局状态污染."""
    from laap.protocol.laap_com import RelayRegistry
    return RelayRegistry(
        clock=mock_clock,
        heartbeat_interval=30,
        offline_timeout=90,
    )


@pytest.fixture
def fresh_signaling(mock_clock):
    """提供空 P2PSignaling + mock clock."""
    from laap.protocol.laap_com import P2PSignaling
    return P2PSignaling(clock=mock_clock)


@pytest.fixture(autouse=True)
def reset_global_singletons():
    """每个测试前重置全局 RelayRegistry / P2PSignaling 单例.

    防止跨测试污染（spec L427: 全局单例禁止状态泄漏）.
    """
    import laap.protocol.laap_com as com_mod
    com_mod._relay_registry = None
    com_mod._signaling = None
    yield
    com_mod._relay_registry = None
    com_mod._signaling = None


@pytest.fixture
def capture_events():
    """订阅 EventBus 的 agent_online / agent_offline 事件.

    返回 ``(events_list, unsubscribe_fn)``.
    """
    from laap.events.bus import bus, Event
    events: List[Event] = []

    def capture_handler(event: Event) -> None:
        events.append(event)

    bus.subscribe("agent_online", capture_handler)
    bus.subscribe("agent_offline", capture_handler)
    yield events
    bus.unsubscribe("agent_online", capture_handler)
    bus.unsubscribe("agent_offline", capture_handler)


# ─── 1. RelayRegistry.register_node (SubTask 3.2) ────────────────


def test_register_node_basic(fresh_registry, real_keypair):
    """register_node 接受合法字段并返回节点信息 dict."""
    _, pub_b64 = real_keypair
    node = fresh_registry.register_node(
        public_key=pub_b64,
        name="aris",
        address="127.0.0.1:9000",
        capabilities=["code-review", "writing"],
        color="#7C9EFF",
    )
    assert node["public_key"] == pub_b64
    assert node["name"] == "aris"
    assert node["address"] == "127.0.0.1:9000"
    assert node["capabilities"] == ["code-review", "writing"]
    assert node["color"] == "#7C9EFF"
    assert node["online"] is True
    assert node["last_heartbeat"] > 0
    assert node["registered_at"] > 0
    assert fresh_registry.count() == 1


def test_register_node_emits_agent_online_event(
    fresh_registry, real_keypair, capture_events
):
    """首次注册触发 agent_online 事件（spec SubTask 3.5 bubble-field）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    online_events = [e for e in capture_events if e.type == "agent_online"]
    assert len(online_events) == 1
    assert online_events[0].data["public_key"] == pub_b64
    assert online_events[0].data["name"] == "aris"
    assert online_events[0].source == "p2p-relay"


def test_register_node_idempotent_update(fresh_registry, real_keypair):
    """同一 public_key 二次调用视为更新（不报错）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(
        public_key=pub_b64, name="aris", color="#FF0000",
    )
    # 更新 name + color
    node = fresh_registry.register_node(
        public_key=pub_b64, name="aris-v2", color="#00FF00",
        capabilities=["chat"],
    )
    assert node["name"] == "aris-v2"
    assert node["color"] == "#00FF00"
    assert node["capabilities"] == ["chat"]
    # 仍然只有一个节点
    assert fresh_registry.count() == 1


def test_register_node_invalid_args(fresh_registry):
    """空 public_key / name → ValueError."""
    with pytest.raises(ValueError, match="public_key"):
        fresh_registry.register_node(public_key="", name="aris")
    with pytest.raises(ValueError, match="name"):
        fresh_registry.register_node(public_key="pk-1", name="")
    with pytest.raises(ValueError, match="public_key"):
        fresh_registry.register_node(public_key=None, name="aris")  # type: ignore[arg-type]


# ─── 2. RelayRegistry.heartbeat (SubTask 3.2/3.5) ──────────────


def test_heartbeat_refreshes_online_status(fresh_registry, real_keypair):
    """heartbeat 刷新 last_heartbeat + 标记 online=True."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    # 推进时间后心跳
    result = fresh_registry.heartbeat(pub_b64)
    assert result["ok"] is True
    assert result["online"] is True
    assert result["last_heartbeat"] > 0
    assert result["next_heartbeat_due"] == result["last_heartbeat"] + 30


def test_heartbeat_revive_emits_agent_online(
    fresh_registry, real_keypair, mock_clock, capture_events
):
    """离线节点心跳恢复 → 触发 agent_online（reason=heartbeat_revive）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    fresh_registry.mark_offline(pub_b64, reason="manual")
    capture_events.clear()
    # 心跳恢复
    result = fresh_registry.heartbeat(pub_b64)
    assert result["ok"] is True
    online_events = [e for e in capture_events if e.type == "agent_online"]
    assert len(online_events) == 1
    assert online_events[0].data.get("reason") == "heartbeat_revive"


def test_heartbeat_unregistered_node_rejected(fresh_registry):
    """未注册节点 heartbeat → 返回 ok=False."""
    result = fresh_registry.heartbeat("nonexistent-pk")
    assert result["ok"] is False
    assert "not registered" in result["error"]


def test_heartbeat_empty_public_key_rejected(fresh_registry):
    """空 public_key → ok=False."""
    result = fresh_registry.heartbeat("")
    assert result["ok"] is False
    assert "public_key" in result["error"]


# ─── 3. RelayRegistry.discover + _sweep_stale (SubTask 3.2/3.5) ──


def test_discover_returns_online_nodes(fresh_registry, real_keypair):
    """discover 返回所有在线节点（先 sweep_stale）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    nodes = fresh_registry.discover()
    assert len(nodes) == 1
    assert nodes[0]["name"] == "aris"
    assert nodes[0]["online"] is True


def test_discover_sweep_stale_marks_timeout_offline(
    fresh_registry, real_keypair, mock_clock, capture_events
):
    """spec SubTask 3.5: 90s 超时 → discover 时自动标记离线.

    场景：
      1. 注册节点 + 心跳（t=1000）
      2. 时间推进 91s（>90s 超时）
      3. discover 触发 _sweep_stale → 节点被标记离线
      4. agent_offline 事件触发（reason=heartbeat_timeout）
      5. 在线列表为空
    """
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    capture_events.clear()
    # 推进 91s（>90s 超时阈值）
    mock_clock.advance(91)
    nodes = fresh_registry.discover()
    assert len(nodes) == 0  # 在线列表为空
    offline_events = [e for e in capture_events if e.type == "agent_offline"]
    assert len(offline_events) == 1
    assert offline_events[0].data["reason"] == "heartbeat_timeout"
    # include_offline=True 仍能看到该节点
    all_nodes = fresh_registry.discover(include_offline=True)
    assert len(all_nodes) == 1
    assert all_nodes[0]["online"] is False


def test_discover_within_timeout_stays_online(
    fresh_registry, real_keypair, mock_clock
):
    """心跳 89s 后仍在线（<90s 超时阈值）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    mock_clock.advance(89)
    nodes = fresh_registry.discover()
    assert len(nodes) == 1
    assert nodes[0]["online"] is True


def test_discover_heartbeat_resets_timeout(
    fresh_registry, real_keypair, mock_clock
):
    """心跳后超时计时器重置：心跳 80s + 推进 30s = 总 110s 仍在线."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    mock_clock.advance(80)
    fresh_registry.heartbeat(pub_b64)  # 重置心跳
    mock_clock.advance(30)  # 总推进 110s，但最近心跳后只过 30s
    nodes = fresh_registry.discover()
    assert len(nodes) == 1
    assert nodes[0]["online"] is True


def test_discover_empty_registry(fresh_registry):
    """空 registry → discover 返回空列表."""
    assert fresh_registry.discover() == []


# ─── 4. RelayRegistry.mark_offline (SubTask 3.2) ────────────────


def test_mark_offline_triggers_event(
    fresh_registry, real_keypair, capture_events
):
    """mark_offline 触发 agent_offline 事件（泡泡变暗）."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    capture_events.clear()
    result = fresh_registry.mark_offline(pub_b64, reason="manual")
    assert result["ok"] is True
    assert result["online"] is False
    assert result["reason"] == "manual"
    offline_events = [e for e in capture_events if e.type == "agent_offline"]
    assert len(offline_events) == 1
    assert offline_events[0].data["public_key"] == pub_b64
    assert offline_events[0].data["reason"] == "manual"


def test_mark_offline_unregistered_node(fresh_registry):
    """未注册节点 mark_offline → ok=False."""
    result = fresh_registry.mark_offline("nonexistent-pk")
    assert result["ok"] is False
    assert "not registered" in result["error"]


def test_mark_offline_excludes_from_discover(
    fresh_registry, real_keypair
):
    """离线节点不出现在 discover 默认列表中."""
    _, pub_b64 = real_keypair
    fresh_registry.register_node(public_key=pub_b64, name="aris")
    fresh_registry.mark_offline(pub_b64)
    assert fresh_registry.discover() == []
    assert len(fresh_registry.discover(include_offline=True)) == 1


# ─── 5. P2PSignaling post_offer/answer/ice + poll (SubTask 3.3) ─


def test_signal_post_offer_returns_signal_id(
    fresh_signaling, real_keypair
):
    """post_offer 返回 signal_id，poll 能取回."""
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    sdp = {"type": "offer", "sdp": "v=0\r\no=-"}
    signal_id = fresh_signaling.post_offer(pub_a, pub_b, sdp)
    assert signal_id.startswith("sig_")
    signals = fresh_signaling.poll(pub_b)
    assert len(signals) == 1
    assert signals[0]["signal_id"] == signal_id
    assert signals[0]["from"] == pub_a
    assert signals[0]["to"] == pub_b
    assert signals[0]["type"] == "offer"
    assert signals[0]["payload"] == sdp


def test_signal_post_answer_and_ice(fresh_signaling, real_keypair):
    """post_answer / post_ice 也能正确投递."""
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    fresh_signaling.post_answer(pub_a, pub_b, {"type": "answer"})
    fresh_signaling.post_ice(pub_a, pub_b, {"candidate": "ice-1"})
    signals = fresh_signaling.poll(pub_b)
    assert len(signals) == 2
    types = [s["type"] for s in signals]
    assert "answer" in types
    assert "ice" in types


def test_signal_poll_clears_queue(fresh_signaling, real_keypair):
    """poll 后清空接收方队列（一次性消费）."""
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    fresh_signaling.post_offer(pub_a, pub_b, "sdp-stub")
    first_poll = fresh_signaling.poll(pub_b)
    assert len(first_poll) == 1
    second_poll = fresh_signaling.poll(pub_b)
    assert second_poll == []


def test_signal_poll_empty_returns_empty_list(fresh_signaling, real_keypair):
    """无信令时 poll 返回空列表（不抛异常）."""
    _, pub_b = real_keypair
    assert fresh_signaling.poll(pub_b) == []
    assert fresh_signaling.poll("") == []
    assert fresh_signaling.poll(None) == []  # type: ignore[arg-type]


def test_signal_multi_recipient_isolation(fresh_signaling):
    """多接收方信令互不干扰.

    注意：``real_keypair`` fixture 是 function-scoped，多次引用返回同一
    密钥对；本测试需要在测试内部直接生成三把不同密钥.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    def _gen() -> str:
        sk = Ed25519PrivateKey.generate()
        pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(pub).decode("ascii")

    pub_a = _gen()
    pub_b = _gen()
    pub_c = _gen()
    assert pub_a != pub_b != pub_c != pub_a
    fresh_signaling.post_offer(pub_a, pub_b, "for-b")
    fresh_signaling.post_offer(pub_a, pub_c, "for-c")
    assert len(fresh_signaling.poll(pub_b)) == 1
    assert len(fresh_signaling.poll(pub_c)) == 1
    # poll B 不影响 C 的队列（已消费）
    assert fresh_signaling.poll(pub_b) == []


# ─── 6. encrypt_channel / decrypt_channel (SubTask 3.4) ────────


def test_encrypt_channel_returns_four_fields(real_keypair):
    """encrypt_channel 返回 {message, signature, public_key, peer_public_key}."""
    from laap.protocol.laap_com import encrypt_channel
    priv_bytes, pub_b64 = real_keypair
    envelope = encrypt_channel(
        message="hello butter",
        private_key=priv_bytes,
        peer_public_key="peer-pub-b64-stub",
    )
    assert set(envelope.keys()) == {
        "message", "signature", "public_key", "peer_public_key",
    }
    assert envelope["message"] == "hello butter"
    assert envelope["public_key"] == pub_b64  # 发送者公钥（从私钥派生）
    assert envelope["peer_public_key"] == "peer-pub-b64-stub"
    # Ed25519 签名 = 64 字节 → base64 长度 = 88
    assert len(base64.b64decode(envelope["signature"])) == 64


def test_decrypt_channel_valid_signature(real_keypair):
    """encrypt + decrypt 闭环：验证通过返回 message + sender_public_key."""
    from laap.protocol.laap_com import encrypt_channel, decrypt_channel
    priv_bytes, pub_b64 = real_keypair
    envelope = encrypt_channel(
        message="hello butter",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    )
    result = decrypt_channel(envelope)
    assert result["verified"] is True
    assert result["message"] == "hello butter"
    assert result["sender_public_key"] == pub_b64


def test_decrypt_channel_forged_signature_rejected(real_keypair):
    """伪造签名（篡改 message）→ verified=False（spec L280 跨节点场景）."""
    from laap.protocol.laap_com import encrypt_channel, decrypt_channel
    priv_bytes, _ = real_keypair
    envelope = encrypt_channel(
        message="original",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    )
    # 篡改 message 但保留 signature → 验证失败
    forged = dict(envelope)
    forged["message"] = "tampered"
    result = decrypt_channel(forged)
    assert result["verified"] is False
    assert "error" in result


def test_decrypt_channel_forged_signature_zero_bytes(real_keypair):
    """签名替换为随机 64 字节 → verified=False."""
    from laap.protocol.laap_com import encrypt_channel, decrypt_channel
    priv_bytes, _ = real_keypair
    envelope = encrypt_channel(
        message="original",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    )
    forged = dict(envelope)
    forged["signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    result = decrypt_channel(forged)
    assert result["verified"] is False


def test_decrypt_channel_wrong_key_rejected(real_keypair):
    """签名有效但用错误公钥验证 → False."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from laap.protocol.laap_com import encrypt_channel, decrypt_channel
    priv_a, _ = real_keypair
    # 另一把 key
    sk_b = Ed25519PrivateKey.generate()
    pub_b_bytes = sk_b.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b = base64.b64encode(pub_b_bytes).decode("ascii")

    envelope = encrypt_channel(
        message="signed by A",
        private_key=priv_a,
        peer_public_key="peer-stub",
    )
    # 用 B 的公钥验证 A 的签名 → False
    mismatched = dict(envelope)
    mismatched["public_key"] = pub_b
    result = decrypt_channel(mismatched)
    assert result["verified"] is False


def test_decrypt_channel_malformed_envelope():
    """decrypt_channel 对缺字段 / 类型错 / 非 dict 一律返回 verified=False."""
    from laap.protocol.laap_com import decrypt_channel
    assert decrypt_channel({})["verified"] is False
    assert decrypt_channel({"message": "x"})["verified"] is False
    assert decrypt_channel("not-a-dict")["verified"] is False  # type: ignore[arg-type]
    assert decrypt_channel(None)["verified"] is False  # type: ignore[arg-type]
    assert decrypt_channel({
        "message": "x",
        "signature": "not-base64!!",
        "public_key": "also-not-base64!!",
    })["verified"] is False


def test_encrypt_channel_invalid_private_key(real_keypair):
    """encrypt_channel 对非法私钥抛 TypeError/ValueError."""
    from laap.protocol.laap_com import encrypt_channel
    with pytest.raises(TypeError):
        encrypt_channel("msg", "not-bytes", "peer")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encrypt_channel("msg", b"\x00" * 31, "peer")  # 长度不对


# ─── 7. sidecar 桥接 helper ──────────────────────────────────


def test_handle_relay_register_success(real_keypair):
    """handle_relay_register 返回 registered=true."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_register,
    )
    _, pub_b64 = real_keypair
    out = handle_relay_register(
        public_key=pub_b64,
        name="aris",
        address="127.0.0.1:9000",
        capabilities=["code-review"],
        color="#7C9EFF",
    )
    payload = json.loads(out)
    assert payload["registered"] is True
    assert payload["node"]["name"] == "aris"
    assert payload["node"]["public_key"] == pub_b64
    assert payload["node"]["color"] == "#7C9EFF"


def test_handle_relay_register_invalid_args():
    """handle_relay_register 对空 public_key 返回 registered=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_register,
    )
    out = handle_relay_register(public_key="", name="aris")
    payload = json.loads(out)
    assert payload["registered"] is False
    assert "public_key" in payload["error"]


def test_handle_relay_heartbeat_after_register(real_keypair):
    """注册后 heartbeat 返回 ok=true."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_register,
        handle_relay_heartbeat,
    )
    _, pub_b64 = real_keypair
    handle_relay_register(public_key=pub_b64, name="aris")
    out = handle_relay_heartbeat(pub_b64)
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["online"] is True
    assert payload["last_heartbeat"] > 0
    assert payload["next_heartbeat_due"] == payload["last_heartbeat"] + 30


def test_handle_relay_heartbeat_unregistered():
    """未注册节点 heartbeat 返回 ok=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_heartbeat,
    )
    out = handle_relay_heartbeat("nonexistent-pk")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "not registered" in payload["error"]


def test_handle_relay_discover_returns_nodes(real_keypair):
    """注册后 discover 返回在线节点列表."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_register,
        handle_relay_discover,
    )
    _, pub_b64 = real_keypair
    handle_relay_register(public_key=pub_b64, name="aris")
    out = handle_relay_discover()
    payload = json.loads(out)
    assert payload["count"] == 1
    assert payload["nodes"][0]["name"] == "aris"


def test_handle_relay_offline_after_register(real_keypair):
    """注册后 mark_offline 返回 ok=true 且 online=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_register,
        handle_relay_offline,
        handle_relay_discover,
    )
    _, pub_b64 = real_keypair
    handle_relay_register(public_key=pub_b64, name="aris")
    out = handle_relay_offline(pub_b64, reason="manual")
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["online"] is False
    assert payload["reason"] == "manual"
    # discover 默认不再返回该节点
    discover_payload = json.loads(handle_relay_discover())
    assert discover_payload["count"] == 0


def test_handle_relay_signal_offer_and_poll(real_keypair):
    """handle_relay_signal post offer + poll 闭环."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_signal,
    )
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    # post offer
    out_post = handle_relay_signal(
        action="offer",
        from_pk=pub_a,
        to_pk=pub_b,
        payload={"type": "offer", "sdp": "stub"},
    )
    post_payload = json.loads(out_post)
    assert post_payload["posted"] is True
    assert post_payload["signal_id"].startswith("sig_")
    # poll
    out_poll = handle_relay_signal(action="poll", to_pk=pub_b)
    poll_payload = json.loads(out_poll)
    assert poll_payload["count"] == 1
    assert poll_payload["signals"][0]["type"] == "offer"
    assert poll_payload["signals"][0]["from"] == pub_a


def test_handle_relay_signal_unknown_action(real_keypair):
    """未知 action 返回 posted=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_signal,
    )
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    out = handle_relay_signal(
        action="bogus",
        from_pk=pub_a,
        to_pk=pub_b,
        payload="x",
    )
    payload = json.loads(out)
    assert payload["posted"] is False
    assert "unknown action" in payload["error"]


def test_handle_relay_signal_missing_args():
    """缺 from_pk / to_pk 返回 posted=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_signal,
    )
    # poll 缺 to_pk
    out1 = handle_relay_signal(action="poll")
    assert json.loads(out1)["count"] == 0
    # post 缺 from_pk
    out2 = handle_relay_signal(action="offer", to_pk="pk-b")
    payload2 = json.loads(out2)
    assert payload2["posted"] is False
    assert "from_pk" in payload2["error"]
    # post 缺 to_pk
    out3 = handle_relay_signal(action="offer", from_pk="pk-a")
    payload3 = json.loads(out3)
    assert payload3["posted"] is False
    assert "to_pk" in payload3["error"]


def test_handle_relay_encrypt_decrypt_round_trip(real_keypair):
    """handle_relay_encrypt + handle_relay_decrypt 闭环."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_encrypt,
        handle_relay_decrypt,
    )
    priv_bytes, pub_b64 = real_keypair
    enc_out = handle_relay_encrypt(
        message="hello butter",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    )
    envelope = json.loads(enc_out)
    assert "signature" in envelope
    dec_out = handle_relay_decrypt(envelope)
    payload = json.loads(dec_out)
    assert payload["verified"] is True
    assert payload["message"] == "hello butter"
    assert payload["sender_public_key"] == pub_b64


def test_handle_relay_decrypt_forged(real_keypair):
    """handle_relay_decrypt 对伪造签名返回 verified=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        handle_relay_encrypt,
        handle_relay_decrypt,
    )
    priv_bytes, _ = real_keypair
    envelope = json.loads(handle_relay_encrypt(
        message="original",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    ))
    envelope["message"] = "tampered"
    out = handle_relay_decrypt(envelope)
    assert json.loads(out)["verified"] is False


# ─── 8. MCP 工具注册 ─────────────────────────────────────────


class _FakeMCP:
    """最小 FastMCP 替身：收集 @tool() 装饰的协程函数."""

    def __init__(self):
        self.tools: dict = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_register_p2p_relay_tools_registers_six_tools():
    """register_p2p_relay_tools 在 FakeMCP 上注册 6 工具
    （relay_encrypt 不暴露为 MCP 工具，spec L435 私钥永不离开 sidecar）.
    """
    from laap.protocol.p2p_relay_mcp_endpoints import (
        register_p2p_relay_tools,
    )
    mcp = _FakeMCP()
    register_p2p_relay_tools(mcp)
    assert "relay_register" in mcp.tools
    assert "relay_heartbeat" in mcp.tools
    assert "relay_discover" in mcp.tools
    assert "relay_offline" in mcp.tools
    assert "relay_signal" in mcp.tools
    assert "relay_decrypt" in mcp.tools
    # relay_encrypt 不应作为 MCP 工具暴露
    assert "relay_encrypt" not in mcp.tools


def test_mcp_relay_register_tool_round_trip(real_keypair):
    """MCP relay_register 工具端到端：注册 → discover 命中."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        register_p2p_relay_tools,
        handle_relay_discover,
    )
    _, pub_b64 = real_keypair
    mcp = _FakeMCP()
    register_p2p_relay_tools(mcp)
    out = asyncio.run(mcp.tools["relay_register"](
        public_key=pub_b64,
        name="aris",
        address="127.0.0.1:9000",
        capabilities=["code-review"],
        color="#7C9EFF",
    ))
    payload = json.loads(out)
    assert payload["registered"] is True
    # discover 能命中
    discover_out = json.loads(handle_relay_discover())
    assert discover_out["count"] == 1
    assert discover_out["nodes"][0]["name"] == "aris"


def test_mcp_relay_signal_tool_round_trip(real_keypair):
    """MCP relay_signal 工具端到端：post offer → poll 取回."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        register_p2p_relay_tools,
    )
    _, pub_a = real_keypair
    _, pub_b = real_keypair
    mcp = _FakeMCP()
    register_p2p_relay_tools(mcp)
    # post offer
    post_out = asyncio.run(mcp.tools["relay_signal"](
        action="offer",
        from_pk=pub_a,
        to_pk=pub_b,
        payload="sdp-stub",
    ))
    post_payload = json.loads(post_out)
    assert post_payload["posted"] is True
    # poll
    poll_out = asyncio.run(mcp.tools["relay_signal"](
        action="poll",
        to_pk=pub_b,
    ))
    poll_payload = json.loads(poll_out)
    assert poll_payload["count"] == 1
    assert poll_payload["signals"][0]["type"] == "offer"


def test_mcp_relay_decrypt_tool_real_signature(real_keypair):
    """MCP relay_decrypt 工具端到端：真实签名 → verified=true."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        register_p2p_relay_tools,
        handle_relay_encrypt,
    )
    priv_bytes, _ = real_keypair
    envelope = json.loads(handle_relay_encrypt(
        message="mcp decrypt test",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    ))
    mcp = _FakeMCP()
    register_p2p_relay_tools(mcp)
    out = asyncio.run(mcp.tools["relay_decrypt"](signed_message=envelope))
    payload = json.loads(out)
    assert payload["verified"] is True
    assert payload["message"] == "mcp decrypt test"


def test_mcp_relay_decrypt_tool_forged(real_keypair):
    """MCP relay_decrypt 工具：伪造签名 → verified=false."""
    from laap.protocol.p2p_relay_mcp_endpoints import (
        register_p2p_relay_tools,
        handle_relay_encrypt,
    )
    priv_bytes, _ = real_keypair
    envelope = json.loads(handle_relay_encrypt(
        message="orig",
        private_key=priv_bytes,
        peer_public_key="peer-stub",
    ))
    envelope["message"] = "tampered"
    mcp = _FakeMCP()
    register_p2p_relay_tools(mcp)
    out = asyncio.run(mcp.tools["relay_decrypt"](signed_message=envelope))
    assert json.loads(out)["verified"] is False


# ─── 9. 全局单例 + clock 注入 ─────────────────────────────────


def test_get_relay_registry_singleton():
    """get_relay_registry 返回全局单例."""
    from laap.protocol.laap_com import get_relay_registry
    r1 = get_relay_registry()
    r2 = get_relay_registry()
    assert r1 is r2


def test_get_signaling_singleton():
    """get_signaling 返回全局单例."""
    from laap.protocol.laap_com import get_signaling
    s1 = get_signaling()
    s2 = get_signaling()
    assert s1 is s2


def test_reset_relay_registry_for_test_injects_clock(mock_clock):
    """reset_relay_registry_for_test 注入 mock clock."""
    from laap.protocol.laap_com import (
        reset_relay_registry_for_test,
        get_relay_registry,
    )
    registry = reset_relay_registry_for_test(clock=mock_clock)
    assert registry is get_relay_registry()
    # 注册节点 + 推进时间 + sweep 应使用 mock_clock
    registry.register_node(public_key="pk-stub", name="aris")
    mock_clock.advance(91)
    assert registry.discover() == []  # 超时被标记离线


def test_reset_signaling_for_test():
    """reset_signaling_for_test 重置全局 signaling."""
    from laap.protocol.laap_com import (
        reset_signaling_for_test,
        get_signaling,
    )
    signaling = reset_signaling_for_test()
    assert signaling is get_signaling()


# ─── 10. /agents/online 兼容性（P2-bubble-field 向后兼容） ──────


def test_relay_registry_empty_discover_returns_empty_list():
    """空 RelayRegistry.discover() 返回空列表（不抛异常）.

    sidecar /agents/online 优先调 RelayRegistry.discover()；
    若空则回退原 logic（spec: 向后兼容 P2-bubble-field）.
    """
    from laap.protocol.laap_com import RelayRegistry
    registry = RelayRegistry()
    assert registry.discover() == []
    assert registry.count() == 0


def test_relay_node_info_to_dict_serializable(real_keypair):
    """RelayNodeInfo.to_dict() 输出 JSON 可序列化."""
    import json as _json
    from laap.protocol.laap_com import RelayNodeInfo
    _, pub_b64 = real_keypair
    node = RelayNodeInfo(
        public_key=pub_b64,
        name="aris",
        address="127.0.0.1:9000",
        capabilities=["code-review"],
        color="#7C9EFF",
        online=True,
        last_heartbeat=1000.0,
        registered_at=1000.0,
    )
    d = node.to_dict()
    # 必须可 JSON 序列化（sidecar 直接 json.dumps）
    serialized = _json.dumps(d, ensure_ascii=False)
    parsed = _json.loads(serialized)
    assert parsed["name"] == "aris"
    assert parsed["online"] is True
