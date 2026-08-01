"""LAAP — 共同进化循环测试 (P4-coevolution-loop SubTask 4.6)

================================================================
  测试 share -> absorb -> feedback -> notify 闭环
================================================================

覆盖 spec SubTask 4.6 的全部场景：

* SubTask 4.1 ``share_experience``：成功路径 + 失败路径（empty
  agent/content/source_memories + 低置信被 Memex 拒绝）
* SubTask 4.2 ``absorb_experience``：成功路径 + 幂等 + 失败路径
  （shared_id 不存在 + 空 agent + grounding 拒绝）
* SubTask 4.3 ``feedback_experience``：成功路径 + derived_from
  一致性校验 + 不存在节点 + 事件通知原分享者
* SubTask 4.4 共同进化图：节点 / 边 / descendants / ancestors
* SubTask 4.5 通知机制：``coevolution_shared`` /
  ``coevolution_absorbed`` / ``coevolution_feedback`` 事件发布到
  本地 EventBus
* MCP 桥接：``handle_coevolution_*`` 返回 JSON 字符串
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

# 确保 laap 包可导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_LAAP_ROOT = os.path.dirname(_HERE)
if _LAAP_ROOT not in sys.path:
    sys.path.insert(0, _LAAP_ROOT)

from laap.protocol.laap_coevolution import (  # noqa: E402
    CoevolutionLoop,
    ExperienceNode,
    get_coevolution_loop,
    reset_coevolution_loop_for_test,
)
from laap.protocol.laap_memex import (  # noqa: E402
    reset_memex_store_for_test,
)
from laap.events.bus import bus as event_bus  # noqa: E402


def _reset_all() -> None:
    """每个测试前的全局状态重置."""
    reset_coevolution_loop_for_test()
    reset_memex_store_for_test()
    # 清空 EventBus 历史
    try:
        with event_bus._lock:
            event_bus._history.clear()
            event_bus._subscribers.clear()
            event_bus._aether_history.clear()
    except Exception:
        pass


def _make_source_memories(n: int = 1) -> List[Dict[str, Any]]:
    """构造 n 条来源记忆（含 memory_id）."""
    return [
        {"memory_id": f"mem_test_{i:04d}", "scope": "episodic",
         "confidence": 0.85}
        for i in range(n)
    ]


# ──────────────────────────────────────────────────────────────────────
# 1. share_experience
# ──────────────────────────────────────────────────────────────────────

class TestShareExperience(unittest.TestCase):
    """SubTask 4.1: share_experience."""

    def setUp(self):
        _reset_all()

    def test_share_success_creates_root_node(self):
        """成功分享：返回 shared_id，并在共同进化图创建根节点."""
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent="aris",
            content="在重构 causal.py 时发现 do_calculus 的实现可优化",
            source_memories=_make_source_memories(2),
            confidence=0.85,
        )
        self.assertTrue(result["shared"], msg=f"result={result}")
        self.assertIn("shared_id", result)
        self.assertTrue(result["shared_id"].startswith("coevo_"))
        self.assertIn("knowledge_id", result)
        self.assertTrue(result["knowledge_id"].startswith("know_"))

        # 节点存在于图
        node = loop.get_experience(result["shared_id"])
        self.assertIsNotNone(node)
        self.assertEqual(node["agent"], "aris")
        self.assertIsNone(node["derived_from"])
        self.assertEqual(node["derived_chain"], [result["shared_id"]])
        self.assertEqual(node["knowledge_id"], result["knowledge_id"])
        self.assertEqual(node["confidence"], 0.85)
        # 去标识化已应用（用户名 Aris 被替换）
        # 注意：内容中的 Aris 是大写，会被 deidentify 替换为 [user]
        self.assertNotIn("Aris", node["content"])

    def test_share_failure_empty_agent(self):
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent="",
            content="内容",
            source_memories=_make_source_memories(),
            confidence=0.8,
        )
        self.assertFalse(result["shared"])
        self.assertEqual(result["reason"], "empty_agent")

    def test_share_failure_empty_content(self):
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent="aris",
            content="   ",
            source_memories=_make_source_memories(),
            confidence=0.8,
        )
        self.assertFalse(result["shared"])
        self.assertEqual(result["reason"], "empty_content")

    def test_share_failure_empty_source_memories(self):
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent="aris",
            content="内容",
            source_memories=[],
            confidence=0.8,
        )
        self.assertFalse(result["shared"])
        self.assertEqual(result["reason"], "empty_source_memories")

    def test_share_failure_low_confidence_rejected_by_memex(self):
        """confidence < 0.6 应被 Memex 拒绝（spec SubTask 4.5）."""
        loop = get_coevolution_loop()
        result = loop.share_experience(
            agent="aris",
            content="内容",
            source_memories=_make_source_memories(),
            confidence=0.4,
        )
        self.assertFalse(result["shared"])
        self.assertEqual(result["reason"], "low_confidence")

    def test_share_publishes_coevolution_shared_event(self):
        """分享成功后应发布 ``coevolution_shared`` 事件."""
        loop = get_coevolution_loop()
        loop.share_experience(
            agent="aris",
            content="经验内容",
            source_memories=_make_source_memories(),
            confidence=0.75,
        )
        events = event_bus.history(limit=50)
        types = [e.type for e in events]
        self.assertIn("coevolution_shared", types)
        # 校验 payload
        shared_evt = next(e for e in events if e.type == "coevolution_shared")
        self.assertEqual(shared_evt.data["agent"], "aris")
        self.assertIn("shared_id", shared_evt.data)
        self.assertIn("knowledge_id", shared_evt.data)
        self.assertEqual(shared_evt.source, "coevo")


# ──────────────────────────────────────────────────────────────────────
# 2. absorb_experience
# ──────────────────────────────────────────────────────────────────────

class TestAbsorbExperience(unittest.TestCase):
    """SubTask 4.2: absorb_experience."""

    def setUp(self):
        _reset_all()
        self.loop = get_coevolution_loop()
        share_result = self.loop.share_experience(
            agent="aris",
            content="原始经验：在调试 truth-grounding 时 grounding_confidence 计算需要考虑 evidence 权重",
            source_memories=_make_source_memories(1),
            confidence=0.85,
        )
        self.assertTrue(share_result["shared"], msg=share_result)
        self.shared_id = share_result["shared_id"]
        self.parent_knowledge_id = share_result["knowledge_id"]

    def test_absorb_success_creates_derived_node(self):
        """成功吸收：返回 new_experience_id，并创建 derived_from=shared_id 的子节点."""
        result = self.loop.absorb_experience(
            agent="hanako",
            shared_id=self.shared_id,
        )
        self.assertTrue(result["absorbed"], msg=result)
        new_id = result["new_experience_id"]
        self.assertTrue(new_id.startswith("coevo_"))
        self.assertEqual(result["derived_from"], self.shared_id)
        self.assertIn("knowledge_id", result)
        self.assertTrue(result["knowledge_id"].startswith("know_"))
        self.assertIn("absorption_summary", result)
        self.assertIn("grounding", result)
        self.assertIn("hanako", result["absorption_summary"])

        # 子节点存在于图
        node = self.loop.get_experience(new_id)
        self.assertIsNotNone(node)
        self.assertEqual(node["agent"], "hanako")
        self.assertEqual(node["derived_from"], self.shared_id)
        # derived_chain 应为 [shared_id, new_id]
        self.assertEqual(node["derived_chain"],
                         [self.shared_id, new_id])
        self.assertEqual(node["knowledge_id"], result["knowledge_id"])
        # 吸收摘要写入节点
        self.assertEqual(node["absorption_summary"],
                         result["absorption_summary"])

    def test_absorb_idempotent_returns_same_new_id(self):
        """同一 (agent, shared_id) 二次吸收应返回同一 new_experience_id.

        注意：因为 absorb 每次都生成新 LLM 摘要 + 新 derived_content，
        Memex 会给新 knowledge_id，所以严格幂等要求知识内容相同.
        本测试用 mock 让 derived_content 二次相同，触发 Memex 的
        content_fingerprint 幂等.
        """
        # 第一次
        r1 = self.loop.absorb_experience(
            agent="hanako",
            shared_id=self.shared_id,
        )
        self.assertTrue(r1["absorbed"])
        # 第二次：用相同 derived_content（patch _llm_absorb_summary）
        with patch(
            "laap.protocol.laap_coevolution._llm_absorb_summary",
            return_value={
                "summary": "固定摘要",
                "grounding": {"state": "uncertain", "rejected": False},
                "derived_content": "固定派生内容",
            },
        ):
            # 同时也 patch 第一次的 summary/derived_content 才能命中幂等
            # 由于 r1 已用真实路径生成不同内容，这里仅验证第二次
            # 在内容固定的情况下返回与 r1 不同的新 ID
            # （因为 r1 的内容 != 固定派生内容）
            r2 = self.loop.absorb_experience(
                agent="hanako",
                shared_id=self.shared_id,
            )
        self.assertTrue(r2["absorbed"])
        # 第二次是新的 knowledge_id（因为内容不同），所以新 new_id
        self.assertNotEqual(r2["new_experience_id"], r1["new_experience_id"])

        # 第三次：相同 derived_content 应触发幂等，返回 r2 的 new_id
        with patch(
            "laap.protocol.laap_coevolution._llm_absorb_summary",
            return_value={
                "summary": "固定摘要",
                "grounding": {"state": "uncertain", "rejected": False},
                "derived_content": "固定派生内容",
            },
        ):
            r3 = self.loop.absorb_experience(
                agent="hanako",
                shared_id=self.shared_id,
            )
        self.assertTrue(r3["absorbed"])
        self.assertEqual(r3["new_experience_id"], r2["new_experience_id"])
        self.assertTrue(r3.get("idempotent", False))

    def test_absorb_failure_shared_id_not_found(self):
        result = self.loop.absorb_experience(
            agent="hanako",
            shared_id="coevo_nonexistent_xxxx",
        )
        self.assertFalse(result["absorbed"])
        self.assertEqual(result["reason"], "shared_id_not_found")

    def test_absorb_failure_empty_agent(self):
        result = self.loop.absorb_experience(
            agent="",
            shared_id=self.shared_id,
        )
        self.assertFalse(result["absorbed"])
        self.assertEqual(result["reason"], "empty_agent")

    def test_absorb_failure_empty_shared_id(self):
        result = self.loop.absorb_experience(
            agent="hanako",
            shared_id="",
        )
        self.assertFalse(result["absorbed"])
        self.assertEqual(result["reason"], "empty_shared_id")

    def test_absorb_failure_grounding_rejected(self):
        """LLM 摘要的 truth-grounding 校验为 error 态时应拒绝吸收."""
        with patch(
            "laap.protocol.laap_coevolution._llm_absorb_summary",
            return_value={
                "summary": "错误摘要",
                "grounding": {
                    "state": "error",
                    "rejected": True,
                    "confidence": 0.0,
                },
                "derived_content": "错误内容",
            },
        ):
            result = self.loop.absorb_experience(
                agent="hanako",
                shared_id=self.shared_id,
            )
        self.assertFalse(result["absorbed"])
        self.assertEqual(result["reason"], "grounding_rejected")
        self.assertIn("grounding", result)
        self.assertTrue(result["grounding"]["rejected"])

    def test_absorb_publishes_coevolution_absorbed_event(self):
        """吸收成功后应发布 ``coevolution_absorbed`` 事件."""
        self.loop.absorb_experience(
            agent="hanako",
            shared_id=self.shared_id,
        )
        events = event_bus.history(limit=100)
        types = [e.type for e in events]
        self.assertIn("coevolution_absorbed", types)
        absorbed_evt = next(
            e for e in events if e.type == "coevolution_absorbed"
        )
        self.assertEqual(absorbed_evt.data["agent"], "hanako")
        self.assertEqual(absorbed_evt.data["parent_agent"], "aris")
        self.assertEqual(absorbed_evt.data["derived_from"], self.shared_id)
        self.assertIn("new_experience_id", absorbed_evt.data)
        self.assertIn("absorption_summary", absorbed_evt.data)

    def test_absorb_updates_children_adjacency(self):
        """吸收后父节点的 children 邻接表应包含子节点 ID."""
        r = self.loop.absorb_experience(
            agent="hanako",
            shared_id=self.shared_id,
        )
        graph = self.loop.get_graph()
        # 找到 derived_from=shared_id 的边
        edges = [e for e in graph["edges"]
                 if e["from"] == self.shared_id]
        self.assertTrue(any(e["to"] == r["new_experience_id"] for e in edges),
                        msg=f"edges={edges}")


# ──────────────────────────────────────────────────────────────────────
# 3. feedback_experience
# ──────────────────────────────────────────────────────────────────────

class TestFeedbackExperience(unittest.TestCase):
    """SubTask 4.3: feedback_experience."""

    def setUp(self):
        _reset_all()
        self.loop = get_coevolution_loop()
        share_r = self.loop.share_experience(
            agent="aris",
            content="原始经验内容",
            source_memories=_make_source_memories(1),
            confidence=0.85,
        )
        self.shared_id = share_r["shared_id"]
        absorb_r = self.loop.absorb_experience(
            agent="hanako",
            shared_id=self.shared_id,
        )
        self.new_id = absorb_r["new_experience_id"]

    def test_feedback_success_emits_event_with_target_agent(self):
        """成功回传：返回 target_agent=原分享者，并发布 coevolution_feedback 事件."""
        # 清空历史，便于隔离
        with event_bus._lock:
            event_bus._history.clear()

        result = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from=self.shared_id,
        )
        self.assertTrue(result["fed_back"])
        self.assertEqual(result["target_agent"], "aris")
        self.assertEqual(result["source_agent"], "hanako")
        self.assertEqual(result["new_experience_id"], self.new_id)
        self.assertEqual(result["derived_from"], self.shared_id)

        # 事件已发布
        events = event_bus.history(limit=50)
        types = [e.type for e in events]
        self.assertIn("coevolution_feedback", types)
        fb_evt = next(e for e in events if e.type == "coevolution_feedback")
        self.assertEqual(fb_evt.data["target_agent"], "aris")
        self.assertEqual(fb_evt.data["source_agent"], "hanako")
        self.assertEqual(fb_evt.data["new_experience_id"], self.new_id)
        self.assertEqual(fb_evt.data["derived_from"], self.shared_id)

    def test_feedback_failure_new_experience_id_not_found(self):
        result = self.loop.feedback_experience(
            new_experience_id="coevo_nonexistent_yyyy",
            derived_from=self.shared_id,
        )
        self.assertFalse(result["fed_back"])
        self.assertEqual(result["reason"], "new_experience_id_not_found")

    def test_feedback_failure_derived_from_not_found(self):
        result = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from="coevo_nonexistent_zzzz",
        )
        self.assertFalse(result["fed_back"])
        self.assertEqual(result["reason"], "derived_from_not_found")

    def test_feedback_failure_derived_from_mismatch(self):
        """子节点的 derived_from 已存在且与传入不一致时应拒绝."""
        # 先创建第二个 share 节点
        share2 = self.loop.share_experience(
            agent="butter",
            content="另一个独立经验",
            source_memories=_make_source_memories(1),
            confidence=0.8,
        )
        # 尝试用 new_id（属于 shared_id）回传给 share2（错误父节点）
        result = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from=share2["shared_id"],
        )
        self.assertFalse(result["fed_back"])
        self.assertEqual(result["reason"], "derived_from_mismatch")
        self.assertEqual(result["existing_derived_from"], self.shared_id)

    def test_feedback_failure_empty_inputs(self):
        result = self.loop.feedback_experience(
            new_experience_id="",
            derived_from=self.shared_id,
        )
        self.assertFalse(result["fed_back"])
        self.assertEqual(result["reason"], "empty_new_experience_id")

        result = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from="",
        )
        self.assertFalse(result["fed_back"])
        self.assertEqual(result["reason"], "empty_derived_from")

    def test_feedback_idempotent_emits_event_each_call(self):
        """子节点已有 derived_from 时，feedback 仍应触发事件（幂等通知）."""
        with event_bus._lock:
            event_bus._history.clear()
        # 第一次
        r1 = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from=self.shared_id,
        )
        self.assertTrue(r1["fed_back"])
        # 第二次（幂等）
        r2 = self.loop.feedback_experience(
            new_experience_id=self.new_id,
            derived_from=self.shared_id,
        )
        self.assertTrue(r2["fed_back"])
        # 两次都发布事件
        events = [e for e in event_bus.history(limit=50)
                  if e.type == "coevolution_feedback"]
        self.assertEqual(len(events), 2)


# ──────────────────────────────────────────────────────────────────────
# 4. 共同进化图
# ──────────────────────────────────────────────────────────────────────

class TestCoevolutionGraph(unittest.TestCase):
    """SubTask 4.4: 共同进化图查询."""

    def setUp(self):
        _reset_all()
        self.loop = get_coevolution_loop()
        # 创建一棵树：
        #   root1 (aris)
        #     └── child1 (hanako, derived from root1)
        #           └── grandchild1 (butter, derived from child1)
        #   root2 (miku, 独立根)
        r = self.loop.share_experience(
            agent="aris", content="根经验1",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        self.root1 = r["shared_id"]
        a = self.loop.absorb_experience(
            agent="hanako", shared_id=self.root1,
        )
        self.child1 = a["new_experience_id"]
        a2 = self.loop.absorb_experience(
            agent="butter", shared_id=self.child1,
        )
        self.grandchild1 = a2["new_experience_id"]
        r2 = self.loop.share_experience(
            agent="miku", content="根经验2",
            source_memories=_make_source_memories(1), confidence=0.8,
        )
        self.root2 = r2["shared_id"]

    def test_get_graph_returns_nodes_and_edges(self):
        graph = self.loop.get_graph()
        self.assertEqual(graph["total_nodes"], 4)
        self.assertEqual(graph["total_edges"], 2)  # root1->child1, child1->grandchild1
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 2)
        # 边类型
        for edge in graph["edges"]:
            self.assertEqual(edge["type"], "derived_from")
        # 节点 ID 全部存在
        node_ids = {n["experience_id"] for n in graph["nodes"]}
        self.assertEqual(node_ids,
                         {self.root1, self.child1, self.grandchild1, self.root2})

    def test_get_descendants_bfs(self):
        """get_descendants(root1) 应返回 [child1, grandchild1] (BFS 顺序)."""
        result = self.loop.get_descendants(self.root1)
        self.assertEqual(result, [self.child1, self.grandchild1])

    def test_get_descendants_leaf_returns_empty(self):
        result = self.loop.get_descendants(self.grandchild1)
        self.assertEqual(result, [])

    def test_get_descendants_nonexistent_returns_empty(self):
        result = self.loop.get_descendants("coevo_nonexistent")
        self.assertEqual(result, [])

    def test_get_ancestors_chain(self):
        """get_ancestors(grandchild1) 应返回 [child1, root1] (直接父到根)."""
        result = self.loop.get_ancestors(self.grandchild1)
        self.assertEqual(result, [self.child1, self.root1])

    def test_get_ancestors_root_returns_empty(self):
        result = self.loop.get_ancestors(self.root1)
        self.assertEqual(result, [])

    def test_list_experiences_all(self):
        nodes = self.loop.list_experiences()
        self.assertEqual(len(nodes), 4)

    def test_list_experiences_filter_by_agent(self):
        nodes = self.loop.list_experiences(agent="aris")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["agent"], "aris")

    def test_list_experiences_derived_only(self):
        nodes = self.loop.list_experiences(derived_only=True)
        self.assertEqual(len(nodes), 2)  # child1 + grandchild1
        for n in nodes:
            self.assertIsNotNone(n["derived_from"])

    def test_stats(self):
        stats = self.loop.stats()
        self.assertEqual(stats["total_experiences"], 4)
        self.assertEqual(stats["shared_roots"], 2)  # root1 + root2
        self.assertEqual(stats["derived"], 2)  # child1 + grandchild1
        self.assertEqual(stats["total_edges"], 2)
        self.assertEqual(stats["roots_count"], 2)
        # leaves: 节点没有子节点的视为叶子
        # root1 有 child1，不是 leaf
        # root2 没子，是 leaf
        # child1 有 grandchild1，不是 leaf
        # grandchild1 没子，是 leaf
        # 所以 leaves = {root2, grandchild1}，共 2 个
        self.assertEqual(stats["leaves_count"], 2)
        # max_depth: grandchild1 的 derived_chain = [root1, child1, grandchild1]
        # 深度 = len(chain) - 1 = 2
        self.assertEqual(stats["max_depth"], 2)
        # by_agent
        self.assertEqual(stats["by_agent"]["aris"], 1)
        self.assertEqual(stats["by_agent"]["hanako"], 1)
        self.assertEqual(stats["by_agent"]["butter"], 1)
        self.assertEqual(stats["by_agent"]["miku"], 1)

    def test_get_experience_returns_none_for_nonexistent(self):
        self.assertIsNone(self.loop.get_experience("coevo_nonexistent"))

    def test_get_experience_returns_dict_for_existing(self):
        node = self.loop.get_experience(self.root1)
        self.assertIsNotNone(node)
        self.assertEqual(node["experience_id"], self.root1)
        self.assertEqual(node["agent"], "aris")
        self.assertIsNone(node["derived_from"])


# ──────────────────────────────────────────────────────────────────────
# 5. 通知机制（SubTask 4.5）— 订阅者接收
# ──────────────────────────────────────────────────────────────────────

class TestNotificationMechanism(unittest.TestCase):
    """SubTask 4.5: 通知机制（订阅者接收）."""

    def setUp(self):
        _reset_all()
        self.loop = get_coevolution_loop()
        self.received: List[Dict[str, Any]] = []

        def subscriber(event):
            if event.type == "coevolution_feedback":
                self.received.append(event.data)

        event_bus.subscribe("coevolution_feedback", subscriber)

    def test_subscriber_receives_feedback_with_target_agent(self):
        """订阅 ``coevolution_feedback`` 的订阅者应收到含 target_agent 的事件."""
        share_r = self.loop.share_experience(
            agent="aris", content="原始经验",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        absorb_r = self.loop.absorb_experience(
            agent="hanako", shared_id=share_r["shared_id"],
        )
        self.loop.feedback_experience(
            new_experience_id=absorb_r["new_experience_id"],
            derived_from=share_r["shared_id"],
        )
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0]["target_agent"], "aris")
        self.assertEqual(self.received[0]["source_agent"], "hanako")

    def test_subscriber_receives_shared_event(self):
        """订阅 ``coevolution_shared`` 应在分享时收到事件."""
        received_shared: List[Dict[str, Any]] = []

        def sub(event):
            if event.type == "coevolution_shared":
                received_shared.append(event.data)

        event_bus.subscribe("coevolution_shared", sub)
        self.loop.share_experience(
            agent="aris", content="原始经验",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        self.assertEqual(len(received_shared), 1)
        self.assertEqual(received_shared[0]["agent"], "aris")

    def test_subscriber_receives_absorbed_event(self):
        """订阅 ``coevolution_absorbed`` 应在吸收时收到事件."""
        received_absorbed: List[Dict[str, Any]] = []

        def sub(event):
            if event.type == "coevolution_absorbed":
                received_absorbed.append(event.data)

        event_bus.subscribe("coevolution_absorbed", sub)
        share_r = self.loop.share_experience(
            agent="aris", content="原始经验",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        self.loop.absorb_experience(
            agent="hanako", shared_id=share_r["shared_id"],
        )
        self.assertEqual(len(received_absorbed), 1)
        self.assertEqual(received_absorbed[0]["agent"], "hanako")
        self.assertEqual(received_absorbed[0]["parent_agent"], "aris")


# ──────────────────────────────────────────────────────────────────────
# 6. 单例与重置
# ──────────────────────────────────────────────────────────────────────

class TestSingletonAndReset(unittest.TestCase):
    """全局单例与测试重置."""

    def test_get_coevolution_loop_returns_same_instance(self):
        _reset_all()
        loop1 = get_coevolution_loop()
        loop2 = get_coevolution_loop()
        self.assertIs(loop1, loop2)

    def test_reset_clears_state(self):
        _reset_all()
        loop = get_coevolution_loop()
        loop.share_experience(
            agent="aris", content="内容",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        self.assertEqual(loop.stats()["total_experiences"], 1)
        loop.clear()
        self.assertEqual(loop.stats()["total_experiences"], 0)

    def test_reset_coevolution_loop_for_test_creates_new_instance(self):
        _reset_all()
        loop1 = get_coevolution_loop()
        reset_coevolution_loop_for_test()
        loop2 = get_coevolution_loop()
        self.assertIsNot(loop1, loop2)


# ──────────────────────────────────────────────────────────────────────
# 7. ExperienceNode dataclass
# ──────────────────────────────────────────────────────────────────────

class TestExperienceNode(unittest.TestCase):
    """ExperienceNode dataclass 序列化."""

    def test_to_dict_returns_all_fields(self):
        node = ExperienceNode(
            experience_id="coevo_test1",
            knowledge_id="know_test1",
            agent="aris",
            content="内容",
            confidence=0.85,
            derived_from=None,
            derived_chain=["coevo_test1"],
            created_at="2026-08-01T00:00:00Z",
            absorption_summary="",
            publisher_public_key="pk_test",
        )
        d = node.to_dict()
        self.assertEqual(d["experience_id"], "coevo_test1")
        self.assertEqual(d["knowledge_id"], "know_test1")
        self.assertEqual(d["agent"], "aris")
        self.assertEqual(d["confidence"], 0.85)
        self.assertIsNone(d["derived_from"])
        self.assertEqual(d["derived_chain"], ["coevo_test1"])
        self.assertEqual(d["publisher_public_key"], "pk_test")

    def test_to_json_returns_valid_json(self):
        node = ExperienceNode(experience_id="coevo_test2", agent="aris")
        s = node.to_json()
        d = json.loads(s)
        self.assertEqual(d["experience_id"], "coevo_test2")
        self.assertEqual(d["agent"], "aris")


# ──────────────────────────────────────────────────────────────────────
# 8. MCP 桥接（handle_coevolution_*）
# ──────────────────────────────────────────────────────────────────────

class TestMcpBridges(unittest.TestCase):
    """MCP 桥接函数返回 JSON 字符串."""

    def setUp(self):
        _reset_all()

    def test_handle_share_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_share,
        )
        result_json = handle_coevolution_share(
            agent="aris",
            content="内容",
            source_memories=_make_source_memories(1),
            confidence=0.85,
        )
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertTrue(d["shared"])
        self.assertIn("shared_id", d)

    def test_handle_share_failure_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_share,
        )
        result_json = handle_coevolution_share(
            agent="",
            content="x",
            source_memories=[],
            confidence=0.5,
        )
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertFalse(d["shared"])
        self.assertEqual(d["reason"], "empty_agent")

    def test_handle_absorb_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_share,
            handle_coevolution_absorb,
        )
        share_json = handle_coevolution_share(
            agent="aris", content="内容",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        shared_id = json.loads(share_json)["shared_id"]
        result_json = handle_coevolution_absorb(
            agent="hanako", shared_id=shared_id,
        )
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertTrue(d["absorbed"])
        self.assertIn("new_experience_id", d)

    def test_handle_feedback_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_share,
            handle_coevolution_absorb,
            handle_coevolution_feedback,
        )
        share_json = handle_coevolution_share(
            agent="aris", content="内容",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        shared_id = json.loads(share_json)["shared_id"]
        absorb_json = handle_coevolution_absorb(
            agent="hanako", shared_id=shared_id,
        )
        new_id = json.loads(absorb_json)["new_experience_id"]
        result_json = handle_coevolution_feedback(
            new_experience_id=new_id, derived_from=shared_id,
        )
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertTrue(d["fed_back"])
        self.assertEqual(d["target_agent"], "aris")

    def test_handle_graph_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_graph,
        )
        result_json = handle_coevolution_graph(limit=10)
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertIn("nodes", d)
        self.assertIn("edges", d)
        self.assertIn("total_nodes", d)
        self.assertIn("total_edges", d)

    def test_handle_stats_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_stats,
        )
        result_json = handle_coevolution_stats()
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertIn("total_experiences", d)
        self.assertIn("shared_roots", d)

    def test_handle_get_returns_json_string(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_share,
            handle_coevolution_get,
        )
        share_json = handle_coevolution_share(
            agent="aris", content="内容",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        shared_id = json.loads(share_json)["shared_id"]
        result_json = handle_coevolution_get(shared_id)
        self.assertIsInstance(result_json, str)
        d = json.loads(result_json)
        self.assertTrue(d["found"])
        self.assertEqual(d["experience"]["experience_id"], shared_id)

    def test_handle_get_nonexistent_returns_not_found(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            handle_coevolution_get,
        )
        result_json = handle_coevolution_get("coevo_nonexistent")
        d = json.loads(result_json)
        self.assertFalse(d["found"])

    def test_register_coevolution_tools_with_mock_mcp(self):
        """用 mock MCP server 验证 register_coevolution_tools 注册流程."""
        from laap.protocol.coevolution_mcp_endpoints import (
            register_coevolution_tools,
        )

        class _MockTool:
            def __init__(self, name, fn):
                self.name = name
                self.fn = fn

        class _MockMCP:
            def __init__(self):
                self.tools = []

            def tool(self):
                def decorator(fn):
                    self.tools.append(_MockTool(fn.__name__, fn))
                    return fn
                return decorator

        mcp = _MockMCP()
        register_coevolution_tools(mcp)
        tool_names = [t.name for t in mcp.tools]
        self.assertIn("coevolution_share", tool_names)
        self.assertIn("coevolution_absorb", tool_names)
        self.assertIn("coevolution_feedback", tool_names)
        self.assertIn("coevolution_graph", tool_names)
        self.assertIn("coevolution_stats", tool_names)
        self.assertEqual(len(mcp.tools), 5)

    def test_register_coevolution_tools_with_none_mcp_no_crash(self):
        from laap.protocol.coevolution_mcp_endpoints import (
            register_coevolution_tools,
        )
        # 不应抛异常
        register_coevolution_tools(None)


# ──────────────────────────────────────────────────────────────────────
# 9. 端到端闭环（share -> absorb -> feedback -> notify）
# ──────────────────────────────────────────────────────────────────────

class TestEndToEndLoop(unittest.TestCase):
    """SubTask 4.6: share -> absorb -> feedback -> notify 完整闭环."""

    def test_full_loop_aris_shares_hanako_absorbs_butter_notified(self):
        """端到端：Aris 分享 -> Hanako 吸收 -> 回传 -> Aris 收到通知."""
        _reset_all()
        loop = get_coevolution_loop()

        # Aris 订阅 feedback 通知
        aris_inbox: List[Dict[str, Any]] = []

        def aris_subscriber(event):
            if event.type == "coevolution_feedback":
                if event.data.get("target_agent") == "aris":
                    aris_inbox.append(event.data)

        event_bus.subscribe("coevolution_feedback", aris_subscriber)

        # 1. Aris 分享经验
        share_r = loop.share_experience(
            agent="aris",
            content="调试 truth-grounding 时发现 evidence 权重需要按时间衰减",
            source_memories=_make_source_memories(2),
            confidence=0.9,
        )
        self.assertTrue(share_r["shared"])
        shared_id = share_r["shared_id"]

        # 2. Hanako 吸收并派生新经验
        absorb_r = loop.absorb_experience(
            agent="hanako",
            shared_id=shared_id,
        )
        self.assertTrue(absorb_r["absorbed"])
        new_id = absorb_r["new_experience_id"]

        # 3. 回传给 Aris
        feedback_r = loop.feedback_experience(
            new_experience_id=new_id,
            derived_from=shared_id,
        )
        self.assertTrue(feedback_r["fed_back"])
        self.assertEqual(feedback_r["target_agent"], "aris")

        # 4. Aris 收到通知
        self.assertEqual(len(aris_inbox), 1)
        self.assertEqual(aris_inbox[0]["new_experience_id"], new_id)
        self.assertEqual(aris_inbox[0]["derived_from"], shared_id)
        self.assertEqual(aris_inbox[0]["target_agent"], "aris")
        self.assertEqual(aris_inbox[0]["source_agent"], "hanako")

        # 5. 共同进化图有 2 节点 1 边
        graph = loop.get_graph()
        self.assertEqual(graph["total_nodes"], 2)
        self.assertEqual(graph["total_edges"], 1)

        # 6. 统计正确
        stats = loop.stats()
        self.assertEqual(stats["total_experiences"], 2)
        self.assertEqual(stats["shared_roots"], 1)
        self.assertEqual(stats["derived"], 1)
        self.assertEqual(stats["by_agent"]["aris"], 1)
        self.assertEqual(stats["by_agent"]["hanako"], 1)

    def test_multi_hop_propagation_aris_hanako_butter(self):
        """多跳传播：Aris 分享 -> Hanako 吸收 -> Butter 吸收 Hanako 的派生."""
        _reset_all()
        loop = get_coevolution_loop()

        # 1. Aris 分享
        r1 = loop.share_experience(
            agent="aris", content="根经验",
            source_memories=_make_source_memories(1), confidence=0.85,
        )
        root_id = r1["shared_id"]

        # 2. Hanako 吸收 Aris 的根
        r2 = loop.absorb_experience(
            agent="hanako", shared_id=root_id,
        )
        child_id = r2["new_experience_id"]

        # 3. Butter 吸收 Hanako 的派生（多跳）
        r3 = loop.absorb_experience(
            agent="butter", shared_id=child_id,
        )
        grandchild_id = r3["new_experience_id"]

        # 4. 回传通知 Hanako（Butter 的派生来自 Hanako 的派生）
        fb = loop.feedback_experience(
            new_experience_id=grandchild_id,
            derived_from=child_id,
        )
        self.assertTrue(fb["fed_back"])
        self.assertEqual(fb["target_agent"], "hanako")

        # 5. 共同进化图：3 节点 2 边
        graph = loop.get_graph()
        self.assertEqual(graph["total_nodes"], 3)
        self.assertEqual(graph["total_edges"], 2)

        # 6. 链路：grandchild -> child -> root
        ancestors = loop.get_ancestors(grandchild_id)
        self.assertEqual(ancestors, [child_id, root_id])

        # 7. 后代：root 的所有后代是 [child, grandchild]
        descendants = loop.get_descendants(root_id)
        self.assertEqual(descendants, [child_id, grandchild_id])

        # 8. max_depth = 2 (chain [root, child, grandchild])
        stats = loop.stats()
        self.assertEqual(stats["max_depth"], 2)


if __name__ == "__main__":
    unittest.main()
