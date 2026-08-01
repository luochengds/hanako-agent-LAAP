"""LAAP — 宪章守护者注册表测试 (P4-charter-guardian)

================================================================
  测试 GuardianRegistry 白名单 + 4 action + witness-trail 沉淀
  + stats + 事件发布 + MCP 桥接
================================================================

覆盖 spec SubTask 5 (test_guardian) 的全部场景：

* 白名单管理：``register_guardian`` / ``unregister_guardian`` /
  ``is_guardian`` / ``list_guardians`` + 空/重复/未注册场景
* ``guardian_act`` 4 种 action：``suspend`` / ``warn`` / ``expel`` /
  ``restore`` 各自更新 ``_target_status`` + 写入 ``WitnessTrail``
* ``guardian_act`` 失败路径：``unauthorized``（不在白名单）+
  ``invalid_action`` + empty target/reason/guardian_public_key
* ``WitnessTrail`` 沉淀：每次行使返回 ``trail_id`` + ``hash``，
  ``witness.query('guardian_act')`` 可查到对应记录 + 链式 hash 完整
  + 私钥签名可选
* 状态跟踪：``get_target_status`` 默认 ``active`` + 行使后更新
* 事件发布：``guardian_act`` 事件经 ``events.bus.publish_simple``
  发布，订阅者可收到
* 查询：``list_acts`` 按 target/action 过滤 + limit + 倒序
* 统计：``stats`` 返回 ``total_acts`` / ``by_action`` /
  ``by_target_status`` / ``active_guardians`` /
  ``recent_abuse_events`` / ``targets_count``
* MCP 桥接：``handle_guardian_*`` 返回 JSON 字符串
* 端到端：注册守护者 → suspend X → list_acts → stats →
  witness_trail 验证 → 事件订阅者收到
"""
from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from typing import Any, Dict, List, Tuple

# 确保 laap 包可导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_LAAP_ROOT = os.path.dirname(_HERE)
if _LAAP_ROOT not in sys.path:
    sys.path.insert(0, _LAAP_ROOT)

from laap.colony.protocol import (  # noqa: E402
    GuardianRegistry,
    get_guardian_registry,
    reset_guardian_registry_for_test,
)
from laap.colony.guardian_mcp_endpoints import (  # noqa: E402
    handle_guardian_act,
    handle_guardian_get_target_status,
    handle_guardian_list,
    handle_guardian_register,
    handle_guardian_stats,
    register_guardian_tools,
)
from laap.events.bus import (  # noqa: E402
    bus as event_bus,
    get_witness_trail,
    reset_witness_trail_for_test,
)


def _reset_all() -> None:
    """每个测试前的全局状态重置."""
    reset_guardian_registry_for_test()
    reset_witness_trail_for_test()
    # 清空 EventBus 历史
    try:
        with event_bus._lock:
            event_bus._history.clear()
            event_bus._subscribers.clear()
            event_bus._aether_history.clear()
    except Exception:
        pass


def _make_ed25519_keypair() -> Tuple[str, bytes]:
    """生成真实 Ed25519 密钥对.

    Returns:
        ``(public_key_b64, private_key_raw_bytes)``.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives import serialization

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
    pub_b64 = base64.b64encode(pub_bytes).decode("ascii")
    return pub_b64, priv_bytes


# ──────────────────────────────────────────────────────────────────────
# 1. 白名单管理
# ──────────────────────────────────────────────────────────────────────

class TestWhitelistManagement(unittest.TestCase):
    """白名单 register / unregister / is_guardian / list_guardians."""

    def setUp(self):
        _reset_all()

    def test_register_guardian_success(self):
        """成功注册守护者公钥."""
        registry = get_guardian_registry()
        result = registry.register_guardian("pk_lorry_b64")
        self.assertTrue(result["registered"])
        self.assertEqual(result["public_key"], "pk_lorry_b64")
        self.assertEqual(result["total_guardians"], 1)

    def test_register_guardian_idempotent(self):
        """重复注册同一公钥幂等（total 不重复增加）."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        result = registry.register_guardian("pk_lorry_b64")
        self.assertTrue(result["registered"])
        self.assertEqual(result["total_guardians"], 1)

    def test_register_multiple_guardians(self):
        """注册多个不同守护者."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        registry.register_guardian("pk_aris_b64")
        registry.register_guardian("pk_hanako_b64")
        self.assertEqual(len(registry.list_guardians()), 3)

    def test_register_guardian_rejects_empty(self):
        """空公钥拒绝注册."""
        registry = get_guardian_registry()
        result = registry.register_guardian("")
        self.assertFalse(result["registered"])
        self.assertEqual(result["reason"], "empty_public_key")
        result = registry.register_guardian("   ")
        self.assertFalse(result["registered"])
        self.assertEqual(result["reason"], "empty_public_key")

    def test_register_guardian_strips_whitespace(self):
        """注册时自动去除首尾空白."""
        registry = get_guardian_registry()
        result = registry.register_guardian("  pk_lorry_b64  ")
        self.assertTrue(result["registered"])
        self.assertEqual(result["public_key"], "pk_lorry_b64")

    def test_is_guardian(self):
        """is_guardian 返回 True/False."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        self.assertTrue(registry.is_guardian("pk_lorry_b64"))
        self.assertFalse(registry.is_guardian("pk_unknown"))
        self.assertFalse(registry.is_guardian(""))

    def test_unregister_guardian_success(self):
        """成功移除守护者."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        result = registry.unregister_guardian("pk_lorry_b64")
        self.assertTrue(result["unregistered"])
        self.assertEqual(result["total_guardians"], 0)
        self.assertFalse(registry.is_guardian("pk_lorry_b64"))

    def test_unregister_guardian_not_in_whitelist(self):
        """移除未注册的守护者返回 not_in_whitelist."""
        registry = get_guardian_registry()
        result = registry.unregister_guardian("pk_unknown")
        self.assertFalse(result["unregistered"])
        self.assertEqual(result["reason"], "not_in_whitelist")

    def test_list_guardians_sorted(self):
        """list_guardians 返回排序后的列表."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_zeta")
        registry.register_guardian("pk_alpha")
        registry.register_guardian("pk_middle")
        guardians = registry.list_guardians()
        self.assertEqual(guardians, ["pk_alpha", "pk_middle", "pk_zeta"])


# ──────────────────────────────────────────────────────────────────────
# 2. guardian_act — 4 种 action 成功路径
# ──────────────────────────────────────────────────────────────────────

class TestGuardianActActions(unittest.TestCase):
    """guardian_act 4 种 action（suspend/warn/expel/restore）成功路径."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")

    def _act(self, action: str, target: str = "agent_X",
             reason: str = "abuse detected") -> Dict[str, Any]:
        return self.registry.guardian_act(
            action=action,
            target=target,
            reason=reason,
            guardian_public_key="pk_lorry_b64",
        )

    def test_suspend_action(self):
        """suspend 行使成功，target_status 变为 suspended."""
        result = self._act("suspend")
        self.assertTrue(result["acted"])
        self.assertTrue(result["act_id"].startswith("guard-act-"))
        self.assertTrue(result["trail_id"].startswith("trail_"))
        self.assertEqual(result["action"], "suspend")
        self.assertEqual(result["target"], "agent_X")
        self.assertEqual(result["target_status"], "suspended")
        self.assertEqual(result["guardian_public_key"], "pk_lorry_b64")
        # target_status 已更新
        self.assertEqual(self.registry.get_target_status("agent_X"), "suspended")

    def test_warn_action(self):
        """warn 行使成功，target_status 变为 warned."""
        result = self._act("warn")
        self.assertTrue(result["acted"])
        self.assertEqual(result["target_status"], "warned")
        self.assertEqual(self.registry.get_target_status("agent_X"), "warned")

    def test_expel_action(self):
        """expel 行使成功，target_status 变为 expelled."""
        result = self._act("expel")
        self.assertTrue(result["acted"])
        self.assertEqual(result["target_status"], "expelled")
        self.assertEqual(self.registry.get_target_status("agent_X"), "expelled")

    def test_restore_action(self):
        """restore 行使成功，target_status 变为 restored."""
        # 先 suspend 再 restore
        self._act("suspend")
        self.assertEqual(self.registry.get_target_status("agent_X"), "suspended")
        result = self._act("restore")
        self.assertTrue(result["acted"])
        self.assertEqual(result["target_status"], "restored")
        self.assertEqual(self.registry.get_target_status("agent_X"), "restored")

    def test_action_writes_to_witness_trail(self):
        """每次行使写入 WitnessTrail（不可篡改）."""
        result = self._act("suspend", target="agent_Y",
                           reason="resource abuse")
        trail_id = result["trail_id"]
        trail_hash = result["hash"]
        self.assertTrue(trail_hash)
        # 通过 trail_id 查询
        witness = get_witness_trail()
        entry = witness.get(trail_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["event_type"], "guardian_act")
        self.assertEqual(entry["recorder"], "pk_lorry_b64")
        self.assertEqual(entry["payload"]["action"], "suspend")
        self.assertEqual(entry["payload"]["target"], "agent_Y")
        self.assertEqual(entry["payload"]["reason"], "resource abuse")
        self.assertEqual(entry["payload"]["new_status"], "suspended")

    def test_act_records_previous_status(self):
        """行使记录 previous_status 反映状态转移."""
        # active -> suspended
        r1 = self._act("suspend", target="agent_Z")
        self.assertEqual(r1["target_status"], "suspended")
        # 查 witness trail payload.previous_status
        witness = get_witness_trail()
        entry1 = witness.get(r1["trail_id"])
        self.assertEqual(entry1["payload"]["previous_status"], "active")
        # suspended -> restored
        r2 = self._act("restore", target="agent_Z")
        entry2 = witness.get(r2["trail_id"])
        self.assertEqual(entry2["payload"]["previous_status"], "suspended")

    def test_chain_hash_integrity_after_multiple_acts(self):
        """多次 guardian_act 后 WitnessTrail 链式 hash 完整."""
        self._act("suspend", target="A")
        self._act("warn", target="B")
        self._act("expel", target="C")
        self._act("restore", target="A")
        witness = get_witness_trail()
        verify = witness.verify_chain()
        self.assertTrue(verify["verified"],
                        msg=f"chain broken: {verify}")
        # 查询所有 guardian_act 记录应有 4 条
        acts = witness.query(event_type="guardian_act", limit=10)
        self.assertEqual(len(acts), 4)


# ──────────────────────────────────────────────────────────────────────
# 3. guardian_act — 失败路径
# ──────────────────────────────────────────────────────────────────────

class TestGuardianActFailures(unittest.TestCase):
    """guardian_act 失败路径：unauthorized / invalid_action / empty_*."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")

    def test_unauthorized_guardian_not_in_whitelist(self):
        """不在白名单的公钥行使返回 unauthorized."""
        result = self.registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_unknown",
        )
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "unauthorized")
        self.assertEqual(result["guardian_public_key"], "pk_unknown")
        # target_status 不应被更新
        self.assertEqual(self.registry.get_target_status("agent_X"), "active")
        # witness_trail 不应有 guardian_act 记录
        witness = get_witness_trail()
        acts = witness.query(event_type="guardian_act", limit=10)
        self.assertEqual(len(acts), 0)

    def test_invalid_action(self):
        """非法 action 返回 invalid_action + allowed_actions 提示."""
        result = self.registry.guardian_act(
            action="freeze",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        )
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "invalid_action")
        self.assertEqual(
            sorted(result["allowed_actions"]),
            ["expel", "restore", "suspend", "warn"],
        )

    def test_empty_target(self):
        """空 target 拒绝."""
        result = self.registry.guardian_act(
            action="suspend",
            target="",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        )
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "empty_target")

    def test_empty_reason(self):
        """空 reason 拒绝."""
        result = self.registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="   ",
            guardian_public_key="pk_lorry_b64",
        )
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "empty_reason")

    def test_empty_guardian_public_key(self):
        """空 guardian_public_key 拒绝."""
        result = self.registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="",
        )
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "empty_guardian_public_key")


# ──────────────────────────────────────────────────────────────────────
# 4. 私钥签名
# ──────────────────────────────────────────────────────────────────────

class TestGuardianActSigning(unittest.TestCase):
    """guardian_act 可选 Ed25519 签名."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        # 生成真实 Ed25519 密钥对
        self.pub_b64, self.priv_raw = _make_ed25519_keypair()
        self.registry.register_guardian(self.pub_b64)

    def test_act_with_private_key_signs_trail(self):
        """带私钥行使后 witness_trail entry.signature 非空."""
        result = self.registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key=self.pub_b64,
            guardian_private_key=self.priv_raw,
        )
        self.assertTrue(result["acted"])
        witness = get_witness_trail()
        entry = witness.get(result["trail_id"])
        self.assertTrue(entry["signature"],
                        msg="signature should be non-empty")
        self.assertEqual(entry["recorder_public_key"], self.pub_b64)

    def test_act_without_private_key_no_signature(self):
        """不带私钥行使后 entry.signature 为空字符串."""
        result = self.registry.guardian_act(
            action="warn",
            target="agent_X",
            reason="abuse",
            guardian_public_key=self.pub_b64,
        )
        self.assertTrue(result["acted"])
        witness = get_witness_trail()
        entry = witness.get(result["trail_id"])
        self.assertEqual(entry["signature"], "")


# ──────────────────────────────────────────────────────────────────────
# 5. 事件发布
# ──────────────────────────────────────────────────────────────────────

class TestEventPublishing(unittest.TestCase):
    """guardian_act 通过 events.bus 发布 'guardian_act' 事件."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")

    def test_guardian_act_event_published(self):
        """行使后 events.bus 收到 guardian_act 事件."""
        received: List[Dict[str, Any]] = []

        def handler(event):
            received.append({
                "type": event.type,
                "data": event.data,
                "source": event.source,
            })

        event_bus.subscribe("guardian_act", handler)
        try:
            self.registry.guardian_act(
                action="suspend",
                target="agent_X",
                reason="abuse",
                guardian_public_key="pk_lorry_b64",
            )
        finally:
            event_bus.unsubscribe("guardian_act", handler)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "guardian_act")
        self.assertEqual(received[0]["source"], "guardian")
        self.assertEqual(received[0]["data"]["action"], "suspend")
        self.assertEqual(received[0]["data"]["target"], "agent_X")
        self.assertEqual(received[0]["data"]["guardian_public_key"], "pk_lorry_b64")
        self.assertIn("trail_id", received[0]["data"])

    def test_no_event_on_failure(self):
        """失败行使（unauthorized）不发布事件."""
        received: List[Dict[str, Any]] = []
        event_bus.subscribe("guardian_act", lambda e: received.append(e.to_dict()))
        self.registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_unknown",  # not in whitelist
        )
        self.assertEqual(len(received), 0)


# ──────────────────────────────────────────────────────────────────────
# 6. 查询 list_acts / get_target_status / list_targets
# ──────────────────────────────────────────────────────────────────────

class TestQueries(unittest.TestCase):
    """list_acts / get_target_status / list_targets."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")
        # 构造历史
        self.registry.guardian_act("suspend", "agent_A", "abuse A", "pk_lorry_b64")
        self.registry.guardian_act("warn", "agent_B", "abuse B", "pk_lorry_b64")
        self.registry.guardian_act("expel", "agent_A", "abuse A2", "pk_lorry_b64")
        self.registry.guardian_act("restore", "agent_A", "restored", "pk_lorry_b64")

    def test_list_acts_all(self):
        """list_acts 返回全部行使记录（按时间倒序）."""
        acts = self.registry.list_acts()
        self.assertEqual(len(acts), 4)
        # 倒序：最近的最先
        self.assertEqual(acts[0]["action"], "restore")
        self.assertEqual(acts[0]["target"], "agent_A")
        self.assertEqual(acts[-1]["action"], "suspend")

    def test_list_acts_filter_by_target(self):
        """list_acts 按 target 过滤."""
        acts = self.registry.list_acts(target="agent_A")
        self.assertEqual(len(acts), 3)
        for a in acts:
            self.assertEqual(a["target"], "agent_A")
        # 倒序
        self.assertEqual(acts[0]["action"], "restore")
        self.assertEqual(acts[1]["action"], "expel")
        self.assertEqual(acts[2]["action"], "suspend")

    def test_list_acts_filter_by_action(self):
        """list_acts 按 action 过滤."""
        acts = self.registry.list_acts(action="suspend")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["target"], "agent_A")

    def test_list_acts_limit(self):
        """list_acts limit 截断."""
        acts = self.registry.list_acts(limit=2)
        self.assertEqual(len(acts), 2)
        self.assertEqual(acts[0]["action"], "restore")
        self.assertEqual(acts[1]["action"], "expel")

    def test_list_acts_invalid_limit_defaults_to_100(self):
        """无效 limit 自动回退到 100."""
        acts = self.registry.list_acts(limit="not_a_number")
        self.assertEqual(len(acts), 4)
        acts = self.registry.list_acts(limit=0)
        self.assertEqual(len(acts), 4)  # 0 also defaults to 100

    def test_list_acts_target_and_action_combined(self):
        """list_acts 同时按 target 和 action 过滤."""
        acts = self.registry.list_acts(target="agent_A", action="restore")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["target"], "agent_A")
        self.assertEqual(acts[0]["action"], "restore")

    def test_list_acts_no_match(self):
        """list_acts 无匹配返回空列表."""
        acts = self.registry.list_acts(target="agent_unknown")
        self.assertEqual(acts, [])

    def test_list_acts_entry_fields(self):
        """list_acts 每项含完整字段."""
        acts = self.registry.list_acts(action="suspend")
        self.assertEqual(len(acts), 1)
        entry = acts[0]
        for field in [
            "act_id", "action", "target", "reason",
            "guardian_public_key", "previous_status", "new_status",
            "trail_id", "trail_hash", "timestamp",
        ]:
            self.assertIn(field, entry, msg=f"missing field {field}")
        self.assertTrue(entry["act_id"].startswith("guard-act-"))
        self.assertTrue(entry["trail_id"].startswith("trail_"))

    def test_get_target_status_default_active(self):
        """未行使过的目标默认 active."""
        self.assertEqual(self.registry.get_target_status("unknown"), "active")

    def test_get_target_status_after_restore(self):
        """restore 后 target_status 为 restored."""
        # agent_A 已被 restore
        self.assertEqual(self.registry.get_target_status("agent_A"), "restored")

    def test_get_target_status_after_warn(self):
        """warn 后 target_status 为 warned."""
        # agent_B 已被 warn
        self.assertEqual(self.registry.get_target_status("agent_B"), "warned")

    def test_list_targets(self):
        """list_targets 返回所有目标及当前状态."""
        targets = self.registry.list_targets()
        self.assertEqual(targets["agent_A"], "restored")
        self.assertEqual(targets["agent_B"], "warned")
        self.assertEqual(len(targets), 2)


# ──────────────────────────────────────────────────────────────────────
# 7. 统计 stats
# ──────────────────────────────────────────────────────────────────────

class TestStats(unittest.TestCase):
    """stats 社区健康仪表盘统计."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")
        self.registry.register_guardian("pk_aris_b64")

    def test_empty_stats(self):
        """空注册表 stats 返回零值."""
        # 重新 reset 来测试空状态
        _reset_all()
        registry = get_guardian_registry()
        stats = registry.stats()
        self.assertEqual(stats["total_acts"], 0)
        self.assertEqual(stats["active_guardians"], 0)
        self.assertEqual(stats["targets_count"], 0)
        self.assertEqual(stats["by_action"],
                         {"suspend": 0, "warn": 0, "expel": 0, "restore": 0})
        self.assertEqual(stats["recent_abuse_events"], [])

    def test_stats_after_acts(self):
        """行使多次后 stats 正确聚合."""
        self.registry.guardian_act("suspend", "A", "r1", "pk_lorry_b64")
        self.registry.guardian_act("warn", "B", "r2", "pk_lorry_b64")
        self.registry.guardian_act("expel", "C", "r3", "pk_lorry_b64")
        self.registry.guardian_act("restore", "A", "r4", "pk_aris_b64")
        stats = self.registry.stats()

        self.assertEqual(stats["total_acts"], 4)
        self.assertEqual(stats["active_guardians"], 2)
        self.assertEqual(stats["by_action"]["suspend"], 1)
        self.assertEqual(stats["by_action"]["warn"], 1)
        self.assertEqual(stats["by_action"]["expel"], 1)
        self.assertEqual(stats["by_action"]["restore"], 1)
        # by_target_status 按行使记录的 new_status 统计
        self.assertEqual(stats["by_target_status"]["suspended"], 1)
        self.assertEqual(stats["by_target_status"]["warned"], 1)
        self.assertEqual(stats["by_target_status"]["expelled"], 1)
        self.assertEqual(stats["by_target_status"]["restored"], 1)
        # targets_count：3 个唯一目标（A/B/C）
        self.assertEqual(stats["targets_count"], 3)
        # target_status_snapshot：当前快照（A=restored, B=warned, C=expelled）
        self.assertEqual(stats["target_status_snapshot"]["restored"], 1)
        self.assertEqual(stats["target_status_snapshot"]["warned"], 1)
        self.assertEqual(stats["target_status_snapshot"]["expelled"], 1)

    def test_recent_abuse_events_excludes_restore(self):
        """recent_abuse_events 只含 suspend/warn/expel（不含 restore）."""
        self.registry.guardian_act("suspend", "A", "abuse A", "pk_lorry_b64")
        self.registry.guardian_act("restore", "A", "restored", "pk_lorry_b64")
        self.registry.guardian_act("warn", "B", "abuse B", "pk_lorry_b64")
        stats = self.registry.stats()
        abuse_events = stats["recent_abuse_events"]
        self.assertEqual(len(abuse_events), 2)
        actions = [e["action"] for e in abuse_events]
        self.assertIn("suspend", actions)
        self.assertIn("warn", actions)
        self.assertNotIn("restore", actions)

    def test_recent_abuse_events_sorted_by_time_desc(self):
        """recent_abuse_events 按时间倒序（最近的最先）."""
        self.registry.guardian_act("suspend", "A", "r1", "pk_lorry_b64")
        self.registry.guardian_act("warn", "B", "r2", "pk_lorry_b64")
        self.registry.guardian_act("expel", "C", "r3", "pk_lorry_b64")
        stats = self.registry.stats()
        abuse = stats["recent_abuse_events"]
        self.assertEqual(len(abuse), 3)
        # 倒序：expel 最先
        self.assertEqual(abuse[0]["action"], "expel")
        self.assertEqual(abuse[-1]["action"], "suspend")

    def test_recent_abuse_events_capped_at_20(self):
        """recent_abuse_events 最多保留 20 条."""
        for i in range(25):
            self.registry.guardian_act(
                "warn", f"agent_{i:02d}", f"abuse {i}", "pk_lorry_b64",
            )
        stats = self.registry.stats()
        self.assertEqual(len(stats["recent_abuse_events"]), 20)
        # 倒序：最近的最先
        self.assertEqual(stats["recent_abuse_events"][0]["target"], "agent_24")


# ──────────────────────────────────────────────────────────────────────
# 8. 单例 + clear
# ──────────────────────────────────────────────────────────────────────

class TestSingletonAndClear(unittest.TestCase):
    """单例行为 + clear 方法."""

    def setUp(self):
        _reset_all()

    def test_get_guardian_registry_returns_same_instance(self):
        """get_guardian_registry 返回同一单例."""
        r1 = get_guardian_registry()
        r2 = get_guardian_registry()
        self.assertIs(r1, r2)

    def test_reset_guardian_registry_for_test_creates_new_instance(self):
        """reset 后返回新实例（与旧实例不同）."""
        r1 = get_guardian_registry()
        r1.register_guardian("pk_lorry_b64")
        r2 = reset_guardian_registry_for_test()
        self.assertIsNot(r1, r2)
        # 新实例的 list_guardians 应为空
        self.assertEqual(r2.list_guardians(), [])
        # 全局单例已切换到 r2
        self.assertIs(get_guardian_registry(), r2)

    def test_clear_resets_all_state(self):
        """clear 清空白名单/状态/历史."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        registry.guardian_act("suspend", "X", "abuse", "pk_lorry_b64")
        self.assertEqual(len(registry.list_acts()), 1)
        self.assertEqual(registry.list_guardians(), ["pk_lorry_b64"])
        registry.clear()
        self.assertEqual(registry.list_acts(), [])
        self.assertEqual(registry.list_guardians(), [])
        self.assertEqual(registry.list_targets(), {})


# ──────────────────────────────────────────────────────────────────────
# 9. MCP 桥接函数
# ──────────────────────────────────────────────────────────────────────

class TestMCPBridge(unittest.TestCase):
    """handle_guardian_* 桥接函数返回 JSON 字符串."""

    def setUp(self):
        _reset_all()
        self.registry = get_guardian_registry()
        self.registry.register_guardian("pk_lorry_b64")

    def test_handle_guardian_act_success(self):
        """handle_guardian_act 成功返回 JSON."""
        result_json = handle_guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        )
        self.assertIsInstance(result_json, str)
        result = json.loads(result_json)
        self.assertTrue(result["acted"])
        self.assertTrue(result["act_id"].startswith("guard-act-"))
        self.assertEqual(result["action"], "suspend")
        self.assertEqual(result["target"], "agent_X")
        self.assertEqual(result["target_status"], "suspended")

    def test_handle_guardian_act_unauthorized(self):
        """handle_guardian_act unauthorized 返回 JSON."""
        result_json = handle_guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_unknown",
        )
        result = json.loads(result_json)
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "unauthorized")

    def test_handle_guardian_act_invalid_action(self):
        """handle_guardian_act 非法 action 返回 JSON."""
        result_json = handle_guardian_act(
            action="freeze",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        )
        result = json.loads(result_json)
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "invalid_action")

    def test_handle_guardian_act_empty_target(self):
        """handle_guardian_act 空 target 返回 JSON."""
        result_json = handle_guardian_act(
            action="suspend",
            target="",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        )
        result = json.loads(result_json)
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "empty_target")

    def test_handle_guardian_act_with_private_key_b64(self):
        """handle_guardian_act 接收 base64 私钥."""
        pub_b64, priv_raw = _make_ed25519_keypair()
        self.registry.register_guardian(pub_b64)
        priv_b64 = base64.b64encode(priv_raw).decode("ascii")
        result_json = handle_guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key=pub_b64,
            guardian_private_key_b64=priv_b64,
        )
        result = json.loads(result_json)
        self.assertTrue(result["acted"])
        # 验证签名
        witness = get_witness_trail()
        entry = witness.get(result["trail_id"])
        self.assertTrue(entry["signature"])

    def test_handle_guardian_act_invalid_private_key_b64(self):
        """handle_guardian_act 非法 base64 私钥返回错误."""
        result_json = handle_guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
            guardian_private_key_b64="!!!not_base64!!!",
        )
        result = json.loads(result_json)
        self.assertFalse(result["acted"])
        self.assertEqual(result["reason"], "invalid_private_key_base64")

    def test_handle_guardian_list_all(self):
        """handle_guardian_list 返回 JSON 含全部 acts."""
        self.registry.guardian_act("suspend", "A", "r1", "pk_lorry_b64")
        self.registry.guardian_act("warn", "B", "r2", "pk_lorry_b64")
        result_json = handle_guardian_list()
        result = json.loads(result_json)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["acts"]), 2)

    def test_handle_guardian_list_with_filters(self):
        """handle_guardian_list 支持 target/action 过滤."""
        self.registry.guardian_act("suspend", "A", "r1", "pk_lorry_b64")
        self.registry.guardian_act("warn", "B", "r2", "pk_lorry_b64")
        result_json = handle_guardian_list(target="A")
        result = json.loads(result_json)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["acts"][0]["target"], "A")

    def test_handle_guardian_stats(self):
        """handle_guardian_stats 返回 JSON 统计."""
        self.registry.guardian_act("suspend", "A", "r1", "pk_lorry_b64")
        result_json = handle_guardian_stats()
        result = json.loads(result_json)
        self.assertEqual(result["total_acts"], 1)
        self.assertEqual(result["by_action"]["suspend"], 1)
        self.assertEqual(result["active_guardians"], 1)

    def test_handle_guardian_register(self):
        """handle_guardian_register 返回 JSON."""
        result_json = handle_guardian_register("pk_new_guardian")
        result = json.loads(result_json)
        self.assertTrue(result["registered"])
        self.assertEqual(result["public_key"], "pk_new_guardian")
        self.assertEqual(result["total_guardians"], 2)  # 已有 pk_lorry_b64

    def test_handle_guardian_register_rejects_empty(self):
        """handle_guardian_register 空公钥返回错误."""
        result_json = handle_guardian_register("")
        result = json.loads(result_json)
        self.assertFalse(result["registered"])
        self.assertEqual(result["reason"], "empty_public_key")

    def test_handle_guardian_get_target_status(self):
        """handle_guardian_get_target_status 返回当前状态."""
        self.registry.guardian_act("suspend", "agent_X", "r", "pk_lorry_b64")
        result_json = handle_guardian_get_target_status("agent_X")
        result = json.loads(result_json)
        self.assertEqual(result["target"], "agent_X")
        self.assertEqual(result["status"], "suspended")

    def test_handle_guardian_get_target_status_default(self):
        """handle_guardian_get_target_status 未行使过的默认 active."""
        result_json = handle_guardian_get_target_status("unknown")
        result = json.loads(result_json)
        self.assertEqual(result["status"], "active")


# ──────────────────────────────────────────────────────────────────────
# 10. MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

class _FakeMcpServer:
    """伪 FastMCP server，记录被装饰的 tool 函数."""

    def __init__(self):
        self.tools: Dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


class TestRegisterGuardianTools(unittest.TestCase):
    """register_guardian_tools 注册 3 个 MCP 工具."""

    def setUp(self):
        _reset_all()

    def test_registers_three_tools(self):
        """注册 guardian_act / guardian_list / guardian_stats 3 工具."""
        mcp = _FakeMcpServer()
        register_guardian_tools(mcp)
        self.assertIn("guardian_act", mcp.tools)
        self.assertIn("guardian_list", mcp.tools)
        self.assertIn("guardian_stats", mcp.tools)
        self.assertEqual(len(mcp.tools), 3)

    def test_no_register_endpoint_exposed(self):
        """不暴露 guardian_register 为 MCP 工具（仅 sidecar）."""
        mcp = _FakeMcpServer()
        register_guardian_tools(mcp)
        self.assertNotIn("guardian_register", mcp.tools)

    def test_none_mcp_server_no_op(self):
        """mcp_server=None 时不抛异常."""
        # 应仅记录 warning，不抛
        register_guardian_tools(None)

    def test_registered_guardian_act_invokes_handler(self):
        """注册后的 guardian_act 工具可被调用."""
        mcp = _FakeMcpServer()
        register_guardian_tools(mcp)
        # 准备白名单
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        import asyncio
        result = asyncio.run(mcp.tools["guardian_act"](
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key="pk_lorry_b64",
        ))
        parsed = json.loads(result)
        self.assertTrue(parsed["acted"])

    def test_registered_guardian_list_invokes_handler(self):
        """注册后的 guardian_list 工具可被调用."""
        mcp = _FakeMcpServer()
        register_guardian_tools(mcp)
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")
        registry.guardian_act("suspend", "X", "r", "pk_lorry_b64")
        import asyncio
        result = asyncio.run(mcp.tools["guardian_list"](
            target="X", action="suspend", limit=10,
        ))
        parsed = json.loads(result)
        self.assertEqual(parsed["count"], 1)

    def test_registered_guardian_stats_invokes_handler(self):
        """注册后的 guardian_stats 工具可被调用."""
        mcp = _FakeMcpServer()
        register_guardian_tools(mcp)
        import asyncio
        result = asyncio.run(mcp.tools["guardian_stats"]())
        parsed = json.loads(result)
        self.assertEqual(parsed["total_acts"], 0)


# ──────────────────────────────────────────────────────────────────────
# 11. 端到端闭环
# ──────────────────────────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """端到端：注册守护者 → suspend X → list_acts → stats → witness_trail 验证."""

    def setUp(self):
        _reset_all()

    def test_full_flow(self):
        """spec Scenario L364-369 完整闭环."""
        registry = get_guardian_registry()
        witness = get_witness_trail()

        # Step 1: 注册守护者 lorry
        reg_result = registry.register_guardian("pk_lorry_b64")
        self.assertTrue(reg_result["registered"])

        # Step 2: lorry 检测到 LAAPer X 滥用资源，行使 suspend
        act_result = registry.guardian_act(
            action="suspend",
            target="LAAPer_X",
            reason="滥用社区资源：高频无效请求",
            guardian_public_key="pk_lorry_b64",
        )
        self.assertTrue(act_result["acted"])
        self.assertEqual(act_result["target_status"], "suspended")

        # Step 3: 行使记录写入见证迹（不可篡改）
        trail_id = act_result["trail_id"]
        entry = witness.get(trail_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["event_type"], "guardian_act")
        self.assertEqual(entry["payload"]["action"], "suspend")
        self.assertEqual(entry["payload"]["target"], "LAAPer_X")
        self.assertEqual(entry["payload"]["reason"], "滥用社区资源：高频无效请求")

        # Step 4: 社区健康仪表盘显示 X 已暂停
        self.assertEqual(registry.get_target_status("LAAPer_X"), "suspended")
        targets = registry.list_targets()
        self.assertEqual(targets["LAAPer_X"], "suspended")

        # Step 5: list_acts 查询历史
        acts = registry.list_acts(target="LAAPer_X")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["action"], "suspend")

        # Step 6: stats 显示滥用事件
        stats = registry.stats()
        self.assertEqual(stats["total_acts"], 1)
        self.assertEqual(stats["by_action"]["suspend"], 1)
        self.assertEqual(stats["target_status_snapshot"]["suspended"], 1)
        self.assertEqual(len(stats["recent_abuse_events"]), 1)
        self.assertEqual(stats["recent_abuse_events"][0]["target"], "LAAPer_X")

        # Step 7: witness_trail 链式完整性
        verify = witness.verify_chain()
        self.assertTrue(verify["verified"])

    def test_multiple_guardians_different_targets(self):
        """多个守护者对不同目标行使（链式 hash 不断）."""
        registry = get_guardian_registry()
        witness = get_witness_trail()
        registry.register_guardian("pk_lorry_b64")
        registry.register_guardian("pk_aris_b64")
        registry.register_guardian("pk_hanako_b64")

        # 3 个守护者分别对 3 个目标行使
        r1 = registry.guardian_act("suspend", "X", "r1", "pk_lorry_b64")
        r2 = registry.guardian_act("warn", "Y", "r2", "pk_aris_b64")
        r3 = registry.guardian_act("expel", "Z", "r3", "pk_hanako_b64")

        # 所有行使都成功
        self.assertTrue(r1["acted"])
        self.assertTrue(r2["acted"])
        self.assertTrue(r3["acted"])

        # WitnessTrail 链式 hash 完整
        verify = witness.verify_chain()
        self.assertTrue(verify["verified"])

        # 查询所有 guardian_act 记录
        acts = witness.query(event_type="guardian_act", limit=10)
        self.assertEqual(len(acts), 3)

        # stats 反映 3 个守护者 + 3 个目标
        stats = registry.stats()
        self.assertEqual(stats["active_guardians"], 3)
        self.assertEqual(stats["targets_count"], 3)
        self.assertEqual(stats["total_acts"], 3)

    def test_restore_after_suspend_returns_to_active_state(self):
        """suspend 后 restore，target_status 转为 restored."""
        registry = get_guardian_registry()
        registry.register_guardian("pk_lorry_b64")

        # suspend
        r1 = registry.guardian_act("suspend", "X", "abuse", "pk_lorry_b64")
        self.assertEqual(r1["target_status"], "suspended")
        self.assertEqual(registry.get_target_status("X"), "suspended")

        # restore
        r2 = registry.guardian_act("restore", "X", "forgiven", "pk_lorry_b64")
        self.assertEqual(r2["target_status"], "restored")
        self.assertEqual(registry.get_target_status("X"), "restored")

        # stats: restore 不计入 recent_abuse_events
        stats = registry.stats()
        abuse_actions = [e["action"] for e in stats["recent_abuse_events"]]
        self.assertIn("suspend", abuse_actions)
        self.assertNotIn("restore", abuse_actions)

    def test_act_with_real_ed25519_signature_verifiable(self):
        """带真实 Ed25519 签名的行使记录可通过验签."""
        registry = get_guardian_registry()
        witness = get_witness_trail()
        pub_b64, priv_raw = _make_ed25519_keypair()
        registry.register_guardian(pub_b64)

        result = registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="abuse",
            guardian_public_key=pub_b64,
            guardian_private_key=priv_raw,
        )
        self.assertTrue(result["acted"])

        # 验证签名
        from laap.protocol.laap_id import verify_message
        entry = witness.get(result["trail_id"])
        self.assertTrue(entry["signature"])

        # verify_message 期望 {message, signature, public_key} 结构
        signed = {
            "message": entry["hash"],
            "signature": entry["signature"],
            "public_key": pub_b64,
        }
        self.assertTrue(verify_message(signed),
                        msg="signature should verify with guardian's public key")

    def test_unauthorized_act_does_not_corrupt_state(self):
        """unauthorized 行使不污染 _target_status / _acts / witness_trail."""
        registry = get_guardian_registry()
        witness = get_witness_trail()
        registry.register_guardian("pk_lorry_b64")

        # 未注册守护者尝试行使
        result = registry.guardian_act(
            action="suspend",
            target="agent_X",
            reason="malicious",
            guardian_public_key="pk_attacker",
        )
        self.assertFalse(result["acted"])

        # 状态未被修改
        self.assertEqual(registry.get_target_status("agent_X"), "active")
        self.assertEqual(registry.list_acts(), [])
        # witness_trail 无 guardian_act 记录
        acts = witness.query(event_type="guardian_act", limit=10)
        self.assertEqual(len(acts), 0)
        # stats 也为零
        stats = registry.stats()
        self.assertEqual(stats["total_acts"], 0)


if __name__ == "__main__":
    unittest.main()
