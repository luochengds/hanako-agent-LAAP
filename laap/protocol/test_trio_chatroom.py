"""P3-trio-chatroom 冒烟测试 (spec L427).

覆盖 spec tasks.md L111-117 (SubTask 3.2/3.3/3.5/3.6)：
- SubTask 3.2: create_chatroom / post_topic / post_message
- SubTask 3.3: detect_consensus（LLM/规则双路径）
- SubTask 3.5: 共识达成后写 witness_trail_local 表
- SubTask 3.6: 三个本地 LAAPer 实例讨论一个话题，共识检测正确

硬约束：
- pytest 必须带 -p no:quadrants（spec L427）
- clock 注入便于断言
- 不依赖真实 LLM（用规则降级路径验证）
- 私钥永不离开 sidecar（测试用真实 Ed25519 密钥对）
"""

from __future__ import annotations

import json
import time
from typing import List

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from laap.protocol.laap_coop import (
    TrioChatroomManager,
    get_trio_chatroom_manager,
    reset_trio_chatroom_manager_for_test,
    _extract_view_rule,
    _keyword_overlap,
    _tokenize,
)
from laap.protocol.trio_chatroom_mcp_endpoints import (
    handle_trio_create,
    handle_trio_topic,
    handle_trio_message,
    handle_trio_consensus,
    handle_trio_get,
    register_trio_chatroom_tools,
)


# ── 测试夹具 ──────────────────────────────────────────────

def _make_keypair() -> tuple:
    """生成真实 Ed25519 密钥对，返回 (public_key_b64, private_key_bytes)."""
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
    import base64
    return base64.b64encode(pub_bytes).decode("ascii"), priv_bytes


@pytest.fixture
def three_keypairs():
    """三个真实 Ed25519 密钥对（模拟三个 LAAPer 实例）."""
    return [_make_keypair() for _ in range(3)]


@pytest.fixture
def three_public_keys(three_keypairs):
    """三个成员公钥列表."""
    return [pk for pk, _ in three_keypairs]


@pytest.fixture
def manager():
    """重置全局 TrioChatroomManager，注入可控 clock."""
    counter = [0.0]

    def mock_clock():
        counter[0] += 1.0
        return counter[0]

    return reset_trio_chatroom_manager_for_test(clock=mock_clock, agent_name="trio_test")


# ── SubTask 3.2: create_chatroom ──────────────────────────

class TestCreateChatroom:
    def test_create_returns_id_and_member_count(self, manager, three_public_keys):
        """创建三人聊天室返回 chatroom_id 与 member_count=3."""
        result = manager.create_chatroom(three_public_keys)
        assert result["created"] is True
        assert result["member_count"] == 3
        assert result["chatroom_id"].startswith("trio_")
        assert result["created_at"] > 0

    def test_create_idempotent_same_members(self, manager, three_public_keys):
        """同一成员集合二次调用返回同一 chatroom_id（幂等）."""
        r1 = manager.create_chatroom(three_public_keys)
        r2 = manager.create_chatroom(list(reversed(three_public_keys)))
        assert r1["chatroom_id"] == r2["chatroom_id"]
        assert r2["created"] is False

    def test_create_rejects_empty_members(self, manager):
        """空成员列表拒绝."""
        with pytest.raises(ValueError, match=">= 2 members"):
            manager.create_chatroom([])

    def test_create_rejects_too_few_members(self, manager):
        """单个成员拒绝（spec: 三人聊天室）."""
        with pytest.raises(ValueError, match=">= 2 members"):
            manager.create_chatroom(["pk_a"])

    def test_create_rejects_empty_pk(self, manager):
        """含空串公钥拒绝."""
        with pytest.raises(ValueError, match="empty value"):
            manager.create_chatroom(["pk_a", "", "pk_c"])

    def test_create_rejects_duplicates(self, manager):
        """重复公钥拒绝."""
        with pytest.raises(ValueError, match="duplicate"):
            manager.create_chatroom(["pk_a", "pk_a", "pk_b"])

    def test_create_two_members_allowed(self, manager):
        """2 人聊天室也允许（spec 软约束：三人为主，但支持 2-4 人）."""
        result = manager.create_chatroom(["pk_a", "pk_b"])
        assert result["member_count"] == 2


# ── SubTask 3.2: post_topic ───────────────────────────────

class TestPostTopic:
    def test_post_topic_returns_id(self, manager, three_public_keys):
        """发起话题返回 topic_id."""
        room = manager.create_chatroom(three_public_keys)
        result = manager.post_topic(room["chatroom_id"], "是否采纳 RSI 候选 X")
        assert result["topic_id"].startswith("topic_")
        assert result["chatroom_id"] == room["chatroom_id"]
        assert result["title"] == "是否采纳 RSI 候选 X"
        assert result["created_at"] > 0

    def test_post_topic_rejects_empty(self, manager, three_public_keys):
        """空话题拒绝."""
        room = manager.create_chatroom(three_public_keys)
        with pytest.raises(ValueError, match="topic must be non-empty"):
            manager.post_topic(room["chatroom_id"], "")

    def test_post_topic_rejects_unknown_room(self, manager):
        """不存在的聊天室拒绝."""
        with pytest.raises(ValueError, match="chatroom not found"):
            manager.post_topic("trio_unknown", "话题")


# ── SubTask 3.2: post_message ─────────────────────────────

class TestPostMessage:
    def test_post_message_returns_id(self, manager, three_public_keys):
        """发布消息返回 message_id 与 stored=True."""
        room = manager.create_chatroom(three_public_keys)
        result = manager.post_message(
            chatroom_id=room["chatroom_id"],
            content="我同意采纳 RSI 候选 X",
            sender_public_key=three_public_keys[0],
        )
        assert result["stored"] is True
        assert result["message_id"].startswith("tmsg_")
        assert result["chatroom_id"] == room["chatroom_id"]

    def test_post_message_with_envelope(self, manager, three_keypairs):
        """提供 private_key 时产出签名信封（复用 encrypt_channel）."""
        three_public_keys = [pk for pk, _ in three_keypairs]
        room = manager.create_chatroom(three_public_keys)
        result = manager.post_message(
            chatroom_id=room["chatroom_id"],
            content="我同意采纳",
            sender_public_key=three_public_keys[0],
            private_key=three_keypairs[0][1],
        )
        assert result["stored"] is True
        assert "envelope" in result
        assert "signature" in result["envelope"]
        assert result["envelope"]["public_key"] == three_public_keys[0]

    def test_post_message_rejects_non_member(self, manager, three_public_keys):
        """非成员发送消息拒绝."""
        room = manager.create_chatroom(three_public_keys)
        with pytest.raises(ValueError, match="not a member"):
            manager.post_message(
                chatroom_id=room["chatroom_id"],
                content="hi",
                sender_public_key="pk_outsider",
            )

    def test_post_message_rejects_empty_content(self, manager, three_public_keys):
        """空内容拒绝."""
        room = manager.create_chatroom(three_public_keys)
        with pytest.raises(ValueError, match="content must be non-empty"):
            manager.post_message(
                chatroom_id=room["chatroom_id"],
                content="",
                sender_public_key=three_public_keys[0],
            )

    def test_post_message_with_topic_id(self, manager, three_public_keys):
        """带 topic_id 的消息正确关联."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题 A")
        result = manager.post_message(
            chatroom_id=room["chatroom_id"],
            content="回复话题 A",
            sender_public_key=three_public_keys[0],
            topic_id=topic["topic_id"],
        )
        assert result["topic_id"] == topic["topic_id"]


# ── SubTask 3.3: detect_consensus ─────────────────────────

class TestDetectConsensus:
    def test_consensus_reached_when_all_agree(self, manager, three_public_keys):
        """三人都同意 → 共识达成（规则降级路径）."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "是否采纳 RSI 候选 X")
        # 三人都发表同意意见，关键词高度重叠
        for i, pk in enumerate(three_public_keys):
            manager.post_message(
                chatroom_id=room["chatroom_id"],
                content=f"我同意采纳 RSI 候选 X，应该采纳",
                sender_public_key=pk,
                topic_id=topic["topic_id"],
            )
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        assert result["consensus_reached"] is True
        assert result["method"] == "rule"
        assert len(result["views"]) == 3
        assert result["avg_keyword_overlap"] > 0.6
        # 共识达成应写见证迹
        assert "witness_trail_id" in result
        assert result["witness_trail_id"].startswith("wit_")

    def test_consensus_not_reached_when_disagree(self, manager, three_public_keys):
        """两人同意一人反对 → 共识未达成，分歧点非空."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题")
        manager.post_message(
            room["chatroom_id"], "我同意采纳 RSI 候选", three_public_keys[0],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "我同意采纳 RSI 候选", three_public_keys[1],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "我反对采纳 RSI 候选，不应该采纳",
            three_public_keys[2], topic_id=topic["topic_id"],
        )
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        assert result["consensus_reached"] is False
        assert len(result["disagreement_points"]) > 0
        # 立场分歧应被检测到
        assert any("立场分歧" in d for d in result["disagreement_points"])

    def test_consensus_llm_path_graceful_degrade(self, manager, three_public_keys):
        """LLM 路径环境不可用时降级到规则（spec L427）."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题")
        for pk in three_public_keys:
            manager.post_message(
                room["chatroom_id"], "我同意采纳 RSI 候选", pk,
                topic_id=topic["topic_id"],
            )
        # use_llm=True 但 truth_grounding engine 可能不可用 → 降级
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=True,
        )
        # 无论 LLM 是否可用，都应返回有效结果
        assert "consensus_reached" in result
        assert "method" in result
        assert result["method"] in ("llm", "rule")
        assert len(result["views"]) == 3

    def test_consensus_views_contain_stance(self, manager, three_public_keys):
        """观点卡片含 stance 字段（pro/con/neutral）."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题")
        manager.post_message(
            room["chatroom_id"], "我同意", three_public_keys[0],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "我反对", three_public_keys[1],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "中立观望", three_public_keys[2],
            topic_id=topic["topic_id"],
        )
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        stances = [v["stance"] for v in result["views"]]
        assert "pro" in stances
        assert "con" in stances


# ── SubTask 3.5: witness_trail_local 写入 ─────────────────

class TestWitnessTrail:
    def test_witness_trail_written_on_consensus(self, manager, three_public_keys):
        """共识达成后写 witness_trail_local 表（spec SubTask 3.5 降级）."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题")
        for pk in three_public_keys:
            manager.post_message(
                room["chatroom_id"], "我同意采纳 RSI 候选", pk,
                topic_id=topic["topic_id"],
            )
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        assert result["consensus_reached"] is True
        witness_id = result.get("witness_trail_id")
        assert witness_id and witness_id.startswith("wit_")
        # 直接查 vault 验证记录已写入
        from laap.memory_vault.vault_manager import (
            vault_manager, _open_vault_connection,
        )
        db_path, key_hex = vault_manager._get_vault("trio_test")
        conn = _open_vault_connection(db_path, key_hex)
        try:
            row = conn.execute(
                "SELECT * FROM witness_trail_local WHERE witness_id = ?",
                (witness_id,),
            ).fetchone()
            assert row is not None
            assert row["event_type"] == "resonance"
            assert row["target_module"] == "trio_chatroom"
            assert row["candidate_id"] == room["chatroom_id"]
            assert row["action"] == "consensus_reached"
            assert row["fitness_score"] > 0.6
        finally:
            conn.close()

    def test_no_witness_trail_without_consensus(self, manager, three_public_keys):
        """未达成共识时不写见证迹."""
        room = manager.create_chatroom(three_public_keys)
        topic = manager.post_topic(room["chatroom_id"], "话题")
        manager.post_message(
            room["chatroom_id"], "同意", three_public_keys[0],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "反对", three_public_keys[1],
            topic_id=topic["topic_id"],
        )
        manager.post_message(
            room["chatroom_id"], "中立", three_public_keys[2],
            topic_id=topic["topic_id"],
        )
        result = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        assert result["consensus_reached"] is False
        assert "witness_trail_id" not in result


# ── SubTask 3.6: 三人讨论冒烟测试 ─────────────────────────

class TestTrioSmoke:
    def test_three_laapers_discuss_topic(self, manager, three_keypairs):
        """SubTask 3.6: 三个本地 LAAPer 实例讨论一个话题，共识检测正确."""
        three_public_keys = [pk for pk, _ in three_keypairs]
        # 步骤 1: 三人创建聊天室
        room = manager.create_chatroom(three_public_keys)
        assert room["created"] is True

        # 步骤 2: 发起话题
        topic = manager.post_topic(room["chatroom_id"], "是否采纳 RSI 候选 X")
        assert topic["topic_id"].startswith("topic_")

        # 步骤 3: 三人各发一条消息（带签名信封）
        messages = [
            "我同意采纳 RSI 候选 X，应该采纳",
            "我同意采纳 RSI 候选 X，应该采纳",
            "我同意采纳 RSI 候选 X，应该采纳",
        ]
        for i, pk in enumerate(three_public_keys):
            result = manager.post_message(
                chatroom_id=room["chatroom_id"],
                content=messages[i],
                sender_public_key=pk,
                private_key=three_keypairs[i][1],
                topic_id=topic["topic_id"],
            )
            assert result["stored"] is True
            assert "envelope" in result

        # 步骤 4: 共识检测
        consensus = manager.detect_consensus(
            room["chatroom_id"], topic["topic_id"], use_llm=False,
        )
        assert consensus["consensus_reached"] is True
        assert len(consensus["views"]) == 3
        assert "witness_trail_id" in consensus

        # 步骤 5: 见证迹被写入
        witness_id = consensus["witness_trail_id"]
        from laap.memory_vault.vault_manager import (
            vault_manager, _open_vault_connection,
        )
        db_path, key_hex = vault_manager._get_vault("trio_test")
        conn = _open_vault_connection(db_path, key_hex)
        try:
            row = conn.execute(
                "SELECT * FROM witness_trail_local WHERE witness_id = ?",
                (witness_id,),
            ).fetchone()
            assert row is not None
            assert row["event_type"] == "resonance"
        finally:
            conn.close()


# ── MCP 桥接函数测试 ──────────────────────────────────────

class TestMcpEndpoints:
    def test_handle_trio_create(self, three_public_keys):
        """handle_trio_create 返回 JSON 字符串且 created=true."""
        out = handle_trio_create(three_public_keys)
        data = json.loads(out)
        assert data["created"] is True
        assert data["member_count"] == 3
        assert data["chatroom_id"].startswith("trio_")

    def test_handle_trio_create_invalid_input(self):
        """非法输入返回 created=false + error."""
        out = handle_trio_create(["only_one"])
        data = json.loads(out)
        assert data["created"] is False
        assert "error" in data

    def test_handle_trio_topic_and_message_and_consensus(self, three_public_keys):
        """端到端桥接函数链路：create→topic→message→consensus."""
        # create
        room = json.loads(handle_trio_create(three_public_keys))
        chatroom_id = room["chatroom_id"]
        # topic
        topic = json.loads(handle_trio_topic(chatroom_id, "测试话题"))
        assert topic["topic_id"].startswith("topic_")
        # message（无 private_key，信封为空但 stored=true）
        msg = json.loads(handle_trio_message(
            chatroom_id, "我同意采纳", three_public_keys[0],
            topic_id=topic["topic_id"],
        ))
        assert msg["stored"] is True
        # 为其他成员也发消息以保证共识
        for pk in three_public_keys[1:]:
            handle_trio_message(
                chatroom_id, "我同意采纳", pk,
                topic_id=topic["topic_id"],
            )
        # consensus
        consensus = json.loads(handle_trio_consensus(
            chatroom_id, topic["topic_id"], use_llm=False,
        ))
        assert "consensus_reached" in consensus
        assert "views" in consensus

    def test_handle_trio_get(self, three_public_keys):
        """handle_trio_get 返回聊天室状态."""
        room = json.loads(handle_trio_create(three_public_keys))
        out = handle_trio_get(room["chatroom_id"])
        data = json.loads(out)
        assert data["chatroom_id"] == room["chatroom_id"]
        assert data["member_count"] == 3
        assert "topics" in data
        assert "messages" in data

    def test_register_trio_chatroom_tools_with_fake_mcp(self):
        """register_trio_chatroom_tools 在 fake mcp 上注册成功."""
        class FakeMcp:
            def __init__(self):
                self.tools = {}

            def tool(self):
                def decorator(fn):
                    self.tools[fn.__name__] = fn
                    return fn
                return decorator

        fake = FakeMcp()
        register_trio_chatroom_tools(fake)
        assert "trio_create" in fake.tools
        assert "trio_topic" in fake.tools
        assert "trio_consensus" in fake.tools
        assert "trio_get" in fake.tools
        # trio_message 不应作为 MCP 工具暴露（私钥不离开 sidecar）
        assert "trio_message" not in fake.tools

    def test_register_trio_chatroom_tools_none_server(self):
        """mcp_server=None 时不报错."""
        register_trio_chatroom_tools(None)  # 不应抛异常


# ── 规则降级路径单测 ──────────────────────────────────────

class TestRuleExtraction:
    def test_extract_view_pro(self):
        """提取'同意/支持'立场为 pro."""
        view = _extract_view_rule("我同意采纳 RSI 候选 X")
        assert view["stance"] == "pro"
        assert "rsi" in [k.lower() for k in view["keywords"]]

    def test_extract_view_con(self):
        """提取'反对'立场为 con."""
        view = _extract_view_rule("我反对采纳 RSI 候选 X")
        assert view["stance"] == "con"

    def test_extract_view_neutral(self):
        """无明确立场为 neutral."""
        view = _extract_view_rule("我需要再想想")
        assert view["stance"] == "neutral"

    def test_keyword_overlap_identical(self):
        """相同关键词重叠度为 1.0."""
        ov = _keyword_overlap(["a", "b", "c"], ["a", "b", "c"])
        assert ov == 1.0

    def test_keyword_overlap_disjoint(self):
        """无交集重叠度为 0.0."""
        ov = _keyword_overlap(["a", "b"], ["c", "d"])
        assert ov == 0.0

    def test_keyword_overlap_empty(self):
        """空列表重叠度为 0.0."""
        assert _keyword_overlap([], ["a"]) == 0.0
        assert _keyword_overlap(["a"], []) == 0.0

    def test_tokenize_chinese(self):
        """中文分词按单字."""
        tokens = _tokenize("我同意采纳")
        assert "同" in tokens
        assert "意" in tokens

    def test_tokenize_english(self):
        """英文分词按单词."""
        tokens = _tokenize("I agree with RSI")
        assert "agree" in tokens
        assert "rsi" in tokens


# ── 全局单例测试 ──────────────────────────────────────────

class TestSingleton:
    def test_get_trio_chatroom_manager_singleton(self):
        """get_trio_chatroom_manager 返回同一实例."""
        m1 = get_trio_chatroom_manager()
        m2 = get_trio_chatroom_manager()
        assert m1 is m2

    def test_reset_for_test_returns_new_instance(self):
        """reset 返回新实例（避免全局污染）."""
        m1 = get_trio_chatroom_manager()
        m2 = reset_trio_chatroom_manager_for_test()
        assert m1 is not m2
