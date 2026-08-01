"""LAAP — Memex 共享知识库测试 (P4-memex SubTask 4.7)

================================================================
  测试去标识化、证据链、低置信过滤、grounding 复核
================================================================

覆盖 spec SubTask 4.7 的全部场景：

* 去标识化：用户名/时间戳/实例ID/个人代词
* 证据链：memory_id 哈希、置信度、校验时间
* 低置信过滤：``confidence < 0.6`` 直接拒绝
* grounding 复核：rejected 时拒绝，uncertain 放行
* publish + query 闭环
* 幂等：同一 (content, evidence_chain) 二次发布返回同一 knowledge_id
* 签名验证：Ed25519 签名 + 验证
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

# 确保 laap 包可导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_LAAP_ROOT = os.path.dirname(_HERE)
if _LAAP_ROOT not in sys.path:
    sys.path.insert(0, _LAAP_ROOT)

from laap.protocol.laap_memex import (  # noqa: E402
    MEMEX_MIN_CONFIDENCE,
    KnowledgeRecord,
    MemexStore,
    attach_evidence,
    deidentify,
    get_memex_store,
    publish_knowledge,
    reset_memex_store_for_test,
)
from laap.verification.memex_verifier import (  # noqa: E402
    verify_before_publish,
    verify_batch,
)


# ──────────────────────────────────────────────────────────────────────
# 1. 去标识化测试
# ──────────────────────────────────────────────────────────────────────

class TestDeidentify(unittest.TestCase):
    """SubTask 4.3: 去标识化."""

    def test_chinese_username_replaced(self):
        """中文用户名/标签应被替换为 [user]."""
        content = "用户Lorry今天和Aris讨论了架构问题"
        result = deidentify(content)
        self.assertNotIn("Lorry", result)
        self.assertNotIn("Aris", result)
        self.assertIn("[user]", result)
        # 保留实质内容
        self.assertIn("架构", result)

    def test_at_mention_replaced(self):
        """@mention 应被替换为 [user]."""
        content = "@alice 你好，@bob 也来看看"
        result = deidentify(content)
        self.assertNotIn("@alice", result)
        self.assertNotIn("@bob", result)
        self.assertIn("[user]", result)

    def test_user_tag_replaced(self):
        """<user:xxx> 应被替换为 [user]."""
        content = "<user:charlie>说了一句重要的话"
        result = deidentify(content)
        self.assertNotIn("<user:charlie>", result)
        self.assertIn("[user]", result)
        self.assertIn("重要", result)

    def test_iso_timestamp_replaced(self):
        """ISO 8601 时间戳应被替换为 [timestamp]."""
        content = "在 2024-01-15T14:30:22Z 这个时刻发生了重要事件"
        result = deidentify(content)
        self.assertNotIn("2024-01-15T14:30:22Z", result)
        self.assertIn("[timestamp]", result)
        self.assertIn("重要事件", result)

    def test_date_replaced(self):
        """日期应被替换为 [timestamp]."""
        content = "2024年1月15日 是个特殊的日子"
        result = deidentify(content)
        self.assertNotIn("2024年1月15日", result)
        self.assertIn("[timestamp]", result)

    def test_uuid_replaced(self):
        """UUID 应被替换为 [id]."""
        content = "会话 550e8400-e29b-41d4-a716-446655440000 已结束"
        result = deidentify(content)
        self.assertNotIn("550e8400-e29b-41d4-a716-446655440000", result)
        self.assertIn("[id]", result)

    def test_memory_id_replaced(self):
        """mem_xxx 应被替换为 [id]."""
        content = "来源记忆 mem_abc123def456 提到这件事"
        result = deidentify(content)
        self.assertNotIn("mem_abc123def456", result)
        self.assertIn("[id]", result)

    def test_did_replaced(self):
        """did:laap:xxx 应被替换为 [id]."""
        content = "身份 did:laap:abcdef1234567890 已注册"
        result = deidentify(content)
        self.assertNotIn("did:laap:abcdef1234567890", result)
        self.assertIn("[id]", result)

    def test_chinese_pronouns_replaced(self):
        """中文个人代词应被替换为 [user]."""
        content = "我今天去看了电影，我的朋友也去了，我们很开心"
        result = deidentify(content)
        self.assertNotIn("我", result)
        self.assertIn("[user]", result)

    def test_english_pronouns_replaced(self):
        """英文个人代词（单词边界）应被替换为 [user]."""
        content = "I think this is important for my work"
        result = deidentify(content)
        # important 中的 "I" 不应被替换（单词边界）
        self.assertIn("important", result)
        # 独立的 I / my 应被替换
        self.assertNotIn(" I ", " " + result + " ")

    def test_english_pronoun_no_false_positive(self):
        """important / iron / main 中的代词子串不应被误伤."""
        content = "This is important information, mainly about iron."
        result = deidentify(content)
        self.assertIn("important", result)
        self.assertIn("iron", result)
        # "mainly" 含 "main" 不含代词，但 "mainly" 不在代词列表
        self.assertIn("mainly", result)

    def test_idempotent(self):
        """对已去标识化内容二次调用不应产生额外变化."""
        content = "用户Lorry在2024-01-15说了重要的话"
        first = deidentify(content)
        second = deidentify(first)
        self.assertEqual(first, second)

    def test_empty_input(self):
        """空输入应返回空字符串."""
        self.assertEqual(deidentify(""), "")
        self.assertEqual(deidentify(None), "")
        self.assertEqual(deidentify(123), "")


# ──────────────────────────────────────────────────────────────────────
# 2. 证据链测试
# ──────────────────────────────────────────────────────────────────────

class TestAttachEvidence(unittest.TestCase):
    """SubTask 4.4: 证据链附加."""

    def test_basic_evidence_chain(self):
        """基本证据链应含 memory_id_hash + 校验时间."""
        sources = [
            {"memory_id": "mem_abc123", "confidence": 0.8, "scope": "episodic"},
            {"memory_id": "mem_def456", "confidence": 0.7, "scope": "semantic"},
        ]
        result = attach_evidence("test content", sources, confidence=0.75)
        self.assertEqual(result["content"], "test content")
        self.assertEqual(len(result["evidence_chain"]), 2)
        self.assertEqual(result["confidence"], 0.75)
        self.assertIn("verified_at", result)
        # memory_id 应被哈希（不直接暴露）
        entry0 = result["evidence_chain"][0]
        self.assertIn("memory_id_hash", entry0)
        self.assertNotIn("mem_abc123", entry0["memory_id_hash"])
        self.assertEqual(len(entry0["memory_id_hash"]), 16)
        self.assertEqual(entry0["source_confidence"], 0.8)
        self.assertEqual(entry0["scope"], "episodic")

    def test_empty_sources(self):
        """空来源列表应返回空 evidence_chain."""
        result = attach_evidence("content", [], confidence=0.7)
        self.assertEqual(result["evidence_chain"], [])
        self.assertEqual(result["confidence"], 0.7)

    def test_missing_memory_id_skipped(self):
        """缺 memory_id 的项应被跳过."""
        sources = [
            {"memory_id": "mem_abc123"},
            {"confidence": 0.8},  # 无 memory_id
            {"memory_id": ""},    # 空 memory_id
            "not a dict",
        ]
        result = attach_evidence("content", sources, confidence=0.7)
        self.assertEqual(len(result["evidence_chain"]), 1)

    def test_confidence_normalization(self):
        """置信度应被归一化到 [0, 1]."""
        result = attach_evidence("c", [], confidence=1.5)
        self.assertEqual(result["confidence"], 1.0)
        result = attach_evidence("c", [], confidence=-0.5)
        self.assertEqual(result["confidence"], 0.0)

    def test_memory_id_hash_stable(self):
        """同一 memory_id 应产生同一哈希."""
        sources = [{"memory_id": "mem_abc123"}]
        r1 = attach_evidence("c", sources, confidence=0.7)
        r2 = attach_evidence("c", sources, confidence=0.7)
        self.assertEqual(
            r1["evidence_chain"][0]["memory_id_hash"],
            r2["evidence_chain"][0]["memory_id_hash"],
        )


# ──────────────────────────────────────────────────────────────────────
# 3. MemexStore 测试
# ──────────────────────────────────────────────────────────────────────

class TestMemexStore(unittest.TestCase):
    """SubTask 4.2: MemexStore publish/query."""

    def setUp(self):
        reset_memex_store_for_test()
        self.store = get_memex_store()

    def tearDown(self):
        self.store.clear()
        reset_memex_store_for_test()

    def _make_grounding_ok(self):
        """构造一个通过的 grounding_result."""
        return {
            "verified": True,
            "reason": "grounded",
            "grounding": {
                "state": "grounded",
                "confidence": 0.85,
                "evidence": ["test"],
                "rejected": False,
            },
            "verified_at": "2026-08-01T00:00:00Z",
        }

    def test_publish_success(self):
        """高置信 + grounding 通过 → 发布成功."""
        result = self.store.publish(
            content="去标识化后的知识内容",
            evidence_chain=[{"memory_id_hash": "abc123def4567890"}],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertTrue(result["published"])
        self.assertIn("knowledge_id", result)
        self.assertNotIn("reason", result)

    def test_publish_low_confidence_rejected(self):
        """低置信 (< 0.6) → 拒绝. (SubTask 4.5)"""
        result = self.store.publish(
            content="低置信内容",
            evidence_chain=[{"memory_id_hash": "abc123def4567890"}],
            confidence=0.4,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "low_confidence")

    def test_publish_grounding_rejected(self):
        """grounding rejected → 拒绝. (SubTask 4.6)"""
        grounding = {
            "verified": False,
            "reason": "grounding_rejected",
            "grounding": {
                "state": "error",
                "confidence": 0.1,
                "evidence": ["conflict"],
                "rejected": True,
                "conflicts": ["fact mismatch"],
            },
            "verified_at": "2026-08-01T00:00:00Z",
        }
        result = self.store.publish(
            content="有冲突的内容",
            evidence_chain=[{"memory_id_hash": "abc123def4567890"}],
            confidence=0.85,
            grounding_result=grounding,
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "grounding_rejected")

    def test_publish_empty_content_rejected(self):
        """空内容 → 拒绝."""
        result = self.store.publish(
            content="",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "empty_content")

    def test_publish_empty_evidence_rejected(self):
        """空证据链 → 拒绝."""
        result = self.store.publish(
            content="有效内容",
            evidence_chain=[],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "empty_evidence")

    def test_publish_grounding_missing_rejected(self):
        """无 grounding_result → 拒绝."""
        result = self.store.publish(
            content="有效内容",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            grounding_result=None,
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "grounding_missing")

    def test_publish_idempotent(self):
        """同一 (content, evidence_chain) 二次发布返回同一 knowledge_id."""
        evidence = [{"memory_id_hash": "abc123def4567890"}]
        r1 = self.store.publish(
            content="幂等测试内容",
            evidence_chain=evidence,
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        r2 = self.store.publish(
            content="幂等测试内容",
            evidence_chain=evidence,
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertTrue(r1["published"])
        self.assertTrue(r2["published"])
        self.assertEqual(r1["knowledge_id"], r2["knowledge_id"])
        self.assertTrue(r2.get("idempotent"))

    def test_query_by_keyword(self):
        """发布后可通过关键词检索."""
        self.store.publish(
            content="React Hooks 的状态管理最佳实践",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        results = self.store.query("React Hooks", top_k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("React", results[0]["content"])

    def test_query_min_confidence_filter(self):
        """min_confidence 过滤生效."""
        self.store.publish(
            content="高置信知识",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.95,
            grounding_result=self._make_grounding_ok(),
        )
        self.store.publish(
            content="中置信知识",
            evidence_chain=[{"memory_id_hash": "def"}],
            confidence=0.65,
            grounding_result=self._make_grounding_ok(),
        )
        results = self.store.query("知识", top_k=10, min_confidence=0.9)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["confidence"], 0.95)

    def test_get_by_id(self):
        """按 knowledge_id 查询单条记录."""
        pub = self.store.publish(
            content="按ID查询的内容",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        kid = pub["knowledge_id"]
        record = self.store.get(kid)
        self.assertIsNotNone(record)
        self.assertEqual(record["knowledge_id"], kid)
        self.assertEqual(record["content"], "按ID查询的内容")

    def test_get_nonexistent(self):
        """查询不存在的 ID 返回 None."""
        self.assertIsNone(self.store.get("know_nonexistent"))

    def test_list_all(self):
        """list_all 返回所有记录."""
        for i in range(3):
            self.store.publish(
                content=f"知识内容 {i}",
                evidence_chain=[{"memory_id_hash": f"hash{i}"}],
                confidence=0.85,
                grounding_result=self._make_grounding_ok(),
            )
        records = self.store.list_all()
        self.assertEqual(len(records), 3)

    def test_stats(self):
        """stats 返回统计信息."""
        self.store.publish(
            content="统计测试",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            grounding_result=self._make_grounding_ok(),
        )
        stats = self.store.stats()
        self.assertEqual(stats["total_records"], 1)
        self.assertEqual(stats["min_confidence_threshold"], MEMEX_MIN_CONFIDENCE)
        self.assertIn("by_grounding_state", stats)
        self.assertGreaterEqual(stats["avg_confidence"], 0.0)

    def test_publish_with_signature(self):
        """带签名的发布可被验证."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("cryptography not available")

        sk = Ed25519PrivateKey.generate()
        pub_bytes = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        pub_b64 = __import__("base64").b64encode(pub_bytes).decode("ascii")
        sk_bytes = sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        result = self.store.publish(
            content="签名测试内容",
            evidence_chain=[{"memory_id_hash": "abc"}],
            confidence=0.85,
            publisher_public_key=pub_b64,
            publisher_private_key=sk_bytes,
            grounding_result=self._make_grounding_ok(),
        )
        self.assertTrue(result["published"])
        kid = result["knowledge_id"]

        # 验证签名
        self.assertTrue(self.store.verify_record_signature(kid))

        # 篡改后应失败
        with self.store._lock:
            rec = self.store._records[kid]
            rec.content = "篡改后的内容"
        self.assertFalse(self.store.verify_record_signature(kid))


# ──────────────────────────────────────────────────────────────────────
# 4. MemexVerifier 测试
# ──────────────────────────────────────────────────────────────────────

class TestMemexVerifier(unittest.TestCase):
    """SubTask 4.6: 发布前复核."""

    def test_low_confidence_rejected(self):
        """低置信 → 拒绝，不触发 grounding."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding"
        ) as mock_g:
            result = verify_before_publish(
                content="测试内容",
                confidence=0.3,
                agent_name="aris",
            )
            self.assertFalse(result["verified"])
            self.assertEqual(result["reason"], "low_confidence")
            # grounding 不应被调用
            mock_g.assert_not_called()

    def test_empty_content_rejected(self):
        """空内容 → 拒绝."""
        result = verify_before_publish(
            content="",
            confidence=0.85,
            agent_name="aris",
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "empty_content")

    def test_grounding_rejected(self):
        """grounding error 态 → 拒绝."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "error",
                "confidence": 0.1,
                "evidence": ["conflict"],
                "rejected": True,
                "conflicts": ["fact mismatch"],
            },
        ):
            result = verify_before_publish(
                content="有冲突的内容",
                confidence=0.85,
                agent_name="aris",
            )
            self.assertFalse(result["verified"])
            self.assertEqual(result["reason"], "grounding_rejected")
            self.assertEqual(result["grounding"]["state"], "error")

    def test_grounding_grounded(self):
        """grounding grounded 态 → 通过."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["verified"],
                "rejected": False,
            },
        ):
            result = verify_before_publish(
                content="可信内容",
                confidence=0.85,
                agent_name="aris",
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["reason"], "grounded")

    def test_grounding_uncertain_passthrough(self):
        """grounding uncertain 态 → 放行但记录."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "uncertain",
                "confidence": 0.5,
                "evidence": ["no_evidence"],
                "rejected": False,
            },
        ):
            result = verify_before_publish(
                content="不确定内容",
                confidence=0.7,
                agent_name="aris",
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["reason"], "uncertain_passthrough")
            self.assertEqual(result["grounding"]["state"], "uncertain")

    def test_grounding_engine_unavailable_passthrough(self):
        """grounding 引擎不可用 → 降级 uncertain 放行."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "uncertain",
                "confidence": 0.0,
                "evidence": ["grounding_module_unavailable"],
                "rejected": False,
            },
        ):
            result = verify_before_publish(
                content="引擎不可用的内容",
                confidence=0.7,
                agent_name="aris",
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["reason"], "uncertain_passthrough")

    def test_batch_verify(self):
        """批量复核."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["ok"],
                "rejected": False,
            },
        ):
            items = [
                {"content": "内容1", "confidence": 0.85},
                {"content": "", "confidence": 0.85},
                {"content": "内容3", "confidence": 0.3},
            ]
            results = verify_batch(items, agent_name="aris")
            self.assertEqual(len(results), 3)
            self.assertTrue(results[0]["verified"])
            self.assertFalse(results[1]["verified"])
            self.assertEqual(results[1]["reason"], "empty_content")
            self.assertFalse(results[2]["verified"])
            self.assertEqual(results[2]["reason"], "low_confidence")


# ──────────────────────────────────────────────────────────────────────
# 5. 端到端 publish_knowledge 测试
# ──────────────────────────────────────────────────────────────────────

class TestPublishKnowledgeE2E(unittest.TestCase):
    """端到端 publish_knowledge 流水线."""

    def setUp(self):
        reset_memex_store_for_test()
        self.store = get_memex_store()

    def tearDown(self):
        self.store.clear()
        reset_memex_store_for_test()

    def test_e2e_with_mocked_grounding(self):
        """端到端：去标识化 → 证据链 → 复核 → 存储（mocked grounding）."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["verified"],
                "rejected": False,
            },
        ):
            result = publish_knowledge(
                content="用户Lorry在2024-01-15发现了一个重要的架构模式",
                source_memories=[
                    {"memory_id": "mem_abc123", "confidence": 0.85,
                     "scope": "episodic"},
                ],
                confidence=0.85,
                agent_name="aris",
            )
        self.assertTrue(result["published"])
        self.assertIn("knowledge_id", result)
        # 验证内容已被去标识化
        record = self.store.get(result["knowledge_id"])
        self.assertNotIn("Lorry", record["content"])
        self.assertNotIn("2024-01-15", record["content"])
        self.assertIn("[user]", record["content"])
        self.assertIn("[timestamp]", record["content"])
        # 验证证据链已附加
        self.assertEqual(len(record["evidence_chain"]), 1)
        self.assertIn("memory_id_hash", record["evidence_chain"][0])

    def test_e2e_low_confidence_rejected(self):
        """端到端低置信拒绝."""
        result = publish_knowledge(
            content="低置信内容",
            source_memories=[{"memory_id": "mem_abc"}],
            confidence=0.4,
            agent_name="aris",
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "low_confidence")

    def test_e2e_grounding_rejected(self):
        """端到端 grounding 拒绝."""
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "error",
                "confidence": 0.1,
                "evidence": ["conflict"],
                "rejected": True,
                "conflicts": ["fact mismatch"],
            },
        ):
            result = publish_knowledge(
                content="有冲突的内容",
                source_memories=[{"memory_id": "mem_abc"}],
                confidence=0.85,
                agent_name="aris",
            )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "grounding_rejected")
        self.assertIn("deidentified_content", result)
        self.assertIn("grounding", result)

    def test_e2e_skip_grounding(self):
        """skip_grounding=True 时跳过复核（仅测试用）."""
        result = publish_knowledge(
            content="跳过复核的内容",
            source_memories=[{"memory_id": "mem_abc"}],
            confidence=0.85,
            agent_name="aris",
            skip_grounding=True,
        )
        self.assertTrue(result["published"])
        self.assertIn("knowledge_id", result)

    def test_e2e_empty_after_deidentify(self):
        """去标识化后内容为空 → 拒绝."""
        # 纯空白输入，去标识化后为空字符串
        result = publish_knowledge(
            content="   ",
            source_memories=[{"memory_id": "mem_abc"}],
            confidence=0.85,
            agent_name="aris",
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "empty_after_deidentify")


# ──────────────────────────────────────────────────────────────────────
# 6. KnowledgeRecord 测试
# ──────────────────────────────────────────────────────────────────────

class TestKnowledgeRecord(unittest.TestCase):
    """KnowledgeRecord dataclass."""

    def test_content_fingerprint_stable(self):
        """同一 (content, evidence_chain) 指纹一致."""
        r1 = KnowledgeRecord(content="abc", evidence_chain=[{"h": "1"}])
        r2 = KnowledgeRecord(content="abc", evidence_chain=[{"h": "1"}])
        self.assertEqual(r1.content_fingerprint(), r2.content_fingerprint())

    def test_content_fingerprint_differs_on_content(self):
        """不同 content 指纹不同."""
        r1 = KnowledgeRecord(content="abc", evidence_chain=[])
        r2 = KnowledgeRecord(content="abd", evidence_chain=[])
        self.assertNotEqual(r1.content_fingerprint(), r2.content_fingerprint())

    def test_content_fingerprint_differs_on_evidence(self):
        """不同 evidence_chain 指纹不同."""
        r1 = KnowledgeRecord(content="abc", evidence_chain=[{"h": "1"}])
        r2 = KnowledgeRecord(content="abc", evidence_chain=[{"h": "2"}])
        self.assertNotEqual(r1.content_fingerprint(), r2.content_fingerprint())

    def test_round_trip(self):
        """to_dict / from_dict 往返."""
        r = KnowledgeRecord(
            knowledge_id="know_abc",
            content="test",
            evidence_chain=[{"memory_id_hash": "h1"}],
            confidence=0.85,
            publisher_public_key="pk",
            signature="sig",
            grounding_state="grounded",
            grounding_confidence=0.9,
            published_at="2026-08-01T00:00:00Z",
            verified_at="2026-08-01T00:00:00Z",
        )
        d = r.to_dict()
        r2 = KnowledgeRecord.from_dict(d)
        self.assertEqual(r2.knowledge_id, "know_abc")
        self.assertEqual(r2.content, "test")
        self.assertEqual(r2.confidence, 0.85)
        self.assertEqual(r2.grounding_state, "grounded")


# ──────────────────────────────────────────────────────────────────────
# 7. MCP 端点桥接测试
# ──────────────────────────────────────────────────────────────────────

class TestMcpEndpoints(unittest.TestCase):
    """memex_mcp_endpoints 桥接函数."""

    def setUp(self):
        reset_memex_store_for_test()

    def tearDown(self):
        get_memex_store().clear()
        reset_memex_store_for_test()

    def test_handle_publish_success(self):
        """桥接函数发布成功返回 JSON."""
        from laap.protocol.memex_mcp_endpoints import handle_memex_publish
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["ok"],
                "rejected": False,
            },
        ):
            result_json = handle_memex_publish(
                content="测试内容",
                source_memories=[{"memory_id": "mem_abc"}],
                confidence=0.85,
            )
        result = json.loads(result_json)
        self.assertTrue(result["published"])
        self.assertIn("knowledge_id", result)

    def test_handle_publish_low_confidence(self):
        """桥接函数低置信拒绝."""
        from laap.protocol.memex_mcp_endpoints import handle_memex_publish
        result_json = handle_memex_publish(
            content="测试",
            source_memories=[{"memory_id": "mem_abc"}],
            confidence=0.3,
        )
        result = json.loads(result_json)
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "low_confidence")

    def test_handle_query(self):
        """桥接函数查询."""
        from laap.protocol.memex_mcp_endpoints import (
            handle_memex_publish,
            handle_memex_query,
        )
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["ok"],
                "rejected": False,
            },
        ):
            handle_memex_publish(
                content="React 状态管理",
                source_memories=[{"memory_id": "mem_abc"}],
                confidence=0.85,
            )
        result_json = handle_memex_query("React", top_k=5)
        result = json.loads(result_json)
        self.assertEqual(result["count"], 1)
        self.assertIn("React", result["results"][0]["content"])

    def test_handle_verify(self):
        """桥接函数复核."""
        from laap.protocol.memex_mcp_endpoints import handle_memex_verify
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["ok"],
                "rejected": False,
            },
        ):
            result_json = handle_memex_verify(
                content="测试内容",
                confidence=0.85,
            )
        result = json.loads(result_json)
        self.assertTrue(result["verified"])
        self.assertEqual(result["reason"], "grounded")

    def test_handle_stats(self):
        """桥接函数统计."""
        from laap.protocol.memex_mcp_endpoints import handle_memex_stats
        result_json = handle_memex_stats()
        result = json.loads(result_json)
        self.assertIn("total_records", result)
        self.assertIn("min_confidence_threshold", result)

    def test_handle_get(self):
        """桥接函数按 ID 查询."""
        from laap.protocol.memex_mcp_endpoints import (
            handle_memex_publish,
            handle_memex_get,
        )
        with patch(
            "laap.verification.memex_verifier._invoke_grounding",
            return_value={
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["ok"],
                "rejected": False,
            },
        ):
            pub_json = handle_memex_publish(
                content="按ID查",
                source_memories=[{"memory_id": "mem_abc"}],
                confidence=0.85,
            )
        kid = json.loads(pub_json)["knowledge_id"]
        result_json = handle_memex_get(kid)
        result = json.loads(result_json)
        self.assertTrue(result["found"])
        self.assertEqual(result["record"]["knowledge_id"], kid)


if __name__ == "__main__":
    unittest.main()
