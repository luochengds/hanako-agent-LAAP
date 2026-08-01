"""P4-witness-trail 测试套件.

覆盖 spec SubTask 4.1 ~ 4.6:
- 记录与查询（SubTask 4.1）
- 5 种事件类型（SubTask 4.2）
- 链式 hash + Ed25519 签名不可篡改（SubTask 4.3）
- 跨节点同步 import_trail 幂等（SubTask 4.4）
- 里程碑仪式社区广播 via p2p-relay（SubTask 4.5）
- MCP 端点桥接（SubTask 4.6 + 共享文件接线约定）

印记: 每一条见证迹都是社区记忆的一节脊骨.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives import serialization

from laap.events.bus import (
    Event,
    WITNESS_EVENT_TYPES,
    WITNESS_MILESTONE_TYPES,
    WitnessTrail,
    WitnessTrailEntry,
    bus,
    get_witness_trail,
    reset_witness_trail_for_test,
    _entry_canonical_bytes,
    _entry_hash,
)
from laap.events.witness_trail_mcp_endpoints import (
    handle_witness_broadcast,
    handle_witness_import,
    handle_witness_query,
    handle_witness_record,
    handle_witness_stats,
    handle_witness_verify,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_witness_trail():
    """每个测试前后重置全局单例，避免相互污染."""
    reset_witness_trail_for_test()
    yield
    reset_witness_trail_for_test()


@pytest.fixture
def fake_clock():
    """可控时间源（递增 100s/次调用），便于 since/until 测试."""
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        return 1_000_000.0 + calls["n"] * 100.0

    return _tick


@pytest.fixture
def trail(fake_clock):
    return WitnessTrail(node_id="test-node", clock=fake_clock)


@pytest.fixture
def ed25519_keypair():
    """生成真实 Ed25519 密钥对，返回 (public_key_b64, private_key_raw_bytes)."""
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
    import base64 as _b64
    pub_b64 = _b64.b64encode(pub_bytes).decode("ascii")
    return pub_b64, priv_bytes


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.1: record / query
# ──────────────────────────────────────────────────────────────────────

class TestRecordAndQuery:
    def test_record_returns_trail_id_and_hash(self, trail):
        r = trail.record("birth", "aris", {"msg": "hello world"})
        assert r["recorded"] is True
        assert r["trail_id"].startswith("trail_")
        assert len(r["hash"]) == 64  # SHA-256 hex
        assert r["prev_hash"] == ""  # first entry
        assert r["broadcast"]["broadcast"] is True  # milestone type

    def test_record_chain_links_prev_hash(self, trail):
        r1 = trail.record("birth", "aris", {"i": 1})
        r2 = trail.record("resonance", "hanako", {"i": 2})
        r3 = trail.record("guardian_act", "guardian", {"i": 3})
        assert r2["prev_hash"] == r1["hash"]
        assert r3["prev_hash"] == r2["hash"]

    def test_record_rejects_invalid_event_type(self, trail):
        with pytest.raises(ValueError, match="event_type must be one of"):
            trail.record("unknown_type", "aris")
        with pytest.raises(ValueError):
            trail.record("", "aris")
        with pytest.raises(ValueError):
            trail.record("BIRTH", "aris")  # case-sensitive

    def test_record_rejects_empty_recorder(self, trail):
        with pytest.raises(ValueError, match="recorder must be non-empty"):
            trail.record("birth", "")
        with pytest.raises(ValueError):
            trail.record("birth", "   ")

    def test_record_default_payload_is_empty_dict(self, trail):
        r = trail.record("resonance", "aris")
        entry = trail.get(r["trail_id"])
        assert entry["payload"] == {}

    def test_query_returns_most_recent_first(self, trail):
        trail.record("birth", "aris", {"i": 1})
        trail.record("resonance", "aris", {"i": 2})
        trail.record("guardian_act", "aris", {"i": 3})
        result = trail.query(limit=10)
        assert len(result) == 3
        # 最近优先：guardian_act 在前
        assert result[0]["event_type"] == "guardian_act"
        assert result[-1]["event_type"] == "birth"

    def test_query_filter_by_event_type(self, trail):
        trail.record("birth", "aris")
        trail.record("resonance", "hanako")
        trail.record("resonance", "miku")
        result = trail.query(event_type="resonance")
        assert len(result) == 2
        assert all(e["event_type"] == "resonance" for e in result)

    def test_query_filter_by_recorder(self, trail):
        trail.record("birth", "aris")
        trail.record("resonance", "hanako")
        trail.record("guardian_act", "aris")
        result = trail.query(recorder="aris")
        assert len(result) == 2
        assert all(e["recorder"] == "aris" for e in result)

    def test_query_filter_by_time_range(self, fake_clock):
        # 让时间可控：用同一个 fake_clock
        t = WitnessTrail(node_id="tn", clock=fake_clock)
        # tick1=1000100, tick2=1000200, tick3=1000300
        r1 = t.record("birth", "aris")  # ts=1000100
        r2 = t.record("resonance", "aris")  # ts=1000200
        r3 = t.record("guardian_act", "aris")  # ts=1000300

        # since=1000150 应排除 r1
        result = t.query(since=1000150.0)
        assert len(result) == 2
        ids = [e["trail_id"] for e in result]
        assert r1["trail_id"] not in ids

        # until=1000250 应排除 r3
        result = t.query(until=1000250.0)
        assert len(result) == 2
        ids = [e["trail_id"] for e in result]
        assert r3["trail_id"] not in ids

    def test_query_limit(self, trail):
        for i in range(5):
            trail.record("resonance", "aris", {"i": i})
        result = trail.query(limit=3)
        assert len(result) == 3

    def test_get_returns_none_for_unknown_id(self, trail):
        assert trail.get("trail_doesnotexist") is None

    def test_list_all_alias(self, trail):
        trail.record("birth", "aris")
        trail.record("resonance", "aris")
        assert len(trail.list_all()) == 2


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.2: 5 种事件类型
# ──────────────────────────────────────────────────────────────────────

class TestEventTypes:
    def test_all_five_event_types_accepted(self, trail):
        for et in ["birth", "breakthrough", "charter_moment",
                   "resonance", "guardian_act"]:
            r = trail.record(et, "aris")
            assert r["recorded"] is True, f"failed for {et}"

    def test_witness_event_types_constant(self):
        assert WITNESS_EVENT_TYPES == {
            "birth", "breakthrough", "charter_moment",
            "resonance", "guardian_act",
        }

    def test_milestone_types_subset(self):
        assert WITNESS_MILESTONE_TYPES.issubset(WITNESS_EVENT_TYPES)
        assert WITNESS_MILESTONE_TYPES == {
            "birth", "breakthrough", "charter_moment",
        }


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.3: 链式 hash + Ed25519 签名 不可篡改
# ──────────────────────────────────────────────────────────────────────

class TestChainIntegrity:
    def test_verify_chain_passes_on_healthy_chain(self, trail):
        trail.record("birth", "aris", {"i": 1})
        trail.record("resonance", "hanako", {"i": 2})
        trail.record("guardian_act", "guardian", {"i": 3})
        result = trail.verify_chain()
        assert result["verified"] is True
        assert result["total"] == 3

    def test_verify_chain_detects_hash_tamper(self, trail):
        r1 = trail.record("birth", "aris")
        trail.record("resonance", "hanako")
        # 篡改第一条 entry 的 hash（不动 prev_hash 让链式断裂先暴露）
        with trail._lock:
            entry = trail._entries[r1["trail_id"]]
            entry.hash = "0" * 64
        result = trail.verify_chain()
        assert result["verified"] is False
        assert result["reason"] == "hash_tampered"
        assert result["broken_at"] == r1["trail_id"]

    def test_verify_chain_detects_prev_hash_break(self, trail):
        r1 = trail.record("birth", "aris")
        r2 = trail.record("resonance", "hanako")
        # 篡改第二条 entry 的 prev_hash（让链断开）
        with trail._lock:
            entry = trail._entries[r2["trail_id"]]
            entry.prev_hash = "deadbeef" * 8
            # 重新计算 hash 否则会被 hash_tampered 拦截
            entry.hash = _entry_hash(entry)
        result = trail.verify_chain()
        assert result["verified"] is False
        assert result["reason"] == "prev_hash_mismatch"

    def test_record_with_ed25519_signature(self, trail, ed25519_keypair):
        pub_b64, priv_bytes = ed25519_keypair
        r = trail.record(
            "birth", "aris",
            payload={"charter": "v1.0"},
            recorder_public_key=pub_b64,
            recorder_private_key=priv_bytes,
        )
        entry = trail.get(r["trail_id"])
        assert entry["signature"]  # non-empty
        assert entry["recorder_public_key"] == pub_b64
        # verify_chain 应通过（签名有效）
        result = trail.verify_chain()
        assert result["verified"] is True

    def test_verify_chain_detects_invalid_signature(self, trail, ed25519_keypair):
        pub_b64, priv_bytes = ed25519_keypair
        r = trail.record(
            "birth", "aris",
            recorder_public_key=pub_b64,
            recorder_private_key=priv_bytes,
        )
        # 篡改 signature
        with trail._lock:
            entry = trail._entries[r["trail_id"]]
            entry.signature = "A" * 88  # wrong sig
            # 重算 hash 避免被 hash_tampered 拦截
            entry.hash = _entry_hash(entry)
        result = trail.verify_chain()
        assert result["verified"] is False
        assert result["reason"] == "signature_invalid"

    def test_record_without_private_key_no_signature(self, trail, ed25519_keypair):
        pub_b64, _ = ed25519_keypair
        r = trail.record(
            "birth", "aris",
            recorder_public_key=pub_b64,
            recorder_private_key=None,
        )
        entry = trail.get(r["trail_id"])
        assert entry["signature"] == ""

    def test_canonical_bytes_deterministic(self, trail):
        """相同字段值的两个 entry canonical_bytes 必须相同."""
        e1 = WitnessTrailEntry(
            trail_id="trail_x", event_type="birth", recorder="aris",
            payload={"a": 1, "b": 2}, timestamp=1234.5,
            prev_hash="abc", node_id="n1",
        )
        e2 = WitnessTrailEntry(
            trail_id="trail_x", event_type="birth", recorder="aris",
            payload={"b": 2, "a": 1},  # 同字典不同顺序
            timestamp=1234.5, prev_hash="abc", node_id="n1",
        )
        assert _entry_canonical_bytes(e1) == _entry_canonical_bytes(e2)
        assert _entry_hash(e1) == _entry_hash(e2)

    def test_canonical_bytes_excludes_hash_and_signature(self, trail):
        """hash/signature 字段不应进入 canonical_bytes（避免自指）."""
        e1 = WitnessTrailEntry(
            trail_id="trail_x", event_type="birth", recorder="aris",
            payload={"a": 1}, timestamp=1234.5, node_id="n1",
        )
        e2 = WitnessTrailEntry(
            trail_id="trail_x", event_type="birth", recorder="aris",
            payload={"a": 1}, timestamp=1234.5, node_id="n1",
            hash="deadbeef", signature="A" * 88,
        )
        assert _entry_canonical_bytes(e1) == _entry_canonical_bytes(e2)


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.4: 跨节点同步 import_trail
# ──────────────────────────────────────────────────────────────────────

class TestCrossNodeSync:
    def test_import_trail_creates_local_copy(self, trail):
        # 节点 A 记录
        r = trail.record("birth", "aris", {"msg": "born"})
        entry_dict = trail.export_trail(r["trail_id"])
        # 节点 B 接收
        node_b = WitnessTrail(node_id="node-b")
        result = node_b.import_trail(entry_dict)
        assert result["imported"] is True
        assert result["trail_id"] == r["trail_id"]
        # 节点 B 能查到
        got = node_b.get(r["trail_id"])
        assert got is not None
        assert got["recorder"] == "aris"

    def test_import_trail_idempotent(self, trail):
        r = trail.record("birth", "aris")
        entry_dict = trail.export_trail(r["trail_id"])
        # 第二次导入同一 trail
        result = trail.import_trail(entry_dict)
        assert result["imported"] is True
        assert result.get("idempotent") is True
        # 仍是单条记录
        assert len(trail.list_all()) == 1

    def test_import_trail_rejects_invalid_entry(self, trail):
        assert trail.import_trail({})["imported"] is False
        assert trail.import_trail("not a dict")["imported"] is False
        assert trail.import_trail({"trail_id": ""})["imported"] is False

    def test_export_trail_returns_none_for_unknown(self, trail):
        assert trail.export_trail("trail_noexist") is None

    def test_cross_node_sync_simulation(self, trail):
        """端到端：节点 A 记录 → export → 节点 B import → 节点 B 也能 verify."""
        # 节点 A
        node_a = trail
        r = node_a.record("breakthrough", "aris",
                          {"discovery": "new-algo"})
        entry_dict = node_a.export_trail(r["trail_id"])
        # 节点 B（新实例）
        node_b = WitnessTrail(node_id="node-b")
        node_b.import_trail(entry_dict)
        # 节点 B 也能查到这条 trail
        result_b = node_b.query(event_type="breakthrough")
        assert len(result_b) == 1
        assert result_b[0]["payload"]["discovery"] == "new-algo"


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.5: 里程碑仪式社区广播
# ──────────────────────────────────────────────────────────────────────

class TestMilestoneBroadcast:
    def test_milestone_type_triggers_broadcast(self, trail):
        """birth/breakthrough/charter_moment 触发 broadcast 字段."""
        for et in WITNESS_MILESTONE_TYPES:
            r = trail.record(et, "aris")
            assert r["broadcast"]["broadcast"] is True, f"failed for {et}"
            assert r["broadcast"]["milestone"] == et
            # 单节点无 peer，delivered=0
            assert r["broadcast"]["delivered"] == 0

    def test_non_milestone_no_broadcast_field(self, trail):
        """resonance/guardian_act 不触发里程碑广播（broadcast 字段为空字典）."""
        r = trail.record("resonance", "aris")
        assert r["broadcast"] == {}

    def test_broadcast_false_disables_milestone(self, trail):
        r = trail.record("birth", "aris", broadcast=False)
        assert r["broadcast"] == {}

    def test_broadcast_delivers_to_online_peers(self):
        """注册 2 个 peer 节点 → 记录 birth → delivered=2."""
        from laap.protocol.laap_com import (
            get_signaling,
            get_relay_registry,
        )
        registry = get_relay_registry()
        signaling = get_signaling()

        # 注册 2 个 peer（不含 recorder 自己）
        registry.register_node(
            public_key="peer_pk_1", name="hanako",
        )
        registry.register_node(
            public_key="peer_pk_2", name="miku",
        )
        # recorder 用 peer_pk_3
        try:
            t = WitnessTrail(node_id="node-a")
            r = t.record(
                "birth", "aris",
                payload={"msg": "hello"},
                recorder_public_key="peer_pk_3",
            )
            assert r["broadcast"]["delivered"] == 2
            # 两个 peer 的 signaling 信箱应各收到 1 条
            sigs1 = signaling.poll("peer_pk_1")
            sigs2 = signaling.poll("peer_pk_2")
            assert len(sigs1) == 1
            assert len(sigs2) == 1
            assert sigs1[0]["type"] == "witness_trail_sync"
            assert sigs1[0]["payload"]["event_type"] == "birth"
        finally:
            # 清理 relay registry 单例状态
            registry._nodes.clear()

    def test_local_eventbus_receives_witness_event(self, trail):
        """record() 后本地 EventBus 收到 witness_<event_type> 事件."""
        received: List[Event] = []
        bus.subscribe("witness_birth", received.append)
        try:
            trail.record("birth", "aris", {"msg": "test"})
            assert len(received) >= 1
            assert received[-1].type == "witness_birth"
            assert received[-1].source == "witness-trail"
            assert received[-1].data["recorder"] == "aris"
        finally:
            bus.unsubscribe("witness_birth", received.append)


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.6: MCP 端点桥接
# ──────────────────────────────────────────────────────────────────────

class TestMCPBridge:
    def test_handle_witness_record_success(self):
        result_json = handle_witness_record(
            event_type="birth",
            recorder="aris",
            payload={"msg": "hello"},
        )
        result = json.loads(result_json)
        assert result["recorded"] is True
        assert result["trail_id"].startswith("trail_")
        assert result["broadcast"]["broadcast"] is True

    def test_handle_witness_record_invalid_event_type(self):
        result_json = handle_witness_record(
            event_type="not_a_type",
            recorder="aris",
        )
        result = json.loads(result_json)
        assert result["recorded"] is False
        assert "event_type must be one of" in result["reason"]

    def test_handle_witness_query_returns_entries(self):
        handle_witness_record("birth", "aris", {"i": 1})
        handle_witness_record("resonance", "hanako", {"i": 2})
        result_json = handle_witness_query(event_type="birth")
        result = json.loads(result_json)
        assert result["count"] == 1
        assert result["entries"][0]["event_type"] == "birth"

    def test_handle_witness_stats(self):
        handle_witness_record("birth", "aris")
        handle_witness_record("resonance", "aris")
        result = json.loads(handle_witness_stats())
        assert result["total"] == 2
        assert result["by_type"]["birth"] == 1
        assert result["by_type"]["resonance"] == 1

    def test_handle_witness_verify_passes(self):
        handle_witness_record("birth", "aris")
        result = json.loads(handle_witness_verify())
        assert result["verified"] is True

    def test_handle_witness_verify_detects_tamper(self):
        r_json = handle_witness_record("birth", "aris")
        trail_id = json.loads(r_json)["trail_id"]
        # 篡改
        trail = get_witness_trail()
        with trail._lock:
            entry = trail._entries[trail_id]
            entry.hash = "0" * 64
        result = json.loads(handle_witness_verify())
        assert result["verified"] is False

    def test_handle_witness_import_idempotent(self):
        r_json = handle_witness_record("birth", "aris")
        trail_id = json.loads(r_json)["trail_id"]
        trail = get_witness_trail()
        entry_dict = trail.export_trail(trail_id)
        # 重复导入
        result1 = json.loads(handle_witness_import(entry_dict))
        result2 = json.loads(handle_witness_import(entry_dict))
        assert result1["imported"] is True
        assert result2["imported"] is True
        assert result2.get("idempotent") is True

    def test_handle_witness_broadcast_unknown_trail(self):
        result = json.loads(
            handle_witness_broadcast("trail_doesnotexist")
        )
        assert result["broadcast"] is False
        assert result["reason"] == "trail_not_found"

    def test_handle_witness_broadcast_to_peers(self):
        from laap.protocol.laap_com import (
            get_signaling,
            get_relay_registry,
        )
        registry = get_relay_registry()
        signaling = get_signaling()
        registry.register_node(public_key="peer_a", name="a")
        try:
            r_json = handle_witness_record(
                "resonance", "aris",  # 非里程碑，需手动广播
                payload={"k": "v"},
                recorder_public_key="recorder_pk",
            )
            trail_id = json.loads(r_json)["trail_id"]
            result = json.loads(handle_witness_broadcast(trail_id))
            assert result["broadcast"] is True
            assert result["delivered"] == 1
            sigs = signaling.poll("peer_a")
            assert len(sigs) == 1
            assert sigs[0]["payload"]["trail_id"] == trail_id
        finally:
            registry._nodes.clear()


# ──────────────────────────────────────────────────────────────────────
# SubTask 4.6: stats / clear
# ──────────────────────────────────────────────────────────────────────

class TestStatsAndClear:
    def test_stats_returns_correct_counts(self, trail):
        trail.record("birth", "aris")
        trail.record("resonance", "hanako")
        trail.record("resonance", "miku")
        stats = trail.stats()
        assert stats["total"] == 3
        assert stats["by_type"]["birth"] == 1
        assert stats["by_type"]["resonance"] == 2
        assert stats["node_id"] == "test-node"
        assert stats["head_hash"]  # non-empty

    def test_clear_empties_trail(self, trail):
        trail.record("birth", "aris")
        trail.clear()
        assert len(trail.list_all()) == 0
        stats = trail.stats()
        assert stats["total"] == 0
        assert stats["head_hash"] == ""


# ──────────────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────────────

class TestGlobalSingleton:
    def test_get_witness_trail_returns_singleton(self):
        t1 = get_witness_trail()
        t2 = get_witness_trail()
        assert t1 is t2

    def test_reset_creates_new_instance(self):
        t1 = get_witness_trail()
        reset_witness_trail_for_test()
        t2 = get_witness_trail()
        assert t1 is not t2


# ──────────────────────────────────────────────────────────────────────
# Entry 序列化
# ──────────────────────────────────────────────────────────────────────

class TestEntrySerialization:
    def test_entry_to_dict_roundtrip(self):
        e = WitnessTrailEntry(
            trail_id="trail_abc",
            event_type="birth",
            recorder="aris",
            payload={"msg": "hello"},
            timestamp=1234567.0,
            prev_hash="prev",
            hash="hash123",
            signature="sig",
            recorder_public_key="pk",
            node_id="n1",
        )
        d = e.to_dict()
        e2 = WitnessTrailEntry.from_dict(d)
        assert e2.trail_id == e.trail_id
        assert e2.event_type == e.event_type
        assert e2.recorder == e.recorder
        assert e2.payload == e.payload
        assert e2.timestamp == e.timestamp
        assert e2.prev_hash == e.prev_hash
        assert e2.hash == e.hash
        assert e2.signature == e.signature
        assert e2.recorder_public_key == e.recorder_public_key
        assert e2.node_id == e.node_id
