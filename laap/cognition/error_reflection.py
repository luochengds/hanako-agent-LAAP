"""
LAAP — 错误反思管道 (Error Reflection Pipeline)

==============================
  错误不是终点，是认知校准信号
==============================

核心理念：
  当 LAAP 答错问题后，不仅仅是记录"我错了"，
  而是自动生成"为什么错了"的解释帧，
  写入长期语义记忆作为触发校准信号。
  下次遇到类似问题时，错误帧以负权重参与推理，
  在同样的决策分岔口拉回正确路径。

架构：
  1. ErrorReflectionFrame  — 结构化错误帧
  2. TriggerIndex          — 触发条件匹配引擎
  3. CalibrationRetrieval  — 新查询时的校准检索
  4. ErrorReflectionPipeline — 主编排器

与 IntegratedCognitiveEngine 的集成：
  - record_failure() 自动触发 Pipeline
  - _retrieve_relevant_memories() 追加校准检索
  - 对外暴露 submit_error_feedback(query, wrong, correct) 接口

依赖：
  - laap.memory.long_term (LongTermMemory, MemoryEntry, MemoryType)
  - laap.cognition.integrated_engine (CognitiveAction, etc.)
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from laap.memory.long_term import LongTermMemory, MemoryEntry, MemoryType

logger = logging.getLogger("laap.cognition.error_reflection")

# ──────────────────────────────────────────────────────────────────────
# 1. 错误反思帧数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ReasoningTraceNode:
    """
    推理轨迹节点 — 记录一次推理决策的分叉点

    每个节点代表推理路径中的一个关键步骤：
    - 当时的推理内容
    - 考虑过的替代方向
    - 置信度评估
    - 最终选择
    """
    step: int                          # 步骤序号
    description: str                   # 这一步在做什么
    reasoning: str                     # 当时的推理过程
    alternatives: List[str] = field(default_factory=list)   # 考虑过的替代可能性
    chosen_direction: str = ""         # 最终选择的方向
    confidence_at_step: float = 0.5    # 当时的置信度
    was_correct_branch: Optional[bool] = None  # 事后看这条分支是否正确


@dataclass
class ErrorReflectionFrame:
    """
    错误反思帧 — 对一次错误输出的完整诊断

    核心字段：
    - original_query:     触发错误的原始问题
    - wrong_answer:       实际输出的错误答案
    - correct_answer:     正确答案（由外部提供或系统推断）
    - gap_analysis:       差距分析 — "我为什么想错了"
    - reasoning_trace:    当时的推理轨迹（冻结的快照）
    - trigger_keywords:   触发索引关键词（用于下次检索匹配）
    - calibration_weight: 校准强度 0-1（控制在未来推理中的影响力度）
    - root_cause:         "认知偏误"类型的归因分类
    - fix_strategy:       下一次遇到类似情况应该怎么做的具体指导
    """
    # ── 标识 ──
    frame_id: str = field(default_factory=lambda: f"err_{uuid.uuid4().hex[:8]}")
    created_at: float = field(default_factory=time.time)

    # ── 错误上下文 ──
    original_query: str = ""
    wrong_answer: str = ""
    correct_answer: str = ""
    confidence_at_output: float = 0.5   # 输出时的置信度

    # ── 诊断 ──
    gap_analysis: str = ""              # "我原本以为X，但实际上Y，因为我遗漏了Z"
    root_cause: str = "unknown"         # 认知偏误类型（见 ROOT_CAUSE_CATEGORIES）
    reasoning_trace: List[ReasoningTraceNode] = field(default_factory=list)

    # ── 校准信息 ──
    trigger_keywords: List[str] = field(default_factory=list)
    calibration_weight: float = 0.6     # 0.0=忽略, 1.0=强烈校准
    fix_strategy: str = ""              # "下次这类问题应该先做A，再检查B"
    fix_confidence: float = 0.7         # 对修正策略的确信度

    # ── 元数据 ──
    category: str = "general"           # 错误大类
    subcategory: str = "unspecified"    # 错误子类
    source: str = "self_check"          # self_check | user_feedback | external_eval
    effective_count: int = 0            # 该校准被触发/应用过的次数
    last_effective_at: Optional[float] = None  # 最近一次生效的时间

    # ── 序列化 ──
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于存储到 long_term_memory）"""
        return {
            "frame_id": self.frame_id,
            "original_query": self.original_query,
            "wrong_answer": self.wrong_answer,
            "correct_answer": self.correct_answer,
            "gap_analysis": self.gap_analysis,
            "root_cause": self.root_cause,
            "reasoning_trace": [
                {
                    "step": n.step,
                    "description": n.description,
                    "reasoning": n.reasoning,
                    "alternatives": n.alternatives,
                    "chosen_direction": n.chosen_direction,
                    "confidence_at_step": n.confidence_at_step,
                    "was_correct_branch": n.was_correct_branch,
                }
                for n in self.reasoning_trace
            ],
            "trigger_keywords": self.trigger_keywords,
            "calibration_weight": self.calibration_weight,
            "fix_strategy": self.fix_strategy,
            "fix_confidence": self.fix_confidence,
            "category": self.category,
            "subcategory": self.subcategory,
            "source": self.source,
            "effective_count": self.effective_count,
            "confidence_at_output": self.confidence_at_output,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ErrorReflectionFrame:
        """从字典反序列化"""
        trace_data = data.get("reasoning_trace", [])
        trace = [
            ReasoningTraceNode(
                step=n.get("step", 0),
                description=n.get("description", ""),
                reasoning=n.get("reasoning", ""),
                alternatives=n.get("alternatives", []),
                chosen_direction=n.get("chosen_direction", ""),
                confidence_at_step=n.get("confidence_at_step", 0.5),
                was_correct_branch=n.get("was_correct_branch"),
            )
            for n in trace_data
        ]

        return cls(
            frame_id=data.get("frame_id", ""),
            original_query=data.get("original_query", ""),
            wrong_answer=data.get("wrong_answer", ""),
            correct_answer=data.get("correct_answer", ""),
            gap_analysis=data.get("gap_analysis", ""),
            root_cause=data.get("root_cause", "unknown"),
            reasoning_trace=trace,
            trigger_keywords=data.get("trigger_keywords", []),
            calibration_weight=data.get("calibration_weight", 0.6),
            fix_strategy=data.get("fix_strategy", ""),
            fix_confidence=data.get("fix_confidence", 0.7),
            category=data.get("category", "general"),
            subcategory=data.get("subcategory", "unspecified"),
            source=data.get("source", "self_check"),
            effective_count=data.get("effective_count", 0),
            confidence_at_output=data.get("confidence_at_output", 0.5),
            created_at=data.get("created_at", 0.0),
        )


# ──────────────────────────────────────────────────────────────────────
# 认知偏误分类体系
# ──────────────────────────────────────────────────────────────────────

ROOT_CAUSE_CATEGORIES = {
    "overconfidence": "过度自信 — 给出了超出证据支持的断言",
    "missing_context": "遗漏上下文 — 没有充分考虑相关背景信息",
    "wrong_assumption": "错误假设 — 推理依赖了一个不正确的前提",
    "factual_error": "事实错误 — 引用了错误或不存在的知识",
    "logical_fallacy": "逻辑谬误 — 推理链中存在逻辑跳跃或断裂",
    "confirmation_bias": "确认偏误 — 只选择了支持已有信念的证据",
    "premature_closure": "过早闭合 — 在信息不足时就给出了结论",
    "causal_misattribution": "因果误归 — 错误地建立了因果关系",
    "analogy_drift": "类比漂移 — 使用了不恰当的类比",
    "ambiguity_mishandled": "歧义处理不当 — 没有识别或澄清关键歧义",
    "numerical_error": "数值错误 — 计算或数量关系错误",
    "temporal_error": "时序错误 — 对时间/顺序关系理解错误",
    "level_confusion": "层次混淆 — 混淆了不同抽象层次的概念",
    "category_error": "范畴错误 — 把事物归入了不恰当的类别",
    "anchoring": "锚定效应 — 被初始信息过度影响",
}


# ──────────────────────────────────────────────────────────────────────
# 2. 触发索引 (Trigger Index)
# ──────────────────────────────────────────────────────────────────────

class TriggerIndex:
    """
    触发索引 — 把错误帧的触发条件映射为可检索的索引

    核心逻辑：
      - 每个错误帧有一组 trigger_keywords
      - 新查询到来时，检查查询内容与 trigger_keywords 的匹配度
      - 高于阈值的错误帧作为"校准信号"返回

    匹配策略：
      1. 关键词精确匹配（加权）
      2. 主题共现匹配
      3. 标签组合匹配
    """

    def __init__(self):
        # keyword -> [(frame_id, weight), ...]
        self._keyword_index: Dict[str, List[Tuple[str, float]]] = {}
        # category -> [frame_id, ...]
        self._category_index: Dict[str, List[str]] = {}
        # frame_id -> ErrorReflectionFrame
        self._frame_cache: Dict[str, ErrorReflectionFrame] = {}

    def register(self, frame: ErrorReflectionFrame) -> None:
        """
        注册一个错误帧到索引
        """
        frame_id = frame.frame_id
        self._frame_cache[frame_id] = frame

        # 按关键词索引
        for kw in frame.trigger_keywords:
            kw_lower = kw.lower().strip()
            if kw_lower not in self._keyword_index:
                self._keyword_index[kw_lower] = []
            self._keyword_index[kw_lower].append(
                (frame_id, frame.calibration_weight)
            )

        # 按分类索引
        cat = f"{frame.category}/{frame.subcategory}"
        if cat not in self._category_index:
            self._category_index[cat] = []
        self._category_index[cat].append(frame_id)

    def unregister(self, frame_id: str) -> None:
        """从索引中移除一个错误帧"""
        self._frame_cache.pop(frame_id, None)
        for kw in list(self._keyword_index.keys()):
            self._keyword_index[kw] = [
                (fid, w) for fid, w in self._keyword_index[kw]
                if fid != frame_id
            ]
            if not self._keyword_index[kw]:
                del self._keyword_index[kw]
        for cat in list(self._category_index.keys()):
            self._category_index[cat] = [
                fid for fid in self._category_index[cat] if fid != frame_id
            ]
            if not self._category_index[cat]:
                del self._category_index[cat]

    def query(self, query_text: str, top_k: int = 5,
              min_weight: float = 0.3) -> List[Tuple[ErrorReflectionFrame, float]]:
        """
        根据查询文本检索最相关的错误帧

        返回：
          [(ErrorReflectionFrame, 匹配分数)], 按分数降序
        """
        # 1. 查询词拆分
        query_terms = self._tokenize(query_text)
        if not query_terms:
            return []

        # 2. 计算每个错误帧的匹配分数
        frame_scores: Dict[str, float] = {}

        # 关键词匹配
        for term in query_terms:
            if term in self._keyword_index:
                for frame_id, weight in self._keyword_index[term]:
                    # 精确命中给最高分
                    frame_scores[frame_id] = max(
                        frame_scores.get(frame_id, 0.0),
                        1.0 * weight
                    )

            # 模糊匹配：关键词是term的子串或term是关键字的子串
            for keyword, entries in self._keyword_index.items():
                if len(term) >= 2 and len(keyword) >= 2:
                    if term in keyword or keyword in term:
                        for frame_id, weight in entries:
                            similarity = min(len(term), len(keyword)) / max(len(term), len(keyword))
                            score = similarity * weight * 0.7  # 模糊匹配折扣
                            frame_scores[frame_id] = max(
                                frame_scores.get(frame_id, 0.0),
                                score
                            )

        # 3. 按分类匹配——检查错误分类标签与查询内容的重叠
        for cat, frame_ids in self._category_index.items():
            cat_terms = set(self._tokenize(cat))
            query_set = set(query_terms)
            overlap = len(cat_terms & query_set)
            if overlap > 0:
                boost = overlap / max(len(cat_terms), 1) * 0.5
                for frame_id in frame_ids:
                    frame_scores[frame_id] = max(
                        frame_scores.get(frame_id, 0.0),
                        boost
                    )

        # 4. 排序并过滤
        scored_frames = []
        for frame_id, score in frame_scores.items():
            if score >= min_weight and frame_id in self._frame_cache:
                scored_frames.append((self._frame_cache[frame_id], score))

        scored_frames.sort(key=lambda x: x[1], reverse=True)

        return scored_frames[:top_k]

    def get_all_frames(self) -> List[ErrorReflectionFrame]:
        """获取所有已注册的帧"""
        return list(self._frame_cache.values())

    def count(self) -> int:
        """已注册的错误帧数量"""
        return len(self._frame_cache)

    def clear(self) -> None:
        """清空索引"""
        self._keyword_index.clear()
        self._category_index.clear()
        self._frame_cache.clear()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """分词：提取英文单词、中文二元组（2-gram 滑动窗口）"""
        if not text:
            return []

        import re
        tokens = []

        # 英文分词：提取英文单词
        english_words = re.findall(r'[a-zA-Z_][a-zA-Z_0-9]{1,}', text)
        for word in english_words:
            tokens.append(word.lower())

        # 数字
        numbers = re.findall(r'\d+', text)
        tokens.extend(numbers)

        # 中文：2-gram 滑动窗口
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        if len(chinese_chars) >= 2:
            for i in range(len(chinese_chars) - 1):
                tokens.append(chinese_chars[i] + chinese_chars[i + 1])
            # 也保留完整连续串前6字和后6字
            full = ''.join(chinese_chars)
            if len(full) <= 6:
                tokens.append(full)
            else:
                tokens.append(full[:6])
                tokens.append(full[-6:])

        # 去重
        return list(set(tokens))


# ──────────────────────────────────────────────────────────────────────
# 3. 校准信号生成
# ──────────────────────────────────────────────────────────────────────

class CalibrationSignal:
    """
    校准信号 — 用于注入到推理过程中的修正信息

    当 ErrorReflectionPipeline 检测到当前查询触发了某个错误帧时，
    生成一个 CalibrationSignal 传递到推理引擎，
    引导引擎在推理时考虑过去的错误教训。
    """

    def __init__(self, frame: ErrorReflectionFrame, match_score: float):
        self.frame = frame
        self.match_score = match_score

    @property
    def effective_weight(self) -> float:
        """综合有效权重 = 校准强度 * 匹配度 * 修正置信度"""
        return (
            self.frame.calibration_weight *
            self.match_score *
            self.frame.fix_confidence
        )

    def to_prompt_block(self) -> str:
        """
        转换为可供推理引擎注入的 prompt 片段

        格式：
          ⚠ 校准信号 [权重={weight:.2f}]
          曾经犯过的错误：{gap_analysis}
          修正策略：{fix_strategy}
        """
        weight = self.effective_weight
        if weight < 0.15:
            # 权重太低，不注入
            return ""

        block = (
            f"[CALIBRATION weight={weight:.2f}]\n"
            f"类似问题曾经出过错——错误分析：{self.frame.gap_analysis}\n"
            f"修正策略：{self.frame.fix_strategy}\n"
            f"错误时的答案（作为反面参考）：{self.frame.wrong_answer}\n"
            f"正确答案（作为参考）：{self.frame.correct_answer}\n"
            f"[/CALIBRATION]"
        )
        return block


# ──────────────────────────────────────────────────────────────────────
# 4. 错误反思管道主编排器
# ──────────────────────────────────────────────────────────────────────

class ErrorReflectionPipeline:
    """
    错误反思管道主编排器

    核心流程：
      1. capture()     — 捕获错误上下文（查询、错误答案、推理轨迹）
      2. analyze()     — 生成差距分析和修正策略
      3. store()       — 存储为长期记忆并注册到触发索引
      4. calibrate()   — 对新查询检索相关校准信号

    生命周期：
      创建管道时：
        - 从 long_term_memory 中恢复已有的校准帧重建索引
      每次错误时：
        - capture → analyze → store
      每次推理时：
        - calibrate → 返回校准信号列表
    """

    DEFAULT_CALIBRATION_MEMORY_TAG = "error_calibration"

    def __init__(self, long_term_memory: Optional[LongTermMemory] = None):
        self.ltm: Optional[LongTermMemory] = long_term_memory
        self.trigger_index = TriggerIndex()
        self._loaded = False
        self._frame_history: List[ErrorReflectionFrame] = []

    # ── 初始化与恢复 ──────────────────────────────────────────────

    def restore_from_memory(self) -> int:
        """
        从 long_term_memory 中恢复已有的校准帧

        检索所有带 error_calibration 标签的语义记忆，
        反序列化为 ErrorReflectionFrame 并注册到触发索引。

        返回：
            恢复的错误帧数量
        """
        if not self.ltm:
            logger.warning("无法恢复校准帧：未提供 long_term_memory")
            return 0

        # 用标签搜索检索校准记忆
        entries = self.ltm.search_by_tags(
            tags=[self.DEFAULT_CALIBRATION_MEMORY_TAG],
            limit=200,
        )

        restored = 0
        for entry in entries:
            if self.DEFAULT_CALIBRATION_MEMORY_TAG not in entry.tags:
                continue
            try:
                metadata = entry.metadata
                if "error_frame" in metadata:
                    frame_data = metadata["error_frame"]
                    if isinstance(frame_data, str):
                        frame_data = json.loads(frame_data)
                    frame = ErrorReflectionFrame.from_dict(frame_data)
                    self.trigger_index.register(frame)
                    self._frame_history.append(frame)
                    restored += 1
            except Exception as e:
                logger.debug(f"恢复校准帧失败: {e}")

        self._loaded = True
        logger.info(f"从长期记忆恢复 {restored} 条校准帧")
        return restored

    # ── 核心流程 ──────────────────────────────────────────────────

    def capture(self, *,
                query: str,
                wrong_answer: str,
                correct_answer: str,
                confidence: float = 0.5,
                reasoning_trace: Optional[List[ReasoningTraceNode]] = None,
                source: str = "self_check",
                ) -> ErrorReflectionFrame:
        """
        第1步：捕获错误上下文

        参数：
            query:          原始查询
            wrong_answer:   实际输出的错误答案
            correct_answer: 正确答案
            confidence:     输出时的置信度
            reasoning_trace:推理轨迹快照（可选）
            source:         错误来源

        返回：
            初步构建的 ErrorReflectionFrame（尚未分析）
        """
        # 提取触发关键词
        trigger_keywords = self._extract_trigger_keywords(
            query, wrong_answer, correct_answer
        )

        frame = ErrorReflectionFrame(
            original_query=query,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            confidence_at_output=confidence,
            reasoning_trace=reasoning_trace or [],
            trigger_keywords=trigger_keywords,
            source=source,
            tags=[
                self.DEFAULT_CALIBRATION_MEMORY_TAG,
                "error_reflection",
                source,
            ],
        )

        logger.debug(f"捕获错误帧: {frame.frame_id[:8]} | query={query[:40]}")
        return frame

    def analyze(self, frame: ErrorReflectionFrame) -> ErrorReflectionFrame:
        """
        第2步：分析错误，生成差距分析和修正策略

        根据推理轨迹和错误对比：
        - 如果有关键词匹配，自动判断 root_cause
        - 生成 gap_analysis 描述推理断点
        - 生成 fix_strategy 指导下次

        参数：
            frame: 初步构建的错误帧

        返回：
            已填充分析的错误帧
        """
        trace = frame.reasoning_trace

        # ── 2a. 从推理轨迹中提取关键断点 ──
        if trace:
            # 找到与正确答案分歧最大的节点
            divergences = [
                n for n in trace
                if n.was_correct_branch is False
            ]
            if divergences:
                first_div = divergences[0]
                frame.gap_analysis = (
                    f"在第{first_div.step}步推理时出现了偏差。"
                    f"当时推理为：{first_div.reasoning}。"
                    f"选择了方向「{first_div.chosen_direction}」，"
                    f"未充分考虑替代方向：{'、'.join(first_div.alternatives[:3])}。"
                )
            else:
                # 没有显式标记错误分支——从高置信步骤推断
                high_conf_steps = [
                    n for n in trace
                    if n.confidence_at_step > 0.8
                ]
                if high_conf_steps:
                    worst = high_conf_steps[0]
                    frame.gap_analysis = (
                        f"推理方向在关键步骤缺少足够验证。"
                        f"第{worst.step}步推理置信度{worst.confidence_at_step:.0%}但未考虑替代可能。"
                        f"当前方向：{worst.chosen_direction}。"
                    )
                else:
                    # 常规差距：用答案对比
                    frame.gap_analysis = self._infer_gap_from_answers(
                        frame.original_query, frame.wrong_answer, frame.correct_answer
                    )

        elif frame.correct_answer:
            frame.gap_analysis = self._infer_gap_from_answers(
                frame.original_query, frame.wrong_answer, frame.correct_answer
            )
        else:
            frame.gap_analysis = f"输出（{frame.wrong_answer[:40]}...）被判定为错误，但未提供正确答案。"

        # ── 2b. 归类 root_cause ──
        frame.root_cause = self._classify_root_cause(
            frame.original_query, frame.wrong_answer,
            frame.correct_answer, trace
        )

        # ── 2c. 生成修正策略 ──
        frame.fix_strategy = self._generate_fix_strategy(
            frame.root_cause, frame.gap_analysis,
            frame.trigger_keywords
        )

        # ── 2d. 自动确定分类 ──
        detected_category, detected_subcategory = self._categorize_error(
            frame.root_cause, frame.trigger_keywords
        )
        frame.category = detected_category
        frame.subcategory = detected_subcategory

        logger.debug(f"分析错误帧: {frame.frame_id[:8]} | root_cause={frame.root_cause}")
        return frame

    def store(self, frame: ErrorReflectionFrame) -> str:
        """
        第3步：存储错误帧到长期记忆

        写入 L3 语义记忆，附带 error_calibration 标签，
        同时注册到触发索引。

        返回：
            记忆条目的 ID
        """
        frame_id = ""

        # 序列化错误帧到 metadata
        frame_dict = frame.to_dict()
        frame_json = json.dumps(frame_dict, ensure_ascii=False)

        # 构建记忆内容（人类可读 + 机器可读）
        memory_content = (
            f"[错误校准] {frame.original_query[:60]}\n"
            f"错误输出: {frame.wrong_answer[:100]}\n"
            f"正确输出: {frame.correct_answer[:100]}\n"
            f"差距分析: {frame.gap_analysis[:200]}\n"
            f"根因: {frame.root_cause} | 修正: {frame.fix_strategy[:100]}"
        )

        # 存储到 long_term_memory
        if self.ltm:
            entry = MemoryEntry(
                content=memory_content,
                title=f"错误校准: {frame.original_query[:40]}",
                memory_type=MemoryType.SEMANTIC,
                tags=frame.tags + frame.trigger_keywords[:5],
                importance=0.5 + frame.calibration_weight * 0.3,
                confidence=frame.fix_confidence,
                metadata={
                    "error_frame": frame_dict,
                    "is_calibration": True,
                    "root_cause": frame.root_cause,
                }
            )
            # 生成嵌入向量以便语义检索
            entry.embedding = self.ltm._generate_embedding(memory_content)
            frame_id = self.ltm.store(entry)
            logger.debug(f"存储校准记忆: {frame_id[:8]}")

        # 注册到触发索引（无论 ltm 是否可用都注册内存索引）
        self.trigger_index.register(frame)
        self._frame_history.append(frame)

        return frame_id

    def calibrate(self, query: str, top_k: int = 3) -> List[CalibrationSignal]:
        """
        第4步：对新查询检索相关校准信号

        对于匹配到的错误帧，生成 CalibrationSignal
        供推理引擎在生成答案时参考。

        参数：
            query:  当前查询
            top_k:  最大返回数量

        返回：
            校准信号列表，按有效权重降序
        """
        matched = self.trigger_index.query(query, top_k=top_k)
        if not matched:
            return []

        signals: List[CalibrationSignal] = []
        for frame, match_score in matched:
            signal = CalibrationSignal(frame, match_score)
            signals.append(signal)

            # 更新生效计数
            frame.effective_count += 1
            frame.last_effective_at = time.time()

        # 按有效权重排序
        signals.sort(key=lambda s: s.effective_weight, reverse=True)

        if signals:
            logger.debug(
                f"检索到 {len(signals)} 条校准信号 | "
                f"最强: {signals[0].frame.root_cause} "
                f"(weight={signals[0].effective_weight:.2f})"
            )

        return signals

    # ── 便捷入口 ──────────────────────────────────────────────────

    def process_error(self, *,
                      query: str,
                      wrong_answer: str,
                      correct_answer: str,
                      confidence: float = 0.5,
                      reasoning_trace: Optional[List[ReasoningTraceNode]] = None,
                      source: str = "self_check",
                      ) -> Tuple[ErrorReflectionFrame, str]:
        """
        完整错误处理流程：capture → analyze → store

        参数：
            query:          原始查询
            wrong_answer:   实际输出的错误答案
            correct_answer: 正确答案
            confidence:     输出时的置信度
            reasoning_trace:推理轨迹快照
            source:         错误来源

        返回：
            (ErrorReflectionFrame, memory_id)
        """
        frame = self.capture(
            query=query,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            confidence=confidence,
            reasoning_trace=reasoning_trace,
            source=source,
        )
        frame = self.analyze(frame)
        memory_id = self.store(frame)
        return frame, memory_id

    def submit_feedback(self, *,
                        query: str,
                        wrong_output: str,
                        correct_output: str,
                        source: str = "user_feedback",
                        ) -> str:
        """
        外部调用入口：提交错误反馈

        由用户或外部评价系统调用。
        返回校准记忆的存储 ID。
        """
        frame, memory_id = self.process_error(
            query=query,
            wrong_answer=wrong_output,
            correct_answer=correct_output,
            confidence=0.0,  # 外部反馈，置信度设为0等待分析
            source=source,
        )
        logger.info(f"收到外部错误反馈: {frame.frame_id[:8]} | {query[:50]}")
        return memory_id

    # ── 防幻觉管线 facade ──────────────────────────────────────

    def reflect(self, error_record: Dict[str, Any]) -> Dict[str, Any]:
        """防幻觉管线 facade — 接收结构化 error_record 触发反思并返回结果。

        本方法是为防幻觉管线提供的对外稳定接口：上游（如 truth_grounding
        的三态判定）只需构造一个 ``error_record`` dict 即可触发完整的
        capture → analyze → store 流程，无需了解 ReasoningTraceNode 等
        内部类型。

        Args:
            error_record: 结构化错误记录，期望字段：
                * ``query`` (str, 必填) — 触发错误的原始查询/论断；
                * ``wrong_answer`` (str, 必填) — 实际的错误输出；
                * ``correct_answer`` (str, 可选) — 正确答案，未知时可留空；
                * ``confidence`` (float, 可选, 默认 0.5) — 输出时置信度；
                * ``source`` (str, 可选, 默认 ``"truth_grounding"``) —
                  错误来源标签；
                * ``reasoning_trace`` (List[dict], 可选) — 推理轨迹节点
                  dict 列表，每项含 step/description/reasoning/alternatives
                  /chosen_direction/confidence_at_step/was_correct_branch。

        Returns:
            ``{"frame_id": str, "memory_id": str, "root_cause": str,
            "gap_analysis": str, "fix_strategy": str, "calibration_weight":
            float}``。当 ``error_record`` 缺失必填字段时，返回
            ``{"error": str, "frame_id": "", "memory_id": ""}`` 而非抛异常，
            以保证管线非阻塞。
        """
        query = error_record.get("query") or ""
        wrong_answer = error_record.get("wrong_answer") or ""
        correct_answer = error_record.get("correct_answer") or ""
        if not query or not wrong_answer:
            return {
                "error": "error_record 缺少必填字段 query/wrong_answer",
                "frame_id": "",
                "memory_id": "",
            }

        confidence = float(error_record.get("confidence", 0.5))
        source = str(error_record.get("source", "truth_grounding"))

        # 把 dict 形式的 reasoning_trace 转回 ReasoningTraceNode
        raw_trace = error_record.get("reasoning_trace") or []
        reasoning_trace: List[ReasoningTraceNode] = []
        for node in raw_trace:
            if isinstance(node, ReasoningTraceNode):
                reasoning_trace.append(node)
                continue
            if not isinstance(node, dict):
                continue
            reasoning_trace.append(ReasoningTraceNode(
                step=int(node.get("step", 0)),
                description=str(node.get("description", "")),
                reasoning=str(node.get("reasoning", "")),
                alternatives=list(node.get("alternatives", []) or []),
                chosen_direction=str(node.get("chosen_direction", "")),
                confidence_at_step=float(node.get("confidence_at_step", 0.5)),
                was_correct_branch=node.get("was_correct_branch"),
            ))

        frame, memory_id = self.process_error(
            query=query,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            confidence=confidence,
            reasoning_trace=reasoning_trace or None,
            source=source,
        )

        return {
            "frame_id": frame.frame_id,
            "memory_id": memory_id,
            "root_cause": frame.root_cause,
            "gap_analysis": frame.gap_analysis,
            "fix_strategy": frame.fix_strategy,
            "calibration_weight": float(frame.calibration_weight),
        }

    # ── 内部辅助方法 ──────────────────────────────────────────────

    def _extract_trigger_keywords(self, query: str, wrong: str, correct: str) -> List[str]:
        """
        从查询、错误答案、正确答案中提取触发关键词

        使用与 TriggerIndex._tokenize 一致的分词策略，
        确保存储的关键词和查询时匹配的关键词在同一个向量空间中。
        """
        keywords = set()

        # 使用统一的 tokenize 方法
        for token in self.trigger_index._tokenize(query):
            keywords.add(token)
        for token in self.trigger_index._tokenize(wrong):
            keywords.add(token)
        for token in self.trigger_index._tokenize(correct):
            keywords.add(token)

        return list(keywords)[:20]

    def _infer_gap_from_answers(self, query: str, wrong: str, correct: str) -> str:
        """
        通过错误答案与正确答案对比推断差距
        """
        if not wrong or not correct:
            return "未提供正确答案，无法分析差距。"

        # 检查长度差异
        len_diff = abs(len(wrong) - len(correct))

        # 检查错误答案是否在某些关键概念上错了
        import re
        query_terms = re.findall(r'[\u4e00-\u9fff]{2,}', query.lower())

        gap_parts = []

        if len_diff > 100:
            gap_parts.append(f"答案长度差异较大（差{len_diff}字符），可能遗漏了完整分析。")

        # 检查正确答案中包含了查询中的哪些词
        missed_terms = []
        for term in query_terms:
            if term not in correct and term not in wrong:
                continue
            if term in correct and term not in wrong:
                missed_terms.append(term)

        if missed_terms:
            gap_parts.append(
                f"未涉及关键概念：{'、'.join(missed_terms[:5])}。"
                f"正确答案中包含了这些概念，错误答案中没有充分考虑。"
            )

        if not gap_parts:
            gap_parts.append(
                f"错误答案「{wrong[:60]}」与正确答案「{correct[:60]}」存在偏差，"
                f"需要分析推理路径中的断点。"
            )

        return " ".join(gap_parts)

    def _classify_root_cause(self, query: str, wrong: str,
                              correct: str,
                              trace: List[ReasoningTraceNode]) -> str:
        """
        根据推理轨迹和答案对比分类根因

        启发式优先级：
        1. 从推理轨迹中的显式标记判断
        2. 从轨迹中高置信度错误分支推断
        3. 从答案对比（内容差异、缺失概念、数值错误）推断
        """
        import re

        # ── Phase 1: 从推理轨迹推断 ──
        if trace:
            # 明确标记为错误分支且高置信度 -> 过度自信
            overconfident_steps = [
                n for n in trace if n.confidence_at_step > 0.85
                and n.was_correct_branch is False
            ]
            if overconfident_steps:
                return "overconfidence"

            # 未标记但高置信且无替代方案 -> 推测过度自信或过早闭合
            for n in trace:
                if n.confidence_at_step > 0.85 and not n.alternatives:
                    # 单个高置信步骤且无替代方案，很可能是过早闭合
                    if len(trace) <= 2:
                        return "premature_closure"
                    return "overconfidence"

            # 没有替代方案 -> 过早闭合的线索
            no_alt_count = sum(1 for n in trace if not n.alternatives)
            if no_alt_count >= len(trace) // 2:
                return "premature_closure"

        # ── Phase 2: 从答案对比推断 ──
        if wrong and correct:
            # 数值错误
            wrong_nums = set(re.findall(r'\d+\.?\d*', wrong))
            correct_nums = set(re.findall(r'\d+\.?\d*', correct))
            if wrong_nums and correct_nums and wrong_nums != correct_nums:
                return "numerical_error"

            # 正确答案比错误答案长很多 -> 可能遗漏了上下文
            if len(correct) > len(wrong) * 1.5 and len(wrong) > 10:
                return "missing_context"

            # 错误答案中缺失正确答案中的关键概念
            query_terms = re.findall(r'[\u4e00-\u9fff]{2,}', query.lower())
            missing_terms = [
                t for t in query_terms
                if t in correct and t not in wrong
            ]
            if len(missing_terms) >= 2:
                return "missing_context"

            # 错误答案在简化/压缩正确答案（范畴错误或过早闭合）
            if len(wrong) < len(correct) * 0.3:
                return "premature_closure"

        # ── Phase 3: 从查询类型推断 ──
        query_lower = query.lower()
        # 请求比较或辨析类问题
        compare_words = ["区别", "对比", "比较", "vs", "diff", "difference", "versus"]
        if any(cw in query_lower for cw in compare_words):
            # 如果是比较类问题，错误答案往往遗漏了关键对比维度
            if correct and len(correct.split()) > 3:
                return "missing_context"

        return "unknown"

    def _generate_fix_strategy(self, root_cause: str,
                                gap_analysis: str,
                                keywords: List[str]) -> str:
        """
        根据根因和差距分析生成修正策略
        """
        strategies = {
            "overconfidence":
                "在给出结论前先检查证据充分性。列出支撑结论的理由清单，"
                "确认每条理由都有直接依据。如果理由少于3条，降低置信度并增加验证步骤。",
            "missing_context":
                "在推理开始时先列出所有相关的上下文信息。"
                "识别问题中隐含的背景假设，逐一验证其有效性。",
            "wrong_assumption":
                "明确列出推理依赖的所有前提假设。"
                "对每条假设问：'如果这条不成立会怎样？'",
            "factual_error":
                "对涉及具体事实、数据、引用的断言进行双重验证。"
                "优先使用可靠来源交叉校验事实性断言。",
            "logical_fallacy":
                "检查推理链中的每一步是否有明确的因果或逻辑连接。"
                "标记出跳跃性的结论，补充中间推理步骤。",
            "confirmation_bias":
                "主动搜索与当前结论相反的证据。"
                "在给出最终答案前，列出至少一个替代解释。",
            "premature_closure":
                "在给出结论前列出所有可能的替代方案。"
                "确保已探索至少2-3个不同方向后再做选择。",
            "numerical_error":
                "涉及数字计算时，先核对数值单位、范围和精度。"
                "执行逆向验证：用结果反推输入，检查是否一致。",
            "unknown":
                "回顾推理过程，标记出所有置信度低于0.7的分支。"
                "对每个低置信度分支补充更多信息后再做结论。",
        }

        strategy = strategies.get(root_cause, strategies["unknown"])

        # 如果有关键词，在策略中融入
        if keywords and root_cause == "unknown":
            top_kws = keywords[:3]
            strategy += f" 特别关注涉及「{'、'.join(top_kws)}」的推理步骤。"

        return strategy

    def _categorize_error(self, root_cause: str,
                          keywords: List[str]) -> Tuple[str, str]:
        """
        对错误进行分类
        """
        category_map = {
            "overconfidence": ("reasoning", "precision"),
            "missing_context": ("reasoning", "completeness"),
            "wrong_assumption": ("reasoning", "validity"),
            "factual_error": ("knowledge", "factuality"),
            "logical_fallacy": ("reasoning", "logic"),
            "confirmation_bias": ("reasoning", "bias"),
            "premature_closure": ("reasoning", "exploration"),
            "causal_misattribution": ("reasoning", "causality"),
            "analogy_drift": ("reasoning", "analogy"),
            "ambiguity_mishandled": ("reasoning", "clarity"),
            "numerical_error": ("knowledge", "numerical"),
            "temporal_error": ("knowledge", "temporal"),
            "level_confusion": ("reasoning", "abstraction"),
            "category_error": ("knowledge", "categorization"),
            "anchoring": ("reasoning", "bias"),
        }

        return category_map.get(root_cause, ("general", "unknown"))

    # ── 诊断与报告 ────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """
        返回管道当前状态摘要
        """
        frames = self._frame_history
        if not frames:
            return {
                "total_frames": 0,
                "status": "no_data",
            }

        # 按根因统计
        cause_counts: Dict[str, int] = {}
        # 按分类统计
        cat_counts: Dict[str, int] = {}
        total_effective = 0

        for f in frames:
            cause_counts[f.root_cause] = cause_counts.get(f.root_cause, 0) + 1
            cat_key = f"{f.category}/{f.subcategory}"
            cat_counts[cat_key] = cat_counts.get(cat_key, 0) + 1
            total_effective += f.effective_count

        return {
            "total_frames": len(frames),
            "total_effective_triggers": total_effective,
            "root_cause_distribution": dict(
                sorted(cause_counts.items(), key=lambda x: x[1], reverse=True)
            ),
            "category_distribution": dict(
                sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
            ),
            "avg_calibration_weight": round(
                sum(f.calibration_weight for f in frames) / len(frames), 2
            ),
            "trigger_index_size": self.trigger_index.count(),
            "status": "active",
        }


# ──────────────────────────────────────────────────────────────────────
# 5. 工厂函数：集成到 IntegratedCognitiveEngine
# ──────────────────────────────────────────────────────────────────────

def create_error_reflection_pipeline(
    long_term_memory: Optional[LongTermMemory] = None,
    auto_restore: bool = True,
) -> ErrorReflectionPipeline:
    """
    创建并初始化错误反思管道

    参数：
        long_term_memory: 长期记忆引擎实例
        auto_restore:     是否自动从记忆库恢复已有校准帧

    返回：
        已初始化的 ErrorReflectionPipeline
    """
    pipeline = ErrorReflectionPipeline(long_term_memory=long_term_memory)

    if auto_restore and long_term_memory:
        restored = pipeline.restore_from_memory()
        logger.info(f"错误反思管道初始化完成，已恢复 {restored} 条校准帧")
    else:
        logger.info("错误反思管道初始化完成（空索引）")

    return pipeline
