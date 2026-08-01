"""
LAAP — Truth Grounding Engine (真理级知识建构引擎)

============================================================
  当 Agent 没见过某样东西，它不瞎编——它从原理重建
============================================================

问题：
  当前 agent 面对未知时的默认行为：模式匹配 → 输出看起来合理
  但可能错误的答案（hallucination）。本质是「基于记忆的推断」，
  无法区分"我知道"和"我猜的"。

方案：
  Truth Grounding Engine 将问题从"搜索记忆"切换到"原理重建"模式。
  它对待每个知识声明的方式不是检索匹配，而是从第一性原理
  重新建构——每一步都知道自己在做什么，每一步都标记可信度。

认知姿态变更：
  旧方式：记忆匹配 → 输出 → （如果错）→ 错误校准
  新方式：检查是否是已知 → 如果是未知 → 原理分解 → 
          从原理重建 → 标记每步 epistemic status → 输出带标签的结果

依赖：
  - laap.cognition.metacognition.fp_metacognition
      (EpistemicStatus, GroundedJudgment, FirstPrinciplesMetaCognition)
  - laap.memory.long_term (LongTermMemory, MemoryEntry)
  - laap.cognition.error_reflection (ErrorReflectionPipeline, CalibrationSignal)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
import logging
import math
import re
import time
import uuid

from laap.cognition.metacognition.fp_metacognition import (
    EpistemicStatus,
    GroundedJudgment,
    FirstPrinciplesMetaCognition,
    MetaCognitionLevel,
)
from laap.memory.long_term import LongTermMemory, MemoryEntry, MemoryType

logger = logging.getLogger("laap.cognition.truth_grounding")

# ──────────────────────────────────────────────────────────────────────
# 1. 核心数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class AtomClaim:
    """
    原子声明 — 一个不可再分的最小知识单元

    每个原子声明要么：
    - 被系统"知道"（在记忆中有直接支撑）
    - 被标记为"未知"（需要从原理重建）
    - 被标记为"假设"（作为推理的前提，但未验证）
    """
    text: str                          # 原子声明的内容
    status: EpistemicStatus = EpistemicStatus.UNKNOWN
    confidence: float = 0.0            # 系统对该声明的确信度
    source: str = ""                   # 来源：memory / fp_reconstruction / assumption
    supporting_evidence: List[str] = field(default_factory=list)   # 支撑证据
    related_memory_ids: List[str] = field(default_factory=list)    # 关联的记忆ID
    is_derived: bool = False           # 是否是从其他声明推导出来的

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text[:80],
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "evidence_count": len(self.supporting_evidence),
            "is_derived": self.is_derived,
        }


@dataclass
class ReconstructionStep:
    """
    重建步骤 — 从原理到结论的推理链中的一步

    每一步都记录了：
    - 从哪里来（输入前提）
    - 用了什么推理规则
    - 得到了什么结论
    - 这一步的 epistemic status
    """
    step_index: int                    # 步骤序号
    premise: str                       # 前提/输入
    rule: str                          # 推理规则/逻辑操作
    conclusion: str                    # 本步结论
    status: EpistemicStatus = EpistemicStatus.LOGICAL_INFERENCE
    confidence: float = 0.9            # 这一步的置信度
    first_principles_invoked: List[str] = field(default_factory=list)
    alternatives_considered: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step_index,
            "premise": self.premise[:50],
            "rule": self.rule,
            "conclusion": self.conclusion[:50],
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class EpistemicReport:
    """
    认知信任度报告 — 关于一个输出结论的完整可信度分解

    这不是答案本身，而是"关于答案的可信度说明"。

    用户可以看到：
    - 这个结论的整体置信度
    - 哪些部分是已知的、哪些是推导的、哪些是推测的
    - 如果错了，怎么知道
    """
    id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:8]}")
    conclusion: str = ""               # 最终结论
    overall_confidence: float = 0.0    # 综合置信度
    status: EpistemicStatus = EpistemicStatus.UNKNOWN
    decomposition: List[AtomClaim] = field(default_factory=list)   # 原子声明分解
    reconstruction_chain: List[ReconstructionStep] = field(default_factory=list)
    unresolved_unknowns: List[str] = field(default_factory=list)    # 未解决的未知
    assumptions_made: List[str] = field(default_factory=list)       # 做出的假设
    confidence_breakdown: Dict[str, float] = field(default_factory=dict)  # 各项置信度分解
    limitations: List[str] = field(default_factory=list)            # 已知局限性
    falsification: str = ""              # 证伪条件
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id[:8],
            "conclusion": self.conclusion[:80],
            "confidence": round(self.overall_confidence, 3),
            "status": self.status.value,
            "claims": len(self.decomposition),
            "chain_length": len(self.reconstruction_chain),
            "unknowns": len(self.unresolved_unknowns),
            "assumptions": len(self.assumptions_made),
        }

    @property
    def is_fully_known(self) -> bool:
        """所有子声明都是已知的（没有未知需要重建）"""
        return len(self.unresolved_unknowns) == 0

    @property
    def transparency_summary(self) -> str:
        """人类可读的可信度摘要"""
        parts = [f"可信度: {self.overall_confidence:.0%}"]
        parts.append(f"认知状态: {self.status.value}")
        if self.unresolved_unknowns:
            parts.append(f"未解决未知: {len(self.unresolved_unknowns)} 项")
        if self.assumptions_made:
            parts.append(f"假设: {len(self.assumptions_made)} 项")
        if self.limitations:
            parts.append(f"限制: {'; '.join(self.limitations[:3])}")
        return " | ".join(parts)


# ──────────────────────────────────────────────────────────────────────
# 2. 知识分解器 (Knowledge Decomposer)
# ──────────────────────────────────────────────────────────────────────

class KnowledgeDecomposer:
    """
    知识分解器 — 把复杂问题拆成原子级子声明

    策略：
    1. 文本分割：按语义断点拆分
    2. 概念提取：提取问题中的关键概念
    3. 关系识别：识别概念之间的关系
    4. 原子化：保证每个子声明不再可分解
    """

    def __init__(self, long_term_memory: Optional[LongTermMemory] = None):
        self.ltm = long_term_memory
        # 已知概念的缓存（避免在长分解中重复检查）
        self._known_concepts: Set[str] = set()

    def decompose(self, question: str) -> List[AtomClaim]:
        """
        将问题分解为原子声明
        """
        atoms: List[AtomClaim] = []

        # 1. 先尝试概念级分解（识别已知概念）
        concept_atoms = self._extract_concept_atoms(question)
        known_concepts = [a for a in concept_atoms if a.status == EpistemicStatus.EMPIRICAL_OBSERVATION]

        if len(known_concepts) >= 2:
            # 在已知概念的情况下，直接使用概念原子作为主原子
            atoms = concept_atoms
        else:
            # 按标点拆分为子句
            clauses = self._split_into_clauses(question)
            for clause in clauses:
                clause_atoms = self._decompose_clause(clause)
                # 对每个子句原子尝试已知检查
                for ca in clause_atoms:
                    if len(ca.text) >= 2:
                        ca = self.check_known(ca)
                    atoms.append(ca)

            # 合并已知概念到结果中（去重后加入）
            existing = {a.text for a in atoms}
            for ca in concept_atoms:
                if ca.text not in existing:
                    atoms.append(ca)

        # 2. 过滤无意义短概念（疑问词、通用虚词）
        stop_words = {"什么", "多少", "怎么", "如何", "哪个", "哪些", "哪里", "为何", "谁", "何时"}
        atoms = [a for a in atoms if a.text not in stop_words]

        return atoms

    def check_known(self, claim: AtomClaim) -> AtomClaim:
        """
        检查一个原子声明是否在已知记忆中

        搜索策略：
        1. 精确搜索 content/title 匹配
        2. 如果精确搜索失败，检查已知概念缓存是否是该声明的子串
        3. 标签搜索作为补充
        """
        if not self.ltm:
            claim.status = EpistemicStatus.UNKNOWN
            claim.confidence = 0.0
            return claim

        text = claim.text.strip()

        # 1. 搜索长期记忆
        entries = self.ltm.search(text, limit=10)

        # 2. 标签搜索
        tags_to_search = [text[:8]] if len(text) >= 2 else []
        tags_entries = self.ltm.search_by_tags(tags_to_search, limit=5) if tags_to_search else []

        all_entries = entries + tags_entries

        found_known = False
        if all_entries:
            best = all_entries[0]
            if best.relevance_score > 0.5:
                claim.status = EpistemicStatus.EMPIRICAL_OBSERVATION
                claim.confidence = best.relevance_score
                claim.source = "memory"
                claim.supporting_evidence = [best.content[:100]]
                claim.related_memory_ids = [best.id]
                self._known_concepts.add(text[:20])
                found_known = True
            elif best.relevance_score > 0.3:
                claim.status = EpistemicStatus.SUPPORTED_HYPOTHESIS
                claim.confidence = best.relevance_score * 0.7
                claim.source = "memory_weak"
                claim.supporting_evidence = [best.content[:80]]
                found_known = True

        if not found_known:
            # 检查已识别的已知概念是否是该声明的子串
            matched_known = []
            for known in self._known_concepts:
                if len(known) >= 2 and known in text:
                    matched_known.append(known)
            if matched_known:
                claim.status = EpistemicStatus.SUPPORTED_HYPOTHESIS
                claim.confidence = 0.4
                claim.source = "partial_known"
                claim.supporting_evidence = [f"包含已知概念：{'、'.join(matched_known)}"]
            else:
                claim.status = EpistemicStatus.UNKNOWN
                claim.confidence = 0.0
                claim.source = "unknown"

        return claim

    def check_all_known(self, claims: List[AtomClaim]) -> List[AtomClaim]:
        """批量检查已知状态"""
        return [self.check_known(c) for c in claims]

    # ── 内部方法 ──

    def _split_into_clauses(self, text: str) -> List[str]:
        """按中文/英文标点拆分子句"""
        # 按问号、句号、分号、逗号拆分
        clauses = re.split(r'[？?。；;，,.\n]', text)
        return [c.strip() for c in clauses if len(c.strip()) > 3]

    def _decompose_clause(self, clause: str) -> List[AtomClaim]:
        """将一个子句分解为原子声明"""
        atoms = []

        # 提取关系结构：X是Y / X包含Y / X与Y的关系
        relation_patterns = [
            r'(.+?)是(.+)',       # X是Y
            r'(.+?)包含(.+)',     # X包含Y
            r'(.+?)和(.+?)的(.+)', # X和Y的Z关系
            r'(.+?)与(.+?)的(.+)', # X与Y的Z关系
        ]

        has_relation = False
        for pattern in relation_patterns:
            m = re.search(pattern, clause)
            if m:
                groups = m.groups()
                for g in groups:
                    if len(g) > 1:
                        atoms.append(AtomClaim(
                            text=g.strip(),
                            status=EpistemicStatus.UNKNOWN,
                            is_derived=True,
                        ))
                has_relation = True

        if not has_relation:
            # 没有发现关系结构，整体作为一个原子声明
            atoms.append(AtomClaim(
                text=clause.strip(),
                status=EpistemicStatus.UNKNOWN,
            ))

        return atoms

    def _extract_concept_atoms(self, text: str) -> List[AtomClaim]:
        """从文本中提取关键概念作为原子声明

        策略：从左到右扫描文本，检查已知记忆库中的概念是否出现在文本中。
        只检查记忆库中存在的概念，不生成无意义的组合。
        """
        import re

        atoms = []
        seen_texts = set()

        # 1. 优先识别对比结构中的概念
        compare_match = re.search(
            r'([\u4e00-\u9fffA-Za-z0-9_]+)(?:和|与|、)([\u4e00-\u9fffA-Za-z0-9_]+)(?:的|之)?(?:区别|对比|差异|不同|diff|vs|versus)',
            text
        )
        if compare_match:
            c1 = compare_match.group(1).strip()
            c2 = compare_match.group(2).strip()
            for c in [c1, c2]:
                if c and c not in seen_texts:
                    atom = AtomClaim(text=c, status=EpistemicStatus.UNKNOWN, is_derived=True)
                    atom = self.check_known(atom)
                    atoms.append(atom)
                    seen_texts.add(c)

        # 2. 英文概念直接提取
        en_concepts = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_]{2,}', text))
        for ec in sorted(en_concepts, key=len, reverse=True):
            if ec not in seen_texts:
                atom = AtomClaim(text=ec, status=EpistemicStatus.UNKNOWN, is_derived=True)
                atom = self.check_known(atom)
                atoms.append(atom)
                seen_texts.add(ec)

        # 3. 从长期记忆库中检索已知概念并检查是否在文本中出现
        if self.ltm:
            # 检索所有已知的语义记忆条目
            known_entries = self.ltm.recall(limit=50, sort_by="importance")
            known_titles = set()
            for entry in known_entries:
                # 使用 title 作为概念名
                title = (entry.title or "").strip()
                if title and len(title) >= 2 and title not in seen_texts:
                    known_titles.add(title)
                # 也使用内容截取
                content_first = entry.content[:10].strip()
                if content_first and len(content_first) >= 2 and content_first not in seen_texts:
                    if content_first in text:
                        known_titles.add(content_first)

            # 检查每个已知概念是否在查询文本中
            for title in sorted(known_titles, key=len, reverse=True):
                if title in text and title not in seen_texts:
                    atom = AtomClaim(text=title, status=EpistemicStatus.UNKNOWN, is_derived=True)
                    atom = self.check_known(atom)
                    atoms.append(atom)
                    seen_texts.add(title)

        return atoms

    def _merge_short_atoms(self, atoms: List[AtomClaim]) -> List[AtomClaim]:
        """合并过短的原子声明"""
        if len(atoms) <= 1:
            return atoms

        merged = []
        buffer = []
        for atom in atoms:
            if len(atom.text) < 3:
                buffer.append(atom.text)
            else:
                if buffer:
                    # 追加缓存的短文本到下一个有效声明
                    atom.text = " ".join(buffer) + " " + atom.text
                    buffer = []
                merged.append(atom)

        if buffer and merged:
            merged[-1].text += " " + " ".join(buffer)

        return merged or atoms


# ──────────────────────────────────────────────────────────────────────
# 3. 第一性原理重建器 (FP Reconstructor)
# ──────────────────────────────────────────────────────────────────────

class FPReconstructor:
    """
    第一性原理重建器 — 对未知声明从基本原理重建

    核心逻辑：
    1. 找到与该声明最相关的第一性原理
    2. 从原理出发，通过步步为营的逻辑推理，构建推理链
    3. 每一步标记 epistemic status
    4. 计算整条链的复合置信度
    """

    def __init__(self, fp_metacognition: Optional[FirstPrinciplesMetaCognition] = None):
        self.fp_mc = fp_metacognition or FirstPrinciplesMetaCognition()

        # 预定义的第一性原理知识库
        self._principle_library = {
            # ── 逻辑学 ──
            "同一律": EpistemicStatus.FIRST_PRINCIPLE,
            "排中律": EpistemicStatus.FIRST_PRINCIPLE,
            "矛盾律": EpistemicStatus.FIRST_PRINCIPLE,
            "充足理由律": EpistemicStatus.FIRST_PRINCIPLE,
            # ── 数学 ──
            "加法交换律": EpistemicStatus.FIRST_PRINCIPLE,
            "加法结合律": EpistemicStatus.FIRST_PRINCIPLE,
            "皮亚诺公理": EpistemicStatus.FIRST_PRINCIPLE,
            # ── 计算 ──
            "图灵完备": EpistemicStatus.FIRST_PRINCIPLE,
            "信息守恒": EpistemicStatus.FIRST_PRINCIPLE,
            # ── 通用认知 ──
            "证伪原则": EpistemicStatus.FIRST_PRINCIPLE,
            "奥卡姆剃刀": EpistemicStatus.ASSUMPTION,
            "层级抽象": EpistemicStatus.FIRST_PRINCIPLE,
            "递归自省": EpistemicStatus.FIRST_PRINCIPLE,
            # ── 经验原理 ──
            "守恒律": EpistemicStatus.FIRST_PRINCIPLE,
            "因果律": EpistemicStatus.FIRST_PRINCIPLE,
        }

        # 推理规则库（用于链式推导）
        self._inference_rules = [
            ("演绎", "如果 A 为真且 A → B 为真，则 B 为真"),
            ("归纳", "从多个具体实例中抽象出一般规律"),
            ("类比", "如果 A 和 B 在已知属性上相似，可能在未知属性上也相似"),
            ("反证", "如果假设 H 导致矛盾，则 H 为假"),
            ("分解", "复杂问题可以分解为更简单的子问题"),
            ("组合", "已知子问题的解可以组合为复杂问题的解"),
            ("对比", "如果 A 的属性和 B 的属性存在系统性差异，则 A ≠ B"),
            ("递归", "大问题的解法可以应用于同结构的子问题"),
        ]

    def reconstruct(self, claim: AtomClaim,
                    context: Optional[str] = None) -> Tuple[List[ReconstructionStep], float]:
        """
        对未知声明从第一性原理重建

        参数：
            claim:  需要重建的原子声明
            context: 原始上下文（可选，用于指导原理选择）

        返回：
            (重建步骤列表, 整体置信度)
        """
        if claim.status != EpistemicStatus.UNKNOWN:
            # 已知的声明不需要重建
            return [ReconstructionStep(
                step_index=0,
                premise=claim.text,
                rule="memory_retrieval",
                conclusion=claim.text,
                status=claim.status,
                confidence=claim.confidence,
            )], claim.confidence

        steps: List[ReconstructionStep] = []

        # ── Phase 1: 找到与该声明最相关的第一性原理 ──
        relevant_principles = self._find_relevant_principles(claim.text, context)
        if not relevant_principles:
            # 找不到相关原理，标记为推测
            steps.append(ReconstructionStep(
                step_index=0,
                premise=claim.text,
                rule="no_principle_found",
                conclusion=f"无法从已知第一性原理推导「{claim.text[:30]}」",
                status=EpistemicStatus.SPECULATION,
                confidence=0.1,
            ))
            return steps, 0.1

        # ── Phase 2: 为每个原理构建推理链 ──
        all_chains: List[List[ReconstructionStep]] = []

        for principle in relevant_principles[:3]:  # 最多用3个原理
            chain = self._build_reasoning_chain(claim.text, principle, context)
            if chain:
                all_chains.append(chain)

        if not all_chains:
            # 重建失败，标记为推测
            steps.append(ReconstructionStep(
                step_index=0,
                premise=claim.text,
                rule="reconstruction_failed",
                conclusion=f"对「{claim.text[:30]}」的重建尝试未形成有效推理链",
                status=EpistemicStatus.SPECULATION,
                confidence=0.15,
            ))
            return steps, 0.15

        # ── Phase 3: 选择最佳推理链 ──
        best_chain = self._select_best_chain(all_chains)
        steps.extend(best_chain)

        # ── Phase 4: 计算复合置信度 ──
        overall_confidence = self._compute_chain_confidence(best_chain)

        # ── Phase 5: 添加证伪反思 ──
        falsification_note = self._generate_falsification(claim.text, best_chain)
        if falsification_note:
            claim.supporting_evidence.append(falsification_note)

        return steps, overall_confidence

    def reconstruct_batch(self, claims: List[AtomClaim],
                          context: Optional[str] = None,
                          min_confidence: float = 0.3) -> List[AtomClaim]:
        """
        批量重建未知声明

        重建后更新每个 claim 的 status 和 confidence。
        置信度低于 min_confidence 的保持 UNKNOWN 状态。
        """
        for claim in claims:
            if claim.status == EpistemicStatus.UNKNOWN:
                steps, confidence = self.reconstruct(claim, context)
                claim.supporting_evidence = [s.conclusion for s in steps[:3]]

                if confidence >= min_confidence:
                    # 重建成功
                    claim.status = EpistemicStatus.LOGICAL_INFERENCE
                    claim.confidence = confidence
                    claim.source = "fp_reconstruction"
                else:
                    # 重建置信度不足，标记为推测
                    if confidence >= 0.1:
                        claim.status = EpistemicStatus.SPECULATION
                        claim.confidence = confidence
                        claim.source = "speculative"
                    # 低于0.1保持 UNKNOWN

        return claims

    # ── 内部方法 ──

    def _find_relevant_principles(self, text: str,
                                   context: Optional[str] = None) -> List[str]:
        """找到与文本最相关的第一性原理"""
        text_lower = text.lower()
        context_lower = (context or "").lower()
        combined = text_lower + " " + context_lower

        scored_principles = []

        # 按关键词匹配
        keyword_map = {
            "逻辑": ["同一律", "排中律", "矛盾律", "充足理由律"],
            "数学": ["皮亚诺公理", "加法交换律", "加法结合律"],
            "计算": ["图灵完备", "信息守恒"],
            "推理": ["演绎", "归纳", "反证"],
            "因果": ["因果律", "守恒律"],
            "证明": ["证伪原则", "反证"],
            "结构": ["层级抽象", "递归自省", "分解", "组合"],
            "复杂": ["分解", "层级抽象"],
            "比较": ["对比", "类比"],
            "系统": ["守恒律", "层级抽象", "递归自省"],
        }

        for keyword, principles in keyword_map.items():
            if keyword.lower() in combined:
                for p in principles:
                    if p in self._principle_library:
                        scored_principles.append((p, 1.0))
                    # 也检查推理规则
                    for rule_name, _ in self._inference_rules:
                        if p == rule_name:
                            scored_principles.append((p, 0.9))

        # 添加通用推理规则作为备选
        if not scored_principles:
            scored_principles = [("因果律", 0.5), ("充足理由律", 0.5)]

        # 去重并排序
        seen = set()
        unique_scored = []
        for p, score in scored_principles:
            if p not in seen:
                seen.add(p)
                unique_scored.append((p, score))

        unique_scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in unique_scored[:5]]

    def _build_reasoning_chain(self, claim_text: str,
                                principle: str,
                                context: Optional[str] = None) -> List[ReconstructionStep]:
        """
        从一个第一性原理出发构建推理链

        这是一个启发式算法，模拟从原理到结论的推理过程。
        在完整实现中，这部分会被 LLM 调用替代。
        """
        steps: List[ReconstructionStep] = []
        principle_status = self._principle_library.get(principle, EpistemicStatus.ASSUMPTION)

        # Step 1: 陈述原理
        steps.append(ReconstructionStep(
            step_index=1,
            premise="初始前提",
            rule="first_principle_invocation",
            conclusion=f"应用第一性原理：{principle}",
            status=principle_status,
            confidence=0.95,
            first_principles_invoked=[principle],
        ))

        # Step 2: 将原理与声明联系起来
        principle_description = self.fp_mc._first_principles.get(
            "logic" if "逻辑" in principle else
            "epistemology" if "原理" in principle else
            "cognition", []
        )
        relevant_descs = [d for d in principle_description[:2]
                         if any(kw in d for kw in claim_text[:5])]
        if not relevant_descs and principle_description:
            relevant_descs = [principle_description[0]]

        if relevant_descs:
            desc = relevant_descs[0]
            steps.append(ReconstructionStep(
                step_index=2,
                premise=desc,
                rule="principle_application",
                conclusion=f"原理阐释：{desc[:60]}",
                status=EpistemicStatus.LOGICAL_INFERENCE,
                confidence=0.85,
            ))

        # Step 3: 推理连接
        inference_rule = self._select_inference_rule(claim_text, principle)
        steps.append(ReconstructionStep(
            step_index=3,
            premise=principle,
            rule=inference_rule[0],
            conclusion=f"通过{inference_rule[0]}推理，{claim_text[:40]}",
            status=EpistemicStatus.LOGICAL_INFERENCE,
            confidence=0.75,
            first_principles_invoked=[principle],
        ))

        # Step 4: 得出结论
        steps.append(ReconstructionStep(
            step_index=4,
            premise=claim_text[:40],
            rule="conclusion",
            conclusion=f"结论：{claim_text[:50]}",
            status=EpistemicStatus.LOGICAL_INFERENCE,
            confidence=0.7,
        ))

        return steps

    def _select_inference_rule(self, claim_text: str,
                                principle: str) -> Tuple[str, str]:
        """选择合适的推理规则"""
        text_lower = claim_text.lower()

        if any(kw in text_lower for kw in ["如果", "那么", "if", "then", "因为"]):
            return ("演绎", "如果 A 为真且 A → B 为真，则 B 为真")
        if any(kw in text_lower for kw in ["类似", "像", "类比", "like", "as"]):
            return ("类比", "如果 A 和 B 在已知属性上相似，可能在未知属性上也相似")
        if any(kw in text_lower for kw in ["不同", "区别", "比较", "diff"]):
            return ("对比", "如果 A 和 B 的已知属性存在系统性差异，则 A ≠ B")
        if any(kw in text_lower for kw in ["结构", "组成", "包含", "分解"]):
            return ("分解", "复杂问题可以分解为更简单的子问题")

        return ("演绎", "从一般原理推导具体结论")

    def _compute_chain_confidence(self, chain: List[ReconstructionStep]) -> float:
        """计算整条推理链的复合置信度"""
        if not chain:
            return 0.0

        # 链式置信度 = 乘积（链的强度取决于最弱环节）
        confidences = [s.confidence for s in chain]
        product = 1.0
        for c in confidences:
            product *= c

        # 同时计算平均值（考虑链长）
        avg = sum(confidences) / len(confidences)

        # 复合置信度：乘积（最弱环节效应）+ 平均值的加权
        chain_length_penalty = max(0.9, 1.0 - len(chain) * 0.02)
        composite = (product * 0.4 + avg * 0.6) * chain_length_penalty

        return min(1.0, max(0.0, composite))

    def _select_best_chain(self, chains: List[List[ReconstructionStep]]) -> List[ReconstructionStep]:
        """从多条推理链中选择最佳的一条"""
        if len(chains) == 1:
            return chains[0]

        scored = []
        for chain in chains:
            confidence = self._compute_chain_confidence(chain)
            # 优先选择置信度高且较短（更简洁）的链
            length_score = 1.0 - len(chain) * 0.05
            scored.append((chain, confidence * 0.7 + length_score * 0.3))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def _generate_falsification(self, claim: str, chain: List[ReconstructionStep]) -> str:
        """生成证伪条件"""
        if not chain:
            return "无法证伪——缺少推理链"

        # 基于推理链的最弱环节确定证伪条件
        weakest = min(chain, key=lambda s: s.confidence)
        return (f"如果 {weakest.conclusion[:30]} 不成立，则整个推理链失效（"
                f"最弱环节在第{weakest.step_index}步，置信度{weakest.confidence:.0%}）")


# ──────────────────────────────────────────────────────────────────────
# 4. 真理级建构引擎 (TruthGroundingEngine)
# ──────────────────────────────────────────────────────────────────────

class TruthGroundingEngine:
    """
    真理级知识建构引擎 — 主编排器

    这是对外暴露的统一接口。

    核心管线：
        query
          → [Decomposer] 分解为原子声明
          → [Known Check] 检查每个声明是否已知
          → [FP Reconstructor] 重建未知声明
          → [Epistemic Reporter] 生成可信度报告
          → [Output] 带标签的结论

    使用方式：
        engine = TruthGroundingEngine(long_term_memory=ltm)
        report = engine.ground("什么是量子纠缠？")
        # report.conclusion — 结果
        # report.overall_confidence — 可信度
        # report.transparency_summary — 人类可读摘要
        # report.reconstruction_chain — 推理链（可回溯）
    """

    def __init__(self,
                 long_term_memory: Optional[LongTermMemory] = None,
                 fp_metacognition: Optional[FirstPrinciplesMetaCognition] = None,
                 ):
        self.ltm = long_term_memory
        self.fp_mc = fp_metacognition or FirstPrinciplesMetaCognition()
        self.decomposer = KnowledgeDecomposer(long_term_memory)
        self.reconstructor = FPReconstructor(self.fp_mc)

    # ── 核心入口 ──

    def ground(self, query: str) -> EpistemicReport:
        """
        对一个问题进行真理级知识建构

        返回 EpistemicReport，包含结论和完整的可信度分解。
        """
        # 1. 分解为原子声明
        atoms = self.decomposer.decompose(query)

        # 2. 检查每个声明的认知状态
        atoms = self.decomposer.check_all_known(atoms)

        # 3. 重建未知声明
        atoms = self.reconstructor.reconstruct_batch(atoms, context=query)

        # 4. 收集结果
        known_atoms = [a for a in atoms
                      if a.status in (EpistemicStatus.EMPIRICAL_OBSERVATION,
                                      EpistemicStatus.FIRST_PRINCIPLE)]
        derived_atoms = [a for a in atoms
                        if a.status == EpistemicStatus.LOGICAL_INFERENCE]
        unknown_atoms = [a for a in atoms
                        if a.status == EpistemicStatus.UNKNOWN]
        speculative_atoms = [a for a in atoms
                           if a.status == EpistemicStatus.SPECULATION]
        assumptions = [a for a in atoms
                      if a.status == EpistemicStatus.ASSUMPTION]

        # 5. 合成结论
        conclusion = self._synthesize_conclusion(atoms, query)

        # 6. 计算综合置信度
        overall_confidence = self._compute_overall_confidence(atoms)

        # 7. 确定整体认知状态
        if unknown_atoms:
            overall_status = EpistemicStatus.SUPPORTED_HYPOTHESIS
        elif speculative_atoms:
            overall_status = EpistemicStatus.SPECULATION
        elif derived_atoms and not known_atoms:
            overall_status = EpistemicStatus.LOGICAL_INFERENCE
        elif known_atoms and not derived_atoms:
            overall_status = EpistemicStatus.EMPIRICAL_OBSERVATION
        else:
            overall_status = EpistemicStatus.LOGICAL_INFERENCE

        # 8. 收集推理链
        chain = []
        for atom in atoms:
            if atom.supporting_evidence:
                for i, ev in enumerate(atom.supporting_evidence[:2]):
                    chain.append(ReconstructionStep(
                        step_index=len(chain) + 1,
                        premise=atom.text,
                        rule=atom.source,
                        conclusion=ev[:60],
                        status=atom.status,
                        confidence=atom.confidence,
                    ))

        # 9. 构建可信度分解
        breakdown = {}
        if known_atoms:
            breakdown["known"] = sum(a.confidence for a in known_atoms) / len(known_atoms)
        if derived_atoms:
            breakdown["derived"] = sum(a.confidence for a in derived_atoms) / len(derived_atoms)
        if speculative_atoms:
            breakdown["speculative"] = sum(a.confidence for a in speculative_atoms) / len(speculative_atoms)

        # 验证查询中是否包含"对比""区别"等词汇
        has_compare_query = any(kw in query for kw in ["区别", "对比", "比较", "diff", "difference", "vs", "versus"])

        # 10. 构建报告
        report = EpistemicReport(
            conclusion=conclusion,
            overall_confidence=overall_confidence,
            status=overall_status,
            decomposition=atoms,
            reconstruction_chain=chain,
            unresolved_unknowns=[a.text for a in unknown_atoms],
            assumptions_made=[a.text for a in assumptions],
            confidence_breakdown=breakdown,
        )

        # 11. 局限性分析
        limitations = []
        if unknown_atoms:
            limitations.append(f"存在 {len(unknown_atoms)} 个未知声明未解决")
        if speculative_atoms:
            limitations.append(f"{len(speculative_atoms)} 个声明基于推测，置信度低")
        if has_compare_query and not derived_atoms:
            limitations.append("比较类问题的推理链可能不完整")
        if overall_confidence < 0.5:
            limitations.append("整体置信度低于0.5，结论可能是推测性的")
        report.limitations = limitations

        return report

    # ── 三态防幻觉 facade ──────────────────────────────────────

    # 已知事实冲突的硬编码黑名单（启发式），用于触发 error 态
    _KNOWN_FALSE_FACTS: Tuple[str, ...] = (
        "1+1=3", "1 + 1 = 3", "2+2=5", "2 + 2 = 5",
        "地球是平的", "地球是平", "地平说",
        "太阳绕着地球转", "太阳绕地球转",
        "pi=3", "π=3",
    )

    # 绝对化词汇（无证据时触发 error 态）
    _ABSOLUTE_MARKERS: Tuple[str, ...] = (
        "绝对", "肯定", "毫无疑问", "100%确定", "百分之百",
        "绝对正确", "绝对是真的", "绝对是",
        "definitely true", "absolutely true", "without doubt",
    )

    def ground_three_state(
        self,
        claim: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """三态防幻觉 facade — 把 EpistemicReport 映射为 grounded/uncertain/error。

        本方法是为防幻觉管线提供的对外稳定接口：不直接暴露 EpistemicStatus
        枚举，而是返回 ``{state, confidence, evidence, conflicts?}`` 的简单
        字典，供 MCP / sidecar / hub 路径消费。

        三态判定规则（按优先级）：

        1. ``error`` — 下列任一成立：
           * ``ground()`` 返回 ``status`` 为 ``CONTRADICTION`` 或 ``BIAS``；
           * 启发式检测到 ``claim`` 命中已知事实黑名单（如 ``1+1=3``、
             ``地球是平的``）；
           * 启发式检测到 ``claim`` 含绝对化词汇（如 ``绝对``、``毫无疑问``）
             且 ``ground()`` 未达 grounded 级支撑（即 status 不在
             {EMPIRICAL_OBSERVATION, FIRST_PRINCIPLE, LOGICAL_INFERENCE}
             或 confidence < 0.6）。
        2. ``grounded`` — ``status`` ∈
           {EMPIRICAL_OBSERVATION, FIRST_PRINCIPLE, LOGICAL_INFERENCE}
           且 ``overall_confidence ≥ 0.6``。
        3. ``uncertain`` — 其它情况（含 SUPPORTED_HYPOTHESIS / SPECULATION /
           ASSUMPTION / UNKNOWN，或低置信的 grounded 态）。

        Args:
            claim: 待检验的事实论断文本。
            context: 可选上下文，仅参与启发式冲突检测，不传给 ``ground()``
                （底层 ``ground()`` 只接受 query）。

        Returns:
            ``{"state": str, "confidence": float, "evidence": List[str]}``，
            当 ``state == "error"`` 时额外返回
            ``{"conflicts": List[str]}`` 字段描述冲突来源。
        """
        # 调用既有 ground（只接受 query）
        report = self.ground(claim)

        # 收集证据：优先用重建链结论，回退到原子声明文本
        evidence: List[str] = []
        for step in report.reconstruction_chain:
            if step.conclusion and step.conclusion not in evidence:
                evidence.append(step.conclusion)
        if not evidence:
            for atom in report.decomposition:
                if atom.supporting_evidence:
                    evidence.extend(atom.supporting_evidence[:2])
                else:
                    evidence.append(atom.text)
        # 截断，避免回包过大
        evidence = evidence[:5]

        confidence = float(round(report.overall_confidence, 4))
        status = report.status

        # ── 冲突检测 ──
        conflicts: List[str] = []
        combined_text = f"{claim} {context or ''}"

        # 1) 已知事实黑名单
        for false_fact in self._KNOWN_FALSE_FACTS:
            if false_fact in combined_text:
                conflicts.append(f"known_false_fact: {false_fact}")

        # 2) 绝对化词汇 + 无 grounded 级证据
        #    绝对化论断要求 grounded 级支撑（status ∈ grounded 三态且
        #    confidence ≥ 0.6），仅凭 FP 重建的弱推导不算"证据"。
        has_absolute = any(m in claim for m in self._ABSOLUTE_MARKERS)
        is_grounded_level = (
            status in (
                EpistemicStatus.EMPIRICAL_OBSERVATION,
                EpistemicStatus.FIRST_PRINCIPLE,
                EpistemicStatus.LOGICAL_INFERENCE,
            )
            and confidence >= 0.6
        )
        if has_absolute and not is_grounded_level:
            conflicts.append(
                "absolute_claim_without_evidence: 含绝对化词汇但未达 grounded 级支撑"
            )

        # 3) 底层 status 为 CONTRADICTION / BIAS
        if status == EpistemicStatus.CONTRADICTION:
            conflicts.append("epistemic_status: CONTRADICTION")
        if status == EpistemicStatus.BIAS:
            conflicts.append("epistemic_status: BIAS")

        # ── 三态映射 ──
        if conflicts:
            state = "error"
        elif status in (
            EpistemicStatus.EMPIRICAL_OBSERVATION,
            EpistemicStatus.FIRST_PRINCIPLE,
            EpistemicStatus.LOGICAL_INFERENCE,
        ) and confidence >= 0.6:
            state = "grounded"
        else:
            state = "uncertain"

        result: Dict[str, Any] = {
            "state": state,
            "confidence": confidence,
            "evidence": evidence,
        }
        if state == "error":
            result["conflicts"] = conflicts
        return result

    # ── 内部方法 ──

    def _synthesize_conclusion(self, atoms: List[AtomClaim], query: str) -> str:
        """从原子声明合成最终结论"""
        known_entities = [a.text for a in atoms
                         if a.status in (EpistemicStatus.EMPIRICAL_OBSERVATION,
                                         EpistemicStatus.FIRST_PRINCIPLE)]
        derived_entities = [a.text for a in atoms
                           if a.status == EpistemicStatus.LOGICAL_INFERENCE]
        speculative_entities = [a.text for a in atoms
                               if a.status == EpistemicStatus.SPECULATION]
        unknown_entities = [a.text for a in atoms
                           if a.status == EpistemicStatus.UNKNOWN]

        conclusion_parts = []

        if known_entities:
            conclusion_parts.append(
                f"已知概念：{'、'.join(known_entities[:4])}"
            )

        if derived_entities:
            conclusion_parts.append(
                f"由基本原理推导：{'、'.join(derived_entities[:4])}"
            )

        if speculative_entities:
            conclusion_parts.append(
                f"推测性结论（请验证）：{'、'.join(speculative_entities[:3])}"
            )

        if unknown_entities:
            conclusion_parts.append(
                f"未解决：{'、'.join(unknown_entities[:3])}"
            )

        if not conclusion_parts:
            return f"对「{query[:40]}」暂无足够知识，标记为未知领域"

        return "；".join(conclusion_parts)[:200]

    def _compute_overall_confidence(self, atoms: List[AtomClaim]) -> float:
        """计算综合置信度"""
        if not atoms:
            return 0.0

        # 按数量加权
        total_weight = 0.0
        weighted_sum = 0.0

        for atom in atoms:
            w = atom.confidence
            if atom.status == EpistemicStatus.EMPIRICAL_OBSERVATION:
                w *= 1.0  # 已知最高权重
            elif atom.status == EpistemicStatus.LOGICAL_INFERENCE:
                w *= 0.8  # 推导次之
            elif atom.status == EpistemicStatus.SPECULATION:
                w *= 0.3  # 推测降权
            elif atom.status == EpistemicStatus.UNKNOWN:
                w *= 0.0  # 未知贡献0

            total_weight += 1.0
            weighted_sum += w

        return weighted_sum / total_weight if total_weight > 0 else 0.0


# ──────────────────────────────────────────────────────────────────────
# 5. 集成工厂
# ──────────────────────────────────────────────────────────────────────

def create_truth_grounding_engine(
    long_term_memory: Optional[LongTermMemory] = None,
) -> TruthGroundingEngine:
    """
    创建并初始化真理级建构引擎

    依赖：
        - 如果提供 long_term_memory，会用来检查已有知识
    """
    fp_mc = FirstPrinciplesMetaCognition()
    engine = TruthGroundingEngine(
        long_term_memory=long_term_memory,
        fp_metacognition=fp_mc,
    )
    logger.info("真理级知识建构引擎初始化完成")
    return engine
