"""
LAAP — First Principles Engine (第一性原理引擎)

最高层级的推理：将问题分解到不可再分的基本真理，
然后从零开始重建解决方案。类比物理学的"还原到最底层定律"。

核心思想（Aristotle / Musk / Feynman）：
  1. 识别并挑战所有假设
  2. 将问题分解到最基本单元
  3. 从基本真理向上重建
  4. 用逻辑和证据验证每个步骤
  5. 质疑类比和"大家都这么做"

与元认知的关系：
  - 元认知监控"如何思考"
  - 第一性原理决定"思考的根基"
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, math, re

logger = logging.getLogger("laap.cognition.first_principles")


class DecompositionStyle(Enum):
    """分解风格"""
    FEYNMAN = "feynman"             # 费曼：用最简单的语言解释
    SOCRATIC = "socratic"           # 苏格拉底：提问式分解
    REDUCTIONIST = "reductionist"   # 还原论：拆到不可分单元
    INDUCTIVE = "inductive"         # 归纳法：从具体到一般
    DEDUCTIVE = "deductive"         # 演绎法：从一般到具体


@dataclass
class FirstPrinciple:
    """
    第一性原理 — 一个不可再分的基本真理
    
    必须满足：
    - 不可再简化 (cannot be simplified further)
    - 自明或可独立验证 (self-evident or independently verifiable)
    - 不依赖领域特定假设 (domain-independent)
    """
    statement: str = ""                  # 陈述
    evidence: str = ""                   # 证据或推理依据
    domain: str = ""                     # 所属领域
    certainty: float = 0.9               # 确信度
    is_fundamental: bool = True         # 是否真的是第一性原理
    source: str = ""                     # 来源（物理/数学/逻辑/经验）
    counterexamples: List[str] = field(default_factory=list)  # 反例

    def to_dict(self) -> dict:
        return {
            "statement": self.statement[:80],
            "domain": self.domain,
            "certainty": round(self.certainty, 2),
            "is_fundamental": self.is_fundamental,
        }


@dataclass
class DecompositionNode:
    """
    问题分解节点 — 树形结构
    
    根：原问题
    子节点：子问题或基本单元
    叶子：第一性原理
    """
    id: str = ""
    question: str = ""                   # 当前层的问题
    answer: str = ""                     # 答案（如果有）
    assumptions: List[str] = field(default_factory=list)   # 识别出的假设
    is_principle: bool = False           # 是否已达到第一性原理
    principle: Optional[FirstPrinciple] = None  # 如果已是原理
    children: List[DecompositionNode] = field(default_factory=list)
    depth: int = 0
    confidence: float = 0.5
    
    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "question": self.question[:60],
            "assumptions": self.assumptions[:3],
            "is_principle": self.is_principle,
            "children_count": len(self.children),
            "depth": self.depth,
        }


@dataclass
class ReconstructionPlan:
    """
    重建计划 — 从第一性原理向上构建解决方案
    
    每个步骤都基于前面的真理，用逻辑连接。
    """
    steps: List[Dict[str, Any]] = field(default_factory=list)
    final_solution: str = ""
    logical_gaps: List[str] = field(default_factory=list)  # 逻辑跳跃
    confidence: float = 0.0
    alternative_paths: List[str] = field(default_factory=list)


class FirstPrinciplesEngine:
    """
    第一性原理推理引擎
    
    核心流程：
    1. ASSUMPTION_CHALLENGE: 识别并挑战所有隐含假设
    2. DECOMPOSITION: 将问题分解到基本真理
    3. RECONSTRUCTION: 从原理向上重建
    4. VERIFICATION: 验证重建的逻辑完备性
    
    这不仅是问题解决方法论，更是 Agent 的"元认知地基"：
    当常规模式匹配失败时，回退到第一性原理重新思考。
    """

    def __init__(self):
        # 知识库：已知的第一性原理
        self.principles: Dict[str, List[FirstPrinciple]] = {
            "physics": [],
            "logic": [],
            "mathematics": [],
            "cognition": [],
            "computation": [],
        }
        self._init_fundamental_principles()
        
        # 分解树缓存
        self._decomposition_cache: Dict[str, DecompositionNode] = {}
        
        # 统计
        self._total_decompositions = 0
        self._assumptions_challenged = 0
        self._reconstructions = 0

    def _init_fundamental_principles(self):
        """初始化一些基本的第一性原理"""
        self.principles["logic"] = [
            FirstPrinciple(
                statement="A = A (同一律: 一个事物就是它自身)",
                evidence="逻辑自明，所有理性思维的基础",
                domain="logic",
                certainty=1.0,
                source="亚里士多德",
            ),
            FirstPrinciple(
                statement="排中律: 一个命题要么为真要么为假",
                evidence="二元逻辑的基本公理",
                domain="logic",
                certainty=1.0,
                source="古典逻辑",
            ),
        ]
        
        self.principles["computation"] = [
            FirstPrinciple(
                statement="图灵完备: 任何可计算问题都可以用有限指令集解决",
                evidence="图灵机理论",
                domain="computation",
                certainty=0.99,
                source="Alan Turing",
            ),
            FirstPrinciple(
                statement="信息守恒: 信息不会凭空产生或消失",
                evidence="Landauer's principle, 热力学第二定律",
                domain="computation",
                certainty=0.99,
                source="Rolf Landauer",
            ),
        ]
        
        self.principles["cognition"] = [
            FirstPrinciple(
                statement="感知驱动: 智能体行为由感知-行动循环驱动",
                evidence="感知-行动循环是一切智能系统的基础",
                domain="cognition",
                certainty=0.95,
                source="认知科学",
            ),
            FirstPrinciple(
                statement="层级抽象: 复杂认知依赖于层级化的概念抽象",
                evidence="大脑新皮质的分层结构",
                domain="cognition",
                certainty=0.95,
                source="Jeff Hawkins, Numenta",
            ),
        ]

    def challenge_assumptions(self, problem: str) -> Dict[str, Any]:
        """
        步骤1: 识别并挑战所有隐含假设
        
        Args:
            problem: 要分析的问题描述
        
        Returns:
            {
                "assumptions": 识别出的假设列表,
                "challenged": 被成功挑战的假设,
                "surviving": 经受住挑战的假设,
                "socratic_questions": 苏格拉底式追问
            }
        """
        self._assumptions_challenged += 1
        
        # 启发式识别常见隐含假设
        assumptions = self._identify_assumptions(problem)
        
        # 苏格拉底追问
        questions = self._generate_socratic_questions(assumptions, problem)
        
        # 挑战结果
        challenged = []
        surviving = []
        for a in assumptions:
            if self._is_challengeable(a):
                challenged.append(a)
            else:
                surviving.append(a)
        
        result = {
            "assumptions": assumptions,
            "challenged": challenged,
            "surviving": surviving,
            "socratic_questions": questions,
            "assumption_free_core": self._extract_core_without_assumptions(problem, assumptions),
        }
        
        logger.info(
            f"[FirstPrinciples] Assumptions: {len(assumptions)} found, "
            f"{len(challenged)} challenged, {len(surviving)} survived"
        )
        return result

    def decompose(self, problem: str, 
                  max_depth: int = 5,
                  style: DecompositionStyle = DecompositionStyle.SOCRATIC) -> DecompositionNode:
        """
        步骤2: 将问题分解到第一性原理
        
        递归地将问题拆解，直到每个子问题都可以
        追溯到基本真理。
        
        Args:
            problem: 要分解的问题
            max_depth: 最大分解深度
            style: 分解风格
        
        Returns:
            分解树根节点
        """
        self._total_decompositions += 1
        root = DecompositionNode(
            id=f"fp_{self._total_decompositions}",
            question=problem,
            depth=0,
        )
        
        # 递归分解
        self._decompose_recursive(root, max_depth, style)
        
        # 缓存
        self._decomposition_cache[root.id] = root
        
        return root

    def reconstruct(self, decomposition: DecompositionNode,
                    original_problem: str) -> ReconstructionPlan:
        """
        步骤3: 从第一性原理向上重建解决方案
        
        从叶子节点(第一性原理)开始，逐层向上构建，
        每一步都确保逻辑连贯。
        
        Args:
            decomposition: 分解树的根节点
            original_problem: 原始问题
        
        Returns:
            重建计划
        """
        self._reconstructions += 1
        
        # 收集所有叶子原理
        principles = []
        self._collect_principles(decomposition, principles)
        
        if not principles:
            return ReconstructionPlan(
                confidence=0.0,
                logical_gaps=["未找到可用的第一性原理"],
            )
        
        # 构建重建步骤
        steps = self._build_reconstruction_steps(principles, original_problem)
        
        # 检测逻辑跳跃
        gaps = self._detect_logical_gaps(steps)
        
        # 替代路径
        alternatives = self._find_alternatives(steps)
        
        return ReconstructionPlan(
            steps=steps,
            logical_gaps=gaps,
            confidence=0.8 - 0.1 * len(gaps),
            alternative_paths=alternatives,
        )

    def analyze(self, problem: str, 
                full_analysis: bool = True) -> Dict[str, Any]:
        """
        完整的第一性原理分析：挑战假设→分解→重建
        
        Args:
            problem: 要分析的问题
            full_analysis: 是否执行完整三步骤
        
        Returns:
            完整的分析报告
        """
        t0 = time.time()
        
        # 1. 挑战假设
        assumption_result = self.challenge_assumptions(problem)
        
        # 2. 分解
        decomposition = self.decompose(problem)
        
        # 3. 重建（可选）
        reconstruction = None
        if full_analysis:
            reconstruction = self.reconstruct(decomposition, problem)
        
        # 收集统计
        principle_count = 0
        max_depth = 0
        
        def count(node):
            nonlocal principle_count, max_depth
            if node.is_principle:
                principle_count += 1
            max_depth = max(max_depth, node.depth)
            for c in node.children:
                count(c)
        count(decomposition)
        
        result = {
            "problem": problem[:60],
            "assumptions_challenged": len(assumption_result["assumptions"]),
            "decomposition_depth": max_depth,
            "principles_found": principle_count,
            "has_logical_gaps": len(reconstruction.logical_gaps) > 0 if reconstruction else None,
            "confidence": reconstruction.confidence if reconstruction else None,
            "duration_ms": round((time.time() - t0) * 1000, 1),
            "summary": self._generate_analysis_summary(
                assumption_result, decomposition, reconstruction
            ),
        }
        
        logger.info(
            f"[FirstPrinciples] Analysis: {result['assumptions_challenged']} assumptions "
            f"challenged, {result['principles_found']} principles, "
            f"depth={result['decomposition_depth']}, {result['duration_ms']}ms"
        )
        return result

    def get_first_principles_prompt_block(self) -> str:
        """生成第一性原理提示块 — 注入 System Prompt"""
        physics = self.principles.get("physics", [])
        logic = self.principles.get("logic", [])
        comp = self.principles.get("computation", [])
        
        parts = ["[第一性原理思维]", ""]
        parts.append("当面对复杂问题时，采用以下方法：")
        parts.append("1. 识别并挑战所有隐含假设")
        parts.append("2. 将问题分解到不可再分的基本真理")
        parts.append("3. 从基本真理向上重建解决方案")
        parts.append("4. 验证每一步的逻辑完备性")
        parts.append("")
        parts.append("不要依赖类比或'大家都这么做'的论证。")
        parts.append("每次遇到瓶颈，回到第一性原理重新思考。")
        
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════

    def _identify_assumptions(self, problem: str) -> List[str]:
        """识别问题中的隐含假设"""
        assumptions = []
        text = problem.lower()
        
        # 启发式模式
        patterns = [
            (r"应该[是都要]", "隐含价值判断"),
            (r"通常|一般|往往", "隐含统计概括"),
            (r"大家|所有人|总是", "隐含全称量化"),
            (r"不能|不可能|无法", "隐含能力限制"),
            (r"因为.*所以|由于.*因此", "隐含因果关系"),
            (r"最好|最有效|最优", "隐含优化目标"),
            (r"传统|标准|常规", "隐含路径依赖"),
            (r"必须|一定|务必", "隐含必要性假设"),
            (r"简单|容易|复杂|困难", "隐含复杂度判断"),
            (r"已经|早就|早已", "隐含时间假设"),
        ]
        
        for pattern, label in patterns:
            if re.search(pattern, text):
                assumptions.append(f"{label}: 问题陈述中包含'{pattern.replace(chr(92), '')}'")
        
        # 长度假设
        if len(problem) > 200:
            assumptions.append("信息过载: 问题描述过长，可能包含不必要的约束")
        
        # 默认假设
        assumptions.append("认知视角: 当前理解受限于已有知识框架")
        
        return list(set(assumptions))

    def _generate_socratic_questions(self, assumptions: List[str],
                                      problem: str) -> List[str]:
        """生成苏格拉底式追问"""
        questions = [
            "这个问题的本质是什么? (剥离所有上下文)",
            "我们怎么知道这是真的? (证据来源)",
            "有没有反例? (证伪测试)",
            "如果不这么做会怎样? (反向思考)",
            "最基础的形式是什么? (还原到基本单元)",
        ]
        
        if assumptions:
            questions.insert(0, f"如果'{assumptions[0][:30]}'不成立会怎样?")
        
        return questions

    def _is_challengeable(self, assumption: str) -> bool:
        """判断一个假设是否可被挑战"""
        non_challengeable = ["认知视角"]  # 元认知假设不可挑战
        return not any(n in assumption for n in non_challengeable)

    def _extract_core_without_assumptions(self, problem: str,
                                           assumptions: List[str]) -> str:
        """移除假设后提取问题核心"""
        core = problem
        # 简单的假设移除启发式
        remove_patterns = [
            r"最好是[^，。]*", r"通常[^，。]*",
            r"一般来说[^，。]*", r"大家都[^，。]*",
        ]
        for pattern in remove_patterns:
            core = re.sub(pattern, "", core)
        return core.strip()[:100]

    def _decompose_recursive(self, node: DecompositionNode,
                              max_depth: int,
                              style: DecompositionStyle):
        """递归分解到第一性原理"""
        if node.depth >= max_depth:
            node.answer = "达到最大分解深度"
            return
        
        question = node.question
        
        # 检查是否已经是第一性原理
        principle = self._match_principle(question)
        if principle:
            node.is_principle = True
            node.principle = principle
            node.answer = principle.statement
            return
        
        # 根据风格生成子问题
        sub_questions = self._generate_sub_questions(question, style)
        
        if not sub_questions:
            # 不能再分解 → 创建近似原理
            node.assumptions.append(f"假设: {question[:40]} 不能再分解")
            return
        
        for sq in sub_questions[:3]:  # 限制分支
            child = DecompositionNode(
                id=f"{node.id}_{len(node.children)}",
                question=sq,
                depth=node.depth + 1,
            )
            self._decompose_recursive(child, max_depth, style)
            node.children.append(child)

    def _match_principle(self, question: str) -> Optional[FirstPrinciple]:
        """检查问题是否匹配已有第一性原理"""
        question_lower = question.lower()
        for domain, principles in self.principles.items():
            for p in principles:
                keywords = re.findall(r'\w+', p.statement.lower())[:5]
                if any(k in question_lower for k in keywords):
                    return p
        return None

    def _generate_sub_questions(self, question: str,
                                 style: DecompositionStyle) -> List[str]:
        """根据分解风格生成子问题"""
        if style == DecompositionStyle.SOCRATIC:
            return [
                f"为了回答'{question[:30]}', 需要先理解什么?",
                f"'{question[:30]}'的基本单元是什么?",
                f"什么因素决定了'{question[:30]}'?",
            ]
        elif style == DecompositionStyle.FEYNMAN:
            return [
                f"用最简单的语言解释: {question[:40]}",
                f"这个现象背后的物理/逻辑过程是什么?",
            ]
        elif style == DecompositionStyle.REDUCTIONIST:
            return [
                f"'{question[:30]}'可以拆解为哪些独立部分?",
                f"每个部分的最简形式是什么?",
            ]
        else:
            return [
                f"'{question[:30]}'的前提是什么?",
                f"'{question[:30]}'的结果是什么?",
            ]

    def _collect_principles(self, node: DecompositionNode,
                             principles: List[FirstPrinciple]):
        """递归收集所有叶子第一性原理"""
        if node.is_principle and node.principle:
            principles.append(node.principle)
        for child in node.children:
            self._collect_principles(child, principles)

    def _build_reconstruction_steps(self, principles: List[FirstPrinciple],
                                     original: str) -> List[Dict[str, Any]]:
        """从原理向上构建解决方案步骤"""
        steps = []
        for i, p in enumerate(principles):
            steps.append({
                "step": i + 1,
                "principle": p.statement[:60],
                "certainty": p.certainty,
                "implication": f"基于{p.statement[:40]}的推论",
            })
        
        steps.append({
            "step": len(steps) + 1,
            "principle": "综合",
            "certainty": 0.7,
            "implication": f"将{len(principles)}个第一性原理综合应用于: {original[:50]}",
        })
        
        return steps

    def _detect_logical_gaps(self, steps: List[Dict[str, Any]]) -> List[str]:
        """检测重建过程中的逻辑跳跃"""
        gaps = []
        for i in range(1, len(steps)):
            step_a = steps[i - 1]
            step_b = steps[i]
            if step_b["certainty"] < step_a["certainty"] * 0.7:
                gaps.append(
                    f"逻辑跳跃: 步骤{step_a['step']}(确信度{step_a['certainty']:.2f}) "
                    f"→ 步骤{step_b['step']}(确信度{step_b['certainty']:.2f})"
                )
        return gaps

    def _find_alternatives(self, steps: List[Dict[str, Any]]) -> List[str]:
        """寻找替代路径"""
        return [f"替代路径: 从不同的基本原理出发重新构建"]

    def _generate_analysis_summary(self, assumptions: Dict,
                                    decomposition: DecompositionNode,
                                    reconstruction: Optional[ReconstructionPlan]) -> str:
        """生成分析摘要"""
        parts = ["第一性原理分析摘要:"]
        parts.append(f"  - 挑战了 {len(assumptions['assumptions'])} 个隐含假设")
        parts.append(f"  - 分解深度: {self._max_depth(decomposition)} 层")
        parts.append(f"  - 找到 {self._count_principles(decomposition)} 个第一性原理")
        if reconstruction:
            parts.append(f"  - 重建确信度: {reconstruction.confidence:.0%}")
            if reconstruction.logical_gaps:
                parts.append(f"  - 逻辑跳跃: {len(reconstruction.logical_gaps)} 处")
        return "\n".join(parts)

    def _max_depth(self, node: DecompositionNode) -> int:
        if not node.children:
            return node.depth
        return max(self._max_depth(c) for c in node.children)

    def _count_principles(self, node: DecompositionNode) -> int:
        count = 1 if node.is_principle else 0
        for c in node.children:
            count += self._count_principles(c)
        return count

    def introspect(self) -> str:
        """内省：返回引擎状态"""
        total_ps = sum(len(v) for v in self.principles.values())
        return (
            "=== 第一性原理引擎 ==="
            f"\n知识库: {total_ps} 条原理 ({len(self.principles)} 个领域)"
            f"\n总分解: {self._total_decompositions}"
            f"\n假设挑战: {self._assumptions_challenged}"
            f"\n总重建: {self._reconstructions}"
        )

    def status(self) -> dict:
        return {
            "principles": sum(len(v) for v in self.principles.values()),
            "domains": list(self.principles.keys()),
            "decompositions": self._total_decompositions,
            "assumptions_challenged": self._assumptions_challenged,
            "reconstructions": self._reconstructions,
        }
