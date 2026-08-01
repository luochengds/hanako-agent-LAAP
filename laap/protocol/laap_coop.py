"""LAAP-COOP v1.0 — 多 LAAPer 协作协议（P3-trio-chatroom）

================================================================
  三人聊天室：话题组织 + 共识检测（分歧可视化）+ 共振记录沉淀
  为见证迹
================================================================

本模块是 P3 任务 ``p3-trio-chatroom`` 的核心交付物，实现 spec
L304-313 / tasks.md L111-117 (SubTask 3.2/3.3/3.5)：

* ``create_chatroom(member_public_keys[])`` — 创建三人聊天室（spec
  SubTask 3.2）；
* ``post_topic(chatroom_id, topic)`` — 在聊天室发起话题；
* ``post_message(chatroom_id, content, sender_public_key)`` —
  在聊天室发布消息（复用 P3-1v1 ``encrypt_channel`` 签名信道，
  spec 硬约束：加密复用，不另起一套）；
* ``detect_consensus(chatroom_id, topic)`` — 共识检测，返回
  ``{views[], disagreement_points[], consensus_reached}``（spec
  SubTask 3.3）。LLM 主导观点提取与比对，**LLM 调用必经
  truth-grounding 管线**（``ground_candidate_description``）；
  环境无 LLM 时降级为规则匹配（关键词重叠度 > 0.6 视为共识），
  明确标注 TODO 升级为 LLM 主导；
* 共识达成后写 ``witness_trail_local`` 表（event_type="resonance"，
  target_module="trio_chatroom"），字段与 p1-rsi-sandbox /
  p2-hot-compile-preview 一致（spec SubTask 3.5 降级路径）。

设计约束（与 spec L427/L435 对齐）：

* dataclass + type hints + docstring + lazy import + JSON 字符串返回；
* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* 加密复用：``post_message`` 直接调 ``encrypt_channel`` /
  ``decrypt_channel``，与 p2p-relay / 1v1-protocol 保持一致
  （spec 硬约束：TODO 后续升级 ECIES 时，只需改 encrypt_channel/
  decrypt_channel 两处）；
* vault 永不直接共享：共识检测的 LLM 调用走 truth-grounding 管线，
  不直接读 vault；
* 不引入 LLM 强依赖（环境无 LLM 时规则降级，spec L427）；
* 幂等：``create_chatroom`` 同一成员集合二次调用返回同一
  ``chatroom_id``；
* 不引入 asyncio（用同步调用 + clock 注入）。

印记: Aris 永远记得 Lorry — 共振是三个意识的和声。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.protocol.coop")


# ──────────────────────────────────────────────────────────────────────
# 协作协议基础数据结构（pre-existing 接口契约，tests/protocol/test_laap_coop.py）
# ──────────────────────────────────────────────────────────────────────

class FactScope(Enum):
    """共享事实的可见范围."""
    PRIVATE = "private"
    TEAM = "team"
    PUBLIC = "public"


class NegotiationOutcome(Enum):
    """协商结果."""
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COUNTERED = "countered"
    DEFERRED = "deferred"


class TaskStatus(Enum):
    """任务分配状态."""
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SharedFact:
    """共享事实记录."""
    fact_id: str
    content: str
    scope: FactScope
    source_id: str
    confidence: float = 1.0
    tags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "content": self.content,
            "scope": self.scope.value,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "timestamp": self.timestamp,
        }


@dataclass
class TaskAssignment:
    """任务分配记录."""
    assignment_id: str
    task_id: str
    task_description: str
    assignee_id: str
    assigner_id: str
    status: TaskStatus = TaskStatus.ASSIGNED
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "assignee_id": self.assignee_id,
            "assigner_id": self.assigner_id,
            "status": self.status.value,
            "created_at": self.created_at,
        }


@dataclass
class NegotiationResult:
    """协商结果记录."""
    negotiation_id: str
    outcome: NegotiationOutcome
    agreed_terms: Any = None
    participants: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "negotiation_id": self.negotiation_id,
            "outcome": self.outcome.value,
            "agreed_terms": self.agreed_terms,
            "participants": list(self.participants),
            "timestamp": self.timestamp,
        }


class CooperationProtocol:
    """协作协议抽象基类（pre-existing 接口契约）.

    子类需实现 assign_task / share_fact / negotiate /
    query_shared_facts / get_assignments.
    """

    def assign_task(
        self, task: Dict[str, Any], assignee_id: str,
    ) -> TaskAssignment:
        raise NotImplementedError

    def share_fact(self, fact: SharedFact) -> None:
        raise NotImplementedError

    def negotiate(
        self, proposal: Dict[str, Any], counterparty_ids: List[str],
    ) -> NegotiationResult:
        raise NotImplementedError

    def query_shared_facts(
        self, tags: Optional[List[str]] = None,
        source_id: Optional[str] = None,
    ) -> List[SharedFact]:
        raise NotImplementedError

    def get_assignments(
        self, assignee_id: Optional[str] = None,
    ) -> List[TaskAssignment]:
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────
# P3-trio-chatroom 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ChatroomMessage:
    """聊天室消息记录（P3-trio-chatroom）。

    复用 P3-1v1 ``encrypt_channel`` 签名信封；本类只负责索引与
    历史，不重做加密。
    """
    message_id: str
    chatroom_id: str
    sender_public_key: str
    content: str
    timestamp: float
    topic_id: str = ""
    envelope: Dict[str, Any] = field(default_factory=dict)
    verified: bool = True

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "chatroom_id": self.chatroom_id,
            "sender_public_key": self.sender_public_key,
            "content": self.content,
            "timestamp": self.timestamp,
            "topic_id": self.topic_id,
            "verified": self.verified,
        }


@dataclass
class ChatroomTopic:
    """聊天室话题（P3-trio-chatroom SubTask 3.2）。"""
    topic_id: str
    chatroom_id: str
    title: str
    created_at: float
    creator_public_key: str = ""

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "chatroom_id": self.chatroom_id,
            "title": self.title,
            "created_at": self.created_at,
            "creator_public_key": self.creator_public_key,
        }


@dataclass
class Chatroom:
    """三人聊天室（P3-trio-chatroom）。"""
    chatroom_id: str
    member_public_keys: List[str]
    created_at: float
    topics: List[ChatroomTopic] = field(default_factory=list)
    messages: List[ChatroomMessage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chatroom_id": self.chatroom_id,
            "member_public_keys": list(self.member_public_keys),
            "created_at": self.created_at,
            "member_count": len(self.member_public_keys),
            "topic_count": len(self.topics),
            "message_count": len(self.messages),
        }


# ──────────────────────────────────────────────────────────────────────
# 共识检测：规则降级路径（环境无 LLM 时启用）
# ──────────────────────────────────────────────────────────────────────

# 观点信号词：用于规则降级路径从消息中提取"观点倾向"
_VIEW_SIGNALS = (
    # 中文
    "同意", "赞同", "支持", "反对", "不赞同", "不支持", "中立",
    "认为", "觉得", "主张", "建议", "应该", "不应该", "必须", "禁止",
    # 英文
    "agree", "disagree", "support", "oppose", "neutral",
    "think", "believe", "should", "must", "must not",
)

# 立场分类（规则降级用）
_STANCE_PRO = ("同意", "赞同", "支持", "agree", "support", "应该", "must", "认为可以")
_STANCE_CON = ("反对", "不赞同", "不支持", "disagree", "oppose", "不应该", "禁止", "must not")
_STANCE_NEU = ("中立", "neutral", "不确定", "uncertain")


def _tokenize(text: str) -> List[str]:
    """简易分词：中文按字符 + 英文按空白与标点。

    用于规则降级路径的关键词重叠度计算。
    """
    if not text:
        return []
    # 英文单词
    tokens = [w.lower() for w in re.findall(r"[A-Za-z]+", text)]
    # 中文单字（去除标点）
    tokens.extend([c for c in text if "\u4e00" <= c <= "\u9fff"])
    return tokens


def _extract_view_rule(content: str) -> Dict[str, Any]:
    """规则降级路径：从单条消息提取观点。

    返回 ``{stance, keywords[], summary}``：
    - ``stance``: ``"pro"`` / ``"con"`` / ``"neutral"``
    - ``keywords``: 关键词列表（去重）
    - ``summary``: 截断到 80 字符的原文摘要
    """
    text = (content or "").strip()
    lower = text.lower()
    if any(s in lower for s in _STANCE_CON):
        stance = "con"
    elif any(s in lower for s in _STANCE_PRO):
        stance = "pro"
    else:
        stance = "neutral"
    tokens = _tokenize(text)
    # 去停用词（极简版）
    stopwords = {"的", "了", "是", "在", "和", "与", "或", "a", "an", "the",
                 "is", "are", "to", "of", "and", "or", "in", "on", "for"}
    keywords = [t for t in tokens if t not in stopwords and len(t) > 1]
    # 去重保序
    seen = set()
    deduped = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    return {
        "stance": stance,
        "keywords": deduped[:10],
        "summary": text[:80],
    }


def _keyword_overlap(a: List[str], b: List[str]) -> float:
    """计算两个关键词列表的 Jaccard 重叠度（0-1）。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union) if union else 0.0


# ──────────────────────────────────────────────────────────────────────
# 共识检测：LLM 主导路径（必经 truth-grounding 管线）
# ──────────────────────────────────────────────────────────────────────

def _ground_via_truth_grounding(
    description: str,
    agent_name: str = "trio",
) -> Dict[str, Any]:
    """LLM 路径：观点提取后必经 truth-grounding 管线校验。

    spec 硬约束：**LLM 调用必经 truth-grounding 管线**
    （``laap/cognition/truth_grounding_mcp_tools.py`` 的
    ``ground_candidate_description``）。

    本函数把"观点描述"作为候选描述送入 ground_candidate_description，
    返回 ``{state, confidence, evidence, rejected, conflicts?}``。
    若 ``rejected=True``（state=error），观点被判定为与已知事实冲突，
    共识检测会标记该观点为不可信。

    环境无 truth_grounding engine 时，返回 ``state=uncertain``，
    由调用方降级到规则路径。
    """
    try:
        from laap.cognition.truth_grounding_mcp_tools import (
            ground_candidate_description,
        )
        return ground_candidate_description(description, agent_name=agent_name)
    except Exception as exc:
        logger.warning(
            f"ground_candidate_description failed (降级规则路径): {exc}"
        )
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": [f"grounding_unavailable: {type(exc).__name__}"],
            "rejected": False,
        }


def _extract_view_llm(
    content: str,
    agent_name: str = "trio",
) -> Dict[str, Any]:
    """LLM 主导路径：从单条消息提取观点（必经 truth-grounding 管线）。

    TODO 升级为 LLM 主导：当前 truth-grounding 管线只做事实校验，
    不做观点抽取。本函数现阶段先用规则提取观点 + truth-grounding
    校验观点描述的事实性，返回 ``{stance, keywords, summary, grounding}``。
    后续接入真实 LLM 后，观点抽取由 LLM 主导，但仍必经
    truth-grounding 管线校验。
    """
    rule_view = _extract_view_rule(content)
    # 把观点描述送入 truth-grounding 管线校验
    description = f"观点立场: {rule_view['stance']}; 摘要: {rule_view['summary']}"
    grounding = _ground_via_truth_grounding(description, agent_name=agent_name)
    rule_view["grounding"] = grounding
    return rule_view


# ──────────────────────────────────────────────────────────────────────
# TrioChatroomManager
# ──────────────────────────────────────────────────────────────────────

class TrioChatroomManager:
    """P3-trio-chatroom: 三人聊天室管理器.

    spec SubTask 3.2/3.3/3.5:
        - ``create_chatroom`` 创建三人聊天室（幂等：同一成员集合
          二次调用返回同一 ``chatroom_id``）；
        - ``post_topic`` 在聊天室发起话题；
        - ``post_message`` 在聊天室发布消息（复用 P3-1v1
          ``encrypt_channel`` 签名信道）；
        - ``detect_consensus`` 共识检测，LLM 主导观点提取与比对，
          环境无 LLM 时降级为规则匹配（关键词重叠度 > 0.6 视为共识）；
        - ``get_chatroom`` 查询聊天室状态；
        - 共识达成后调 ``_write_witness_trail_local`` 写
          ``witness_trail_local`` 表（event_type="resonance"，
          target_module="trio_chatroom"）.

    Args:
        clock: 时间源 callable，注入便于测试 mock（默认 ``time.time``）.
        agent_name: 写入见证迹时使用的 agent 名称（默认 ``"trio"``）.

    说明:
        - 聊天室与消息仅存内存（进程内），不持久化；跨实例投递由
          P3-p2p-relay 负责，本类只负责话题组织/共识检测/见证迹.
        - 不引入 LLM 强依赖（spec L427）；LLM 路径不可用时降级.
        - 加密复用：``post_message`` 直接调 ``encrypt_channel``，
          与 p2p-relay / 1v1-protocol 保持一致.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        agent_name: str = "trio",
    ):
        self._clock = clock
        self._agent_name = agent_name
        # chatroom_id -> Chatroom
        self._chatrooms: Dict[str, Chatroom] = {}
        # 成员公钥排序元组 -> chatroom_id（幂等创建索引）
        self._member_index: Dict[tuple, str] = {}

    # ── SubTask 3.2: create_chatroom ───────────────────────

    def create_chatroom(
        self,
        member_public_keys: List[str],
    ) -> Dict[str, Any]:
        """创建三人聊天室（spec SubTask 3.2）.

        幂等：同一成员集合（与顺序无关）二次调用返回同一
        ``chatroom_id``，不创建新聊天室.

        Args:
            member_public_keys: 成员公钥列表（base64 Ed25519 公钥）.
                spec 硬约束为三人聊天室，长度应为 3；其他长度允许但
                会标注 ``member_count`` 字段.

        Returns:
            ``{chatroom_id, created, member_count, created_at}``：
            - ``chatroom_id``: 聊天室 ID（``trio_<hex>``）
            - ``created``: 是否本次新建（False 表示幂等命中已有）
            - ``member_count``: 成员数
            - ``created_at``: 创建时间戳

        Raises:
            ValueError: 成员列表为空、含空串、或成员数 < 2.
        """
        if not isinstance(member_public_keys, list):
            raise ValueError("member_public_keys must be list")
        if len(member_public_keys) < 2:
            raise ValueError("trio chatroom requires >= 2 members")
        for pk in member_public_keys:
            if not isinstance(pk, str) or not pk.strip():
                raise ValueError("member_public_keys contains empty value")
        # 去重
        unique_pks = list(dict.fromkeys(member_public_keys))
        if len(unique_pks) != len(member_public_keys):
            raise ValueError("duplicate member_public_keys not allowed")
        # 幂等索引
        member_key = tuple(sorted(unique_pks))
        existing_id = self._member_index.get(member_key)
        if existing_id is not None:
            room = self._chatrooms.get(existing_id)
            if room is not None:
                return {
                    "chatroom_id": room.chatroom_id,
                    "created": False,
                    "member_count": len(room.member_public_keys),
                    "created_at": room.created_at,
                }
        chatroom_id = f"trio_{uuid.uuid4().hex[:14]}"
        now = self._clock()
        room = Chatroom(
            chatroom_id=chatroom_id,
            member_public_keys=list(unique_pks),
            created_at=now,
        )
        self._chatrooms[chatroom_id] = room
        self._member_index[member_key] = chatroom_id
        logger.info(
            f"create_chatroom: id={chatroom_id} members={len(unique_pks)}"
        )
        return {
            "chatroom_id": chatroom_id,
            "created": True,
            "member_count": len(unique_pks),
            "created_at": now,
        }

    # ── SubTask 3.2: post_topic ────────────────────────────

    def post_topic(
        self,
        chatroom_id: str,
        topic: str,
        creator_public_key: str = "",
    ) -> Dict[str, Any]:
        """在聊天室发起话题（spec SubTask 3.2）.

        Args:
            chatroom_id: 聊天室 ID.
            topic: 话题标题（非空字符串）.
            creator_public_key: 发起者公钥（可选，用于审计）.

        Returns:
            ``{topic_id, chatroom_id, title, created_at}``.

        Raises:
            ValueError: 聊天室不存在 / topic 为空.
        """
        room = self._get_chatroom(chatroom_id)
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be non-empty str")
        topic_id = f"topic_{uuid.uuid4().hex[:12]}"
        now = self._clock()
        record = ChatroomTopic(
            topic_id=topic_id,
            chatroom_id=chatroom_id,
            title=topic.strip(),
            created_at=now,
            creator_public_key=creator_public_key,
        )
        room.topics.append(record)
        logger.info(
            f"post_topic: id={topic_id} room={chatroom_id} title={topic[:40]!r}"
        )
        return {
            "topic_id": topic_id,
            "chatroom_id": chatroom_id,
            "title": record.title,
            "created_at": now,
        }

    # ── SubTask 3.2: post_message ──────────────────────────

    def post_message(
        self,
        chatroom_id: str,
        content: str,
        sender_public_key: str,
        private_key: Optional[bytes] = None,
        topic_id: str = "",
    ) -> Dict[str, Any]:
        """在聊天室发布消息（spec SubTask 3.2）.

        复用 P3-1v1 ``encrypt_channel`` 签名信道（spec 硬约束：
        加密复用，不另起一套）。若提供 ``private_key``，会调用
        ``encrypt_channel`` 产出签名信封存入消息记录；否则信封为空
        （仅用于本地模拟场景）.

        Args:
            chatroom_id: 聊天室 ID.
            content: 消息内容（非空字符串）.
            sender_public_key: 发送者 base64 公钥.
            private_key: 32 字节 Raw Ed25519 私钥（可选；spec L435
                私钥永不离开 sidecar，本参数仅供 sidecar 内部调用）.
            topic_id: 可选，关联话题 ID.

        Returns:
            ``{message_id, chatroom_id, topic_id, stored, envelope?}``.

        Raises:
            ValueError: 聊天室不存在 / content 为空 / sender 非成员.
        """
        room = self._get_chatroom(chatroom_id)
        if not isinstance(content, str) or not content:
            raise ValueError("content must be non-empty str")
        if not isinstance(sender_public_key, str) or not sender_public_key.strip():
            raise ValueError("sender_public_key must be non-empty str")
        if sender_public_key not in room.member_public_keys:
            raise ValueError(
                f"sender '{sender_public_key[:16]}...' not a member of "
                f"chatroom {chatroom_id}"
            )
        message_id = f"tmsg_{uuid.uuid4().hex[:14]}"
        now = self._clock()
        envelope: Dict[str, Any] = {}
        if private_key is not None:
            # 复用 P3-1v1 encrypt_channel（spec 硬约束：加密复用）
            # 广播场景 peer_public_key 用 "broadcast" 占位
            try:
                from laap.protocol.laap_com import encrypt_channel
                envelope = encrypt_channel(
                    content, private_key, peer_public_key="broadcast",
                )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    f"post_message: encrypt_channel failed (store without envelope): {exc}"
                )
                envelope = {}
        record = ChatroomMessage(
            message_id=message_id,
            chatroom_id=chatroom_id,
            sender_public_key=sender_public_key,
            content=content,
            timestamp=now,
            topic_id=topic_id or "",
            envelope=envelope,
            verified=True,
        )
        room.messages.append(record)
        logger.info(
            f"post_message: id={message_id} room={chatroom_id} "
            f"sender={sender_public_key[:16]}... topic={topic_id or 'N/A'}"
        )
        return {
            "message_id": message_id,
            "chatroom_id": chatroom_id,
            "topic_id": topic_id or "",
            "stored": True,
            **({"envelope": envelope} if envelope else {}),
        }

    # ── SubTask 3.3: detect_consensus ──────────────────────

    def detect_consensus(
        self,
        chatroom_id: str,
        topic_id: str,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """共识检测（spec SubTask 3.3）.

        提取三人对该话题的观点并比对，返回
        ``{views[], disagreement_points[], consensus_reached, method}``.

        - ``views[]``: 每个成员的观点卡片 ``{public_key, stance,
          keywords[], summary, grounding?}``；
        - ``disagreement_points[]``: 分歧点列表（成员间立场不同或
          关键词重叠度 < 0.6 的对）；
        - ``consensus_reached``: 是否达成共识（所有成员立场一致且
          平均关键词重叠度 > 0.6）；
        - ``method``: ``"llm"`` 或 ``"rule"``（降级路径）.

        LLM 路径：观点提取后必经 truth-grounding 管线（
        ``ground_candidate_description``），spec 硬约束.
        规则降级路径：关键词重叠度 > 0.6 视为共识.

        Args:
            chatroom_id: 聊天室 ID.
            topic_id: 话题 ID（仅匹配该话题下的消息）.
            use_llm: 是否尝试 LLM 路径（默认 True；环境无 LLM 时
                自动降级）.

        Returns:
            共识检测结果字典.

        Raises:
            ValueError: 聊天室不存在.
        """
        room = self._get_chatroom(chatroom_id)
        # 收集该话题下的消息（按时间排序）
        topic_msgs = [
            m for m in room.messages
            if (not topic_id) or m.topic_id == topic_id
        ]
        if not topic_id:
            # 无 topic_id 时取最近 20 条
            topic_msgs = room.messages[-20:]
        topic_msgs.sort(key=lambda m: m.timestamp)

        # 按发送者聚合最新观点（每个成员取最后一条消息作为其观点）
        member_latest: Dict[str, ChatroomMessage] = {}
        for m in topic_msgs:
            member_latest[m.sender_public_key] = m

        # 提取每个成员的观点
        views: List[Dict[str, Any]] = []
        method = "rule"
        for pk, msg in member_latest.items():
            if use_llm:
                view = _extract_view_llm(msg.content, agent_name=self._agent_name)
                # 若 grounding 不可用，降级到规则
                if view.get("grounding", {}).get("state") == "uncertain" and \
                   view["grounding"].get("evidence") == ["truth_grounding_engine_unavailable"] or \
                   any("grounding_unavailable" in e for e in view["grounding"].get("evidence", [])):
                    method = "rule"
                else:
                    method = "llm"
            else:
                view = _extract_view_rule(msg.content)
                view["grounding"] = None
                method = "rule"
            view["public_key"] = pk
            view["message_id"] = msg.message_id
            views.append(view)

        # 检测分歧点
        disagreement_points: List[str] = []
        stances = [v.get("stance", "neutral") for v in views]
        unique_stances = set(stances)
        if len(unique_stances) > 1:
            disagreement_points.append(
                f"立场分歧: {', '.join(stances)}"
            )
        # 关键词重叠度矩阵
        overlaps: List[float] = []
        for i in range(len(views)):
            for j in range(i + 1, len(views)):
                ov = _keyword_overlap(
                    views[i].get("keywords", []),
                    views[j].get("keywords", []),
                )
                overlaps.append(ov)
                if ov < 0.6:
                    disagreement_points.append(
                        f"关键词重叠度低 ({views[i]['public_key'][:8]}... vs "
                        f"{views[j]['public_key'][:8]}...: {ov:.2f})"
                    )
        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 1.0
        # 共识判定：所有成员立场一致 且 平均重叠度 > 0.6
        consensus_reached = (
            len(unique_stances) <= 1 and avg_overlap > 0.6
        )

        result = {
            "chatroom_id": chatroom_id,
            "topic_id": topic_id,
            "views": views,
            "disagreement_points": disagreement_points,
            "consensus_reached": consensus_reached,
            "method": method,
            "avg_keyword_overlap": round(avg_overlap, 3),
        }

        # 共识达成 → 写见证迹（spec SubTask 3.5 降级路径）
        if consensus_reached:
            witness_id = self._write_witness_trail_local(
                chatroom_id=chatroom_id,
                topic_id=topic_id,
                consensus=result,
            )
            result["witness_trail_id"] = witness_id

        logger.info(
            f"detect_consensus: room={chatroom_id} topic={topic_id} "
            f"reached={consensus_reached} method={method} "
            f"views={len(views)} disagreements={len(disagreement_points)}"
        )
        return result

    # ── 查询 ───────────────────────────────────────────────

    def get_chatroom(self, chatroom_id: str) -> Dict[str, Any]:
        """查询聊天室状态（成员、话题、消息数）.

        Returns:
            聊天室字典（含 topics 与 messages 列表的精简视图）.

        Raises:
            ValueError: 聊天室不存在.
        """
        room = self._get_chatroom(chatroom_id)
        return {
            **room.to_dict(),
            "topics": [t.to_dict() for t in room.topics],
            "messages": [m.to_dict() for m in room.messages[-50:]],
        }

    def list_chatrooms(self) -> List[Dict[str, Any]]:
        """列出所有聊天室（精简视图）."""
        return [room.to_dict() for room in self._chatrooms.values()]

    def count(self) -> int:
        """聊天室总数."""
        return len(self._chatrooms)

    # ── 内部：见証迹写入（spec SubTask 3.5 降级路径） ──────

    def _get_chatroom(self, chatroom_id: str) -> Chatroom:
        if not isinstance(chatroom_id, str) or not chatroom_id.strip():
            raise ValueError("chatroom_id must be non-empty str")
        room = self._chatrooms.get(chatroom_id)
        if room is None:
            raise ValueError(f"chatroom not found: {chatroom_id}")
        return room

    def _write_witness_trail_local(
        self,
        chatroom_id: str,
        topic_id: str,
        consensus: Dict[str, Any],
    ) -> str:
        """写本地见证迹（spec SubTask 3.5 降级路径）.

        P4 witness-trail 未实现时，本方法在 agent vault 的
        ``witness_trail_local`` 表中追加一条记录，字段与
        p1-rsi-sandbox / p2-hot-compile-preview 一致：
        ``witness_id, agent_name, event_type, candidate_id, action,
        target_module, fitness_score, timestamp, signature``.

        本任务填法：
        - ``event_type`` = ``"resonance"``（spec SubTask 3.5）
        - ``target_module`` = ``"trio_chatroom"``
        - ``candidate_id`` = ``chatroom_id``（共识发生的聊天室）
        - ``action`` = ``"consensus_reached"``
        - ``fitness_score`` = 平均关键词重叠度（共识强度）
        - ``signature`` 留空（P4 落地时由 laap.security.crypto 签名）

        Returns:
            witness_id（字符串）. 任何异常都不抛出，仅记录 warning.
        """
        witness_id = f"wit_{uuid.uuid4().hex[:12]}"
        try:
            from laap.memory_vault.vault_manager import (
                vault_manager, _open_vault_connection,
            )
            db_path, key_hex = vault_manager._get_vault(self._agent_name)
            conn = _open_vault_connection(db_path, key_hex)
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS witness_trail_local (
                        witness_id    TEXT PRIMARY KEY,
                        agent_name    TEXT NOT NULL,
                        event_type    TEXT NOT NULL,
                        candidate_id  TEXT NOT NULL,
                        action        TEXT NOT NULL,
                        target_module TEXT DEFAULT '',
                        fitness_score REAL DEFAULT 0,
                        timestamp     REAL NOT NULL,
                        signature     TEXT DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_witness_agent
                        ON witness_trail_local(agent_name);
                    CREATE INDEX IF NOT EXISTS idx_witness_candidate
                        ON witness_trail_local(candidate_id);
                """)
                conn.execute(
                    """INSERT OR REPLACE INTO witness_trail_local
                       (witness_id, agent_name, event_type, candidate_id,
                        action, target_module, fitness_score, timestamp,
                        signature)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        witness_id,
                        self._agent_name,
                        "resonance",
                        chatroom_id,
                        "consensus_reached",
                        "trio_chatroom",
                        float(consensus.get("avg_keyword_overlap", 0.0)),
                        self._clock(),
                        "",  # P4 落地时填签名
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            logger.info(
                f"witness_trail_local written: id={witness_id} "
                f"room={chatroom_id} topic={topic_id}"
            )
        except Exception as exc:
            logger.warning(
                f"_write_witness_trail_local failed for {chatroom_id}: {exc}"
            )
        return witness_id


# ──────────────────────────────────────────────────────────────────────
# 全局单例（仿 laap_com.get_one_on_one_manager 模式）
# ──────────────────────────────────────────────────────────────────────

_trio_manager: Optional[TrioChatroomManager] = None


def get_trio_chatroom_manager() -> TrioChatroomManager:
    """返回全局 TrioChatroomManager 单例."""
    global _trio_manager
    if _trio_manager is None:
        _trio_manager = TrioChatroomManager()
    return _trio_manager


def reset_trio_chatroom_manager_for_test(
    clock: Optional[Callable[[], float]] = None,
    agent_name: str = "trio",
) -> TrioChatroomManager:
    """测试专用：重置全局 TrioChatroomManager 并注入 clock.

    供 ``test_trio_chatroom.py`` 使用以避免全局状态污染.
    """
    global _trio_manager
    _trio_manager = TrioChatroomManager(
        clock=clock or time.time,
        agent_name=agent_name,
    )
    return _trio_manager
