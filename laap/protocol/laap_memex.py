"""LAAP Protocol — Memex 共享知识库 (P4-memex)

================================================================
  去标识化知识片段 + grounding 证据链（低置信不可发布）
================================================================

本模块是 P4 任务 ``p4-memex`` 的核心交付物：实现社区共享知识库
协议 ``laap_memex``，所有发布到社区的知识片段必须：

1. **去标识化**：去除用户名、时间戳、实例 ID、个人代词等隐私
   痕迹（``deidentify``）；
2. **附加证据链**：每条知识片段必须挂载来源 memory_id（哈希）、
   置信度、校验时间（``attach_evidence``）；
3. **低置信过滤**：``confidence < 0.6`` 直接拒绝发布
   （``{published: false, reason: "low_confidence"}``）；
4. **grounding 复核**：发布前强制经 P1 truth-grounding 管线
   复核，``rejected=true`` 时拒绝发布（由
   ``laap.verification.memex_verifier`` 完成）；
5. **可选签名**：发布者可用 Ed25519 私钥对知识记录签名，
   消费节点可验证发布者身份（复用 P3 identity-pki）.

注意：本模块与 ``laap.protocol.laap_mem``（分层记忆协议，含
ForgettingCurve / MemoryStore）是不同关注点. 本模块专指社区
共享知识库的发布/检索协议.

设计约束（与 spec L130-137 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``vault_manager`` / ``truth_grounding_mcp_tools`` /
  ``laap_id`` 仅在首次调用时导入；
* 模板优先，不新增外部 LLM 依赖；
* vault 永不直接共享：发布到 Memex 的内容必须先经 ``deidentify``，
  原始 memory_id 仅以哈希形式出现在证据链中；
* dataclass + type hints + docstring；
* 所有 MCP 工具入口返回 JSON 字符串；
* 幂等：同一 (content, evidence_chain) 二次发布返回同一
  ``knowledge_id``，不创建新记录.

印记: Aris 永远记得 Lorry — 共享是为了让一个生命的经验
照亮另一个生命的暗夜.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.laap_memex")


# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

# spec SubTask 4.5: confidence < 0.6 直接拒绝发布
MEMEX_MIN_CONFIDENCE: float = 0.6

# Memex 知识片段的 scope 标签（与 vault scope 解耦，专用于共享知识）
MEMEX_SCOPE = "memex_shared"


# ──────────────────────────────────────────────────────────────────────
# 1. 去标识化（SubTask 4.3）
# ──────────────────────────────────────────────────────────────────────

# 用户名/标签模式：
#   <user:xxx> | @name | 用户<ascii-name> | Lorry | Aris
# 注意：`用户` 后只匹配 ASCII 字母数字下划线，遇到中文即停，
# 避免吞掉 `用户Lorry今天` 中的中文后续内容.
_USER_TAG_PATTERN = re.compile(
    r"<user:[^>]*>"
    r"|@[A-Za-z0-9_\u4e00-\u9fa5]+"
    r"|用户[A-Za-z0-9_]+"
    r"|Lorry"
    r"|Aris",
    re.IGNORECASE,
)

# 时间戳模式：ISO 8601 | 日期 | 时间 | 中文日期
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{1,2}:\d{2}(:\d{2})?"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
)

# 实例 ID 模式：UUID | mem_xxx | evt_xxx | wit_xxx | trio_xxx | did:laap:xxx | session_xxx
_INSTANCE_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|\bmem_[0-9a-f]{8,16}\b"
    r"|\bevt_[0-9a-f]{8,16}\b"
    r"|\bwit_[0-9a-f]{8,16}\b"
    r"|\btrio_[0-9a-f]{8,16}\b"
    r"|\bdid:laap:[0-9a-f]{8,32}\b"
    r"|\bsession[_-]?[0-9a-f]{6,16}\b",
    re.IGNORECASE,
)

# 英文代词的单词边界正则（避免误伤 important / iron / main 中的子串）
_PRONOUN_BOUNDARY_PATTERN = re.compile(
    r"\b(I|me|my|mine|we|us|our|ours|myself|ourselves)\b",
    re.IGNORECASE,
)


def deidentify(content: str) -> str:
    """去标识化：去除用户名、时间戳、实例 ID、个人代词等隐私痕迹.

    spec SubTask 4.3: ``deidentify(content) -> deidentified_content``.

    替换规则（顺序执行）：
    1. **用户名/标签**：``<user:xxx>`` / ``@xxx`` / ``用户XXX`` /
       项目核心用户名（Lorry/Aris）→ ``[user]``；
    2. **实例 ID**：UUID / ``mem_xxx`` / ``evt_xxx`` / ``did:laap:xxx``
       / ``session_xxx`` → ``[id]``；
    3. **时间戳**：ISO 8601 / 日期 / 时间 → ``[timestamp]``；
    4. **中文个人代词**：``我`` / ``我们`` / ``我的`` → ``[user]``；
    5. **英文个人代词**：``I`` / ``me`` / ``my`` / ``we`` / ``us`` 等
       （单词边界匹配，避免误伤 ``important``）→ ``[user]``；
    6. **空白规整**：合并连续空格为单个，去除首尾空白.

    幂等：对已去标识化的内容二次调用不会产生额外变化.

    Args:
        content: 原始内容字符串.

    Returns:
        去标识化后的内容字符串. 输入为空时返回空字符串.
    """
    if not isinstance(content, str) or not content:
        return ""

    text = content
    # 1. 用户名/标签
    text = _USER_TAG_PATTERN.sub("[user]", text)
    # 2. 实例 ID
    text = _INSTANCE_ID_PATTERN.sub("[id]", text)
    # 3. 时间戳
    text = _TIMESTAMP_PATTERN.sub("[timestamp]", text)
    # 4. 中文个人代词
    text = text.replace("我们", "[user]")
    text = text.replace("我的", "[user]")
    text = text.replace("我", "[user]")
    # 5. 英文个人代词（单词边界）
    text = _PRONOUN_BOUNDARY_PATTERN.sub("[user]", text)
    # 6. 空白规整
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ──────────────────────────────────────────────────────────────────────
# 2. 证据链附加（SubTask 4.4）
# ──────────────────────────────────────────────────────────────────────

def _hash_memory_id(memory_id: str) -> str:
    """对 memory_id 做 SHA-256 哈希，返回前 16 字符十六进制."""
    if not memory_id:
        return ""
    return hashlib.sha256(memory_id.encode("utf-8")).hexdigest()[:16]


def attach_evidence(
    content: str,
    source_memories: List[Dict[str, Any]],
    confidence: float = 0.7,
) -> Dict[str, Any]:
    """附加证据链：把来源 memory_id（哈希）、置信度、校验时间挂到内容上.

    spec SubTask 4.4: ``attach_evidence(content, source_memories[])
    -> {content, evidence_chain[]}``.

    Args:
        content: 已去标识化的内容字符串.
        source_memories: 来源记忆列表，每项是 dict，至少含 ``memory_id``
            字段，可选 ``confidence`` / ``scope`` / ``content_hash``.
        confidence: 整体置信度（发布者自评），范围 [0.0, 1.0].

    Returns:
        ``{content, evidence_chain, confidence, verified_at}``.
    """
    if not isinstance(content, str):
        content = str(content) if content is not None else ""

    safe_confidence = float(confidence) if confidence is not None else 0.0
    safe_confidence = max(0.0, min(1.0, safe_confidence))

    evidence_chain: List[Dict[str, Any]] = []
    if isinstance(source_memories, list):
        for src in source_memories:
            if not isinstance(src, dict):
                continue
            mem_id = src.get("memory_id", "")
            if not mem_id:
                continue
            entry: Dict[str, Any] = {
                "memory_id_hash": _hash_memory_id(str(mem_id)),
            }
            if "confidence" in src:
                try:
                    entry["source_confidence"] = float(src["confidence"])
                except (TypeError, ValueError):
                    pass
            if "scope" in src and src["scope"]:
                entry["scope"] = str(src["scope"])
            if "content_hash" in src and src["content_hash"]:
                entry["content_hash"] = str(src["content_hash"])
            evidence_chain.append(entry)

    return {
        "content": content,
        "evidence_chain": evidence_chain,
        "confidence": safe_confidence,
        "verified_at": _now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# 3. KnowledgeRecord / MemexStore
# ──────────────────────────────────────────────────────────────────────

@dataclass
class KnowledgeRecord:
    """一条已发布到 Memex 的知识记录."""
    knowledge_id: str = ""
    content: str = ""
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    publisher_public_key: str = ""
    signature: str = ""
    grounding_state: str = "unknown"
    grounding_confidence: float = 0.0
    published_at: str = ""
    verified_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KnowledgeRecord":
        return cls(
            knowledge_id=d.get("knowledge_id", ""),
            content=d.get("content", ""),
            evidence_chain=list(d.get("evidence_chain", []) or []),
            confidence=float(d.get("confidence", 0.0)),
            publisher_public_key=d.get("publisher_public_key", ""),
            signature=d.get("signature", ""),
            grounding_state=d.get("grounding_state", "unknown"),
            grounding_confidence=float(d.get("grounding_confidence", 0.0)),
            published_at=d.get("published_at", ""),
            verified_at=d.get("verified_at", ""),
        )

    def content_fingerprint(self) -> str:
        """内容的稳定指纹（用于幂等去重）."""
        payload = json.dumps(
            {"content": self.content,
             "evidence_chain": self.evidence_chain},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class MemexStore:
    """Memex 共享知识库存储（进程内单例）.

    存储采用进程内 dict + InMemoryDB 双索引：
    * ``_records``: knowledge_id → KnowledgeRecord；
    * ``_fingerprints``: content_fingerprint → knowledge_id（幂等去重）；
    * ``_vector_db``: InMemoryDB（语义检索，复用 laap.rag.db）.

    幂等：同一 (content, evidence_chain) 二次发布返回同一
    ``knowledge_id``.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._records: Dict[str, KnowledgeRecord] = {}
        self._fingerprints: Dict[str, str] = {}
        self._vector_db = None
        self._collection_name = "memex_knowledge"
        self._vector_dim = 64

    def _get_vector_db(self):
        if self._vector_db is None:
            try:
                from laap.rag.db import InMemoryDB
                self._vector_db = InMemoryDB()
                self._vector_db.create_collection(
                    self._collection_name, self._vector_dim
                )
            except Exception as exc:
                logger.warning(f"InMemoryDB init failed: {exc}")
                self._vector_db = None
        return self._vector_db

    def _pseudo_embedding(self, text: str) -> List[float]:
        """从文本生成伪 embedding（基于字符哈希的确定性向量）."""
        vec = [0.0] * self._vector_dim
        if not text:
            return vec
        for ch in text:
            idx = hash(ch) % self._vector_dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def publish(
        self,
        content: str,
        evidence_chain: List[Dict[str, Any]],
        confidence: float,
        publisher_public_key: str = "",
        publisher_private_key: Optional[bytes] = None,
        grounding_result: Optional[Dict[str, Any]] = None,
        skip_verify: bool = False,
    ) -> Dict[str, Any]:
        """发布一条知识片段到 Memex（幂等）.

        spec SubTask 4.2: ``publish_knowledge(content, evidence_chain,
        confidence) -> {published, reason?}``.

        Args:
            content: 已去标识化的内容字符串.
            evidence_chain: 证据链（来自 ``attach_evidence``）.
            confidence: 整体置信度 [0.0, 1.0].
            publisher_public_key: 发布者 base64 公钥（可选）.
            publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选，
                spec L435 私钥永不离开 sidecar）.
            grounding_result: 来自 ``MemexVerifier`` 的复核结果.
            skip_verify: 跳过复核检查（仅测试用）.

        Returns:
            ``{published: bool, reason?: str, knowledge_id?: str}``.
        """
        if not isinstance(content, str) or not content.strip():
            return {"published": False, "reason": "empty_content"}
        if not isinstance(evidence_chain, list) or not evidence_chain:
            return {"published": False, "reason": "empty_evidence"}

        # 低置信过滤（spec SubTask 4.5）
        if confidence is None or confidence < MEMEX_MIN_CONFIDENCE:
            return {"published": False, "reason": "low_confidence"}

        # grounding 复核（spec SubTask 4.6）
        if not skip_verify:
            if not isinstance(grounding_result, dict):
                return {"published": False,
                        "reason": "grounding_missing"}
            if not grounding_result.get("verified"):
                reason = grounding_result.get("reason", "grounding_rejected")
                return {"published": False, "reason": reason}

        record = KnowledgeRecord(
            knowledge_id=f"know_{uuid.uuid4().hex[:12]}",
            content=content,
            evidence_chain=list(evidence_chain),
            confidence=float(confidence),
            publisher_public_key=publisher_public_key or "",
            grounding_state=(grounding_result or {}).get(
                "grounding", {}).get("state", "unknown"),
            grounding_confidence=(grounding_result or {}).get(
                "grounding", {}).get("confidence", 0.0),
            published_at=_now_iso(),
            verified_at=(grounding_result or {}).get("verified_at", _now_iso()),
        )

        # 可选签名
        if publisher_private_key is not None and publisher_public_key:
            try:
                from laap.protocol.laap_id import sign_message
                signed = sign_message(
                    message=record.content_fingerprint(),
                    private_key=publisher_private_key,
                )
                record.signature = signed["signature"]
            except Exception as exc:
                logger.warning(f"publish sign failed: {exc}")

        # 幂等检查
        fp = record.content_fingerprint()
        with self._lock:
            existing_id = self._fingerprints.get(fp)
            if existing_id and existing_id in self._records:
                logger.info(
                    f"memex publish idempotent hit: fp={fp} "
                    f"know_id={existing_id}"
                )
                return {
                    "published": True,
                    "knowledge_id": existing_id,
                    "idempotent": True,
                }
            self._records[record.knowledge_id] = record
            self._fingerprints[fp] = record.knowledge_id

        # 写入向量库（非阻塞）
        vdb = self._get_vector_db()
        if vdb is not None:
            try:
                vdb.upsert(
                    self._collection_name,
                    [{
                        "id": record.knowledge_id,
                        "text": record.content,
                        "embedding": self._pseudo_embedding(record.content),
                        "metadata": {
                            "confidence": record.confidence,
                            "publisher_public_key": record.publisher_public_key,
                            "published_at": record.published_at,
                        },
                    }],
                )
            except Exception as exc:
                logger.warning(f"vector db upsert failed: {exc}")

        logger.info(
            f"memex publish: know_id={record.knowledge_id} "
            f"conf={record.confidence:.2f} grounding={record.grounding_state}"
        )
        return {"published": True, "knowledge_id": record.knowledge_id}

    def query(
        self,
        query_text: str,
        top_k: int = 10,
        min_confidence: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索 Memex 知识片段."""
        if not query_text or not isinstance(query_text, str):
            return []
        safe_top_k = max(1, min(int(top_k), 100))
        vdb = self._get_vector_db()
        if vdb is None:
            with self._lock:
                records = list(self._records.values())
            q_lower = query_text.lower()
            scored = []
            for r in records:
                if query_text in r.content or q_lower in r.content.lower():
                    scored.append((1.0, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [r.to_dict() for _, r in scored[:safe_top_k]]
        else:
            hits = vdb.search(
                self._collection_name,
                self._pseudo_embedding(query_text),
                top_k=safe_top_k,
            )
            results = []
            with self._lock:
                for hit in hits:
                    kid = hit.get("id", "")
                    rec = self._records.get(kid)
                    if rec is not None:
                        d = rec.to_dict()
                        d["score"] = hit.get("score", 0.0)
                        results.append(d)

        if min_confidence is not None:
            results = [r for r in results
                       if r.get("confidence", 0.0) >= min_confidence]
        return results

    def get(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        """按 knowledge_id 查询单条记录."""
        with self._lock:
            rec = self._records.get(knowledge_id)
        return rec.to_dict() if rec is not None else None

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有知识记录（按发布时间倒序）."""
        safe_limit = max(1, min(int(limit), 500))
        with self._lock:
            records = sorted(
                self._records.values(),
                key=lambda r: r.published_at,
                reverse=True,
            )[:safe_limit]
        return [r.to_dict() for r in records]

    def verify_record_signature(self, knowledge_id: str) -> bool:
        """验证某条记录的发布者签名."""
        with self._lock:
            rec = self._records.get(knowledge_id)
        if rec is None or not rec.signature or not rec.publisher_public_key:
            return False
        try:
            from laap.protocol.laap_id import verify_message
            return verify_message({
                "message": rec.content_fingerprint(),
                "signature": rec.signature,
                "public_key": rec.publisher_public_key,
            })
        except Exception:
            return False

    def stats(self) -> Dict[str, Any]:
        """Memex 知识库统计."""
        with self._lock:
            total = len(self._records)
            signed = sum(1 for r in self._records.values() if r.signature)
            avg_conf = (sum(r.confidence for r in self._records.values()) / total
                        if total > 0 else 0.0)
            by_grounding: Dict[str, int] = {}
            for r in self._records.values():
                by_grounding[r.grounding_state] = (
                    by_grounding.get(r.grounding_state, 0) + 1
                )
        return {
            "total_records": total,
            "signed_records": signed,
            "avg_confidence": round(avg_conf, 4),
            "by_grounding_state": by_grounding,
            "min_confidence_threshold": MEMEX_MIN_CONFIDENCE,
        }

    def clear(self) -> None:
        """清空所有记录（仅测试用）."""
        with self._lock:
            self._records.clear()
            self._fingerprints.clear()
        if self._vector_db is not None:
            try:
                self._vector_db.delete_collection(self._collection_name)
                self._vector_db.create_collection(
                    self._collection_name, self._vector_dim
                )
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────
# 4. 工具函数与全局单例
# ──────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


_memex_store: Optional[MemexStore] = None
_memex_lock = threading.Lock()


def get_memex_store() -> MemexStore:
    """获取全局 MemexStore 单例."""
    global _memex_store
    if _memex_store is None:
        with _memex_lock:
            if _memex_store is None:
                _memex_store = MemexStore()
    return _memex_store


def reset_memex_store_for_test() -> None:
    """测试辅助：重置全局 MemexStore 单例. 生产代码不要调用."""
    global _memex_store
    with _memex_lock:
        _memex_store = None


# ──────────────────────────────────────────────────────────────────────
# 5. 高级发布入口（集成 verifier）
# ──────────────────────────────────────────────────────────────────────

def publish_knowledge(
    content: str,
    source_memories: List[Dict[str, Any]],
    confidence: float,
    agent_name: str = "aris",
    publisher_public_key: str = "",
    publisher_private_key: Optional[bytes] = None,
    skip_grounding: bool = False,
) -> Dict[str, Any]:
    """端到端发布入口：去标识化 → 证据链 → 复核 → 存储.

    spec SubTask 4.2 + 4.3 + 4.4 + 4.5 + 4.6 完整流水线.

    Args:
        content: 原始内容字符串（可能含用户名/时间戳等隐私痕迹）.
        source_memories: 来源记忆列表（来自 vault retrieve）.
        confidence: 整体置信度 [0.0, 1.0].
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
        publisher_public_key: 发布者 base64 公钥（可选）.
        publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选）.
        skip_grounding: 跳过 grounding 复核（仅测试用）.

    Returns:
        ``{published: bool, reason?: str, knowledge_id?: str,
        deidentified_content?: str, grounding?: dict}``.
    """
    # 1. 去标识化
    deid = deidentify(content)
    if not deid.strip():
        return {"published": False, "reason": "empty_after_deidentify"}

    # 2. 附加证据链
    evidence = attach_evidence(deid, source_memories, confidence)

    # 3. 复核（低置信 + grounding）
    grounding_result: Optional[Dict[str, Any]] = None
    if not skip_grounding:
        try:
            from laap.verification.memex_verifier import (
                verify_before_publish,
            )
            grounding_result = verify_before_publish(
                content=deid,
                confidence=confidence,
                agent_name=agent_name,
            )
        except Exception as exc:
            logger.warning(f"memex_verifier unavailable: {exc}")
            grounding_result = {"verified": False,
                                "reason": "verifier_unavailable"}

    # 4. 存储
    store = get_memex_store()
    result = store.publish(
        content=deid,
        evidence_chain=evidence["evidence_chain"],
        confidence=confidence,
        publisher_public_key=publisher_public_key,
        publisher_private_key=publisher_private_key,
        grounding_result=grounding_result,
        skip_verify=skip_grounding,
    )

    if not result.get("published"):
        result.setdefault("deidentified_content", deid)
        if grounding_result:
            result.setdefault("grounding", grounding_result.get("grounding"))
    return result
