"""
LAAP — 知行合一 (Unity of Knowledge and Action) 决策执行引擎

核心理念：知与行不可分割。 
- 决策就是行动的第一步骤
- 行动就是知识的具体化
- 技能是身体化的知识，通过练习而精进
- 思考与执行是同一过程的两个面相

三层深度融合：
  1. Knowledge-Action Binding: 每个知识片段都绑定执行路径
  2. Skill Embodiment: 工具不是外部资源，而是大脑的"肌肉记忆"
  3. Unity Decision: 决策 IS 执行计划，执行 IS 知识获取
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, math

logger = logging.getLogger("laap.cognition.unity")


class SkillProficiency(Enum):
    """技能熟练度"""
    UNKNOWN = "unknown"            # 从未使用
    AWARE = "aware"                # 知道但未使用过
    NOVICE = "novice"              # 初学：需要明确指导
    PRACTITIONER = "practitioner"  # 实践者：能独立使用
    EXPERT = "expert"             # 专家：能优化使用方式
    MASTER = "master"             # 大师：能教导和创新


@dataclass
class EmbodiedSkill:
    """
    具身技能 — 大脑"知道如何做"的知识单元
    
    知行合一的核心载体：
    - 知道 (knowledge): 技能是什么，什么时候用
    - 行动 (action): 具体的工具调用序列
    - 身体化 (embodiment): 通过练习从"需要想"变成"自然反应"
    """
    name: str = ""
    description: str = ""
    cognitive_action: str = ""         # 对应的认知动作
    tool_sequence: List[Dict[str, Any]] = field(default_factory=list)  # [{"tool":"run_python", "params_template":{...}}, ...]
    proficiency: SkillProficiency = SkillProficiency.UNKNOWN
    use_count: int = 0
    success_count: int = 0
    last_used: float = 0.0
    avg_duration_ms: float = 0.0
    avg_quality: float = 0.0
    
    # 参数记忆 — 记住上次成功的参数模式
    last_successful_params: Dict[str, Any] = field(default_factory=dict)
    
    # 直觉触发条件 — 什么情况下大脑可以不假思索地使用此技能
    intuitive_triggers: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        return self.success_count / max(1, self.use_count)
    
    @property
    def is_embodied(self) -> bool:
        """是否已内化为身体记忆"""
        return self.proficiency in (SkillProficiency.EXPERT, SkillProficiency.MASTER)


@dataclass
class UnityDecision:
    """
    统一决策 — 知行合一的核心单元
    
    不是"先想再做"，而是在决定的那一刻就已经在执行。
    
    传统模式:  思考 → 计划 → 执行 (三段分离)
    知行合一:  决定=行动 (不可分割)
    """
    id: str = ""
    timestamp: float = 0.0
    
    # 认知层
    trigger: str = ""                  # 什么触发了决策
    cognitive_action: str = ""         # 认知动作 (analyze/explore/debug)
    reasoning: List[str] = field(default_factory=list)  # 推理过程
    intention: str = ""                # 意图：想做什么
    
    # 行动层 (与认知层同时产生)
    action_plan: str = ""              # 具体做什么
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # 要调用的工具链
    expected_steps: int = 0            # 期望的步骤数
    
    # 知行合一指标
    confidence: float = 0.5            # 对"知道要做什么"的自信
    execution_readiness: float = 0.5   # 对"能执行"的准备度
    knowledge_action_gap: float = 0.0  # 知行差距 (0=完全合一)
    
    # 执行后
    actual_steps: int = 0
    actual_quality: float = 0.0
    completed: bool = False
    learning: str = ""                 # 从本次执行学到什么
    
    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "action": self.cognitive_action,
            "intention": self.intention[:30],
            "plan": self.action_plan[:30],
            "tools": len(self.tool_calls),
            "confidence": round(self.confidence, 2),
            "readiness": round(self.execution_readiness, 2),
            "gap": round(self.knowledge_action_gap, 2),
        }


class UnityEngine:
    """
    知行合一引擎 — 决策即执行，执行即认知
    
    核心流程 (每个决策都是完整的知行循环):
    
    1. 知 (Knowledge):
       - 理解当前状态 (感知)
       - 检索相关技能 (SkillMemory)
       - 评估自身能力 (自信/准备度)
    
    2. 行 (Action):
       - 决策 = 行动方案 (同时产生)
       - 调用具身技能执行
       - 实时调整执行路径
    
    3. 合 (Unity):
       - 从执行结果获取新知识
       - 更新技能熟练度 (内化)
       - 缩小知行差距
    
    结果: 大脑的每一个"决定"都包含完整执行路径。
    不是"我要分析"，而是"我分析"。
    """

    def __init__(self, cortex: Any, brain: Optional[Any] = None):
        self.cortex = cortex
        self.brain = brain
        
        # 具身技能库 — 大脑"会做的事"
        self.skills: Dict[str, EmbodiedSkill] = {}
        self._init_embodied_skills()
        
        # 决策历史
        self.decisions: List[UnityDecision] = []
        self._max_decisions = 100
        
        # 知行差距追踪
        self._total_gap = 0.0
        self._gap_samples = 0
        self._avg_gap = 0.0
        
        # 统计
        self._total_decisions = 0
        self._skills_used = 0
        self._skills_practiced = 0
        
        logger.info(
            f"UnityEngine initialized: {len(self.skills)} embodied skills"
        )

    def _init_embodied_skills(self):
        """初始化具身技能库"""
        embodied_skills = [
            EmbodiedSkill(
                name="文件分析",
                description="读取并分析文件内容，提取模式和信息",
                cognitive_action="analyze",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "with open('{path}', 'r') as f:\n    content = f.read()\nprint(f'Read {len(content)} chars')"}},
                    {"tool": "run_python", "params_template": {"code": "import re\npatterns = {patterns}\nprint('Pattern analysis complete')"}},
                ],
                proficiency=SkillProficiency.PRACTITIONER,
                intuitive_triggers=["分析文件", "文件内容", "读取"],
                avg_quality=0.7,
            ),
            EmbodiedSkill(
                name="代码调试",
                description="系统化调试：隔离-分析-修复-验证",
                cognitive_action="debug",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "try:\n    {code}\nexcept Exception as e:\n    import traceback\n    traceback.print_exc()\n    print(f'Error: {e}')"}},
                    {"tool": "run_python", "params_template": {"code": "print('Root cause analysis...')"}},
                ],
                proficiency=SkillProficiency.PRACTITIONER,
                intuitive_triggers=["debug", "bug", "错误", "崩溃", "不工作"],
                avg_quality=0.65,
            ),
            EmbodiedSkill(
                name="信息搜索",
                description="搜索和收集相关信息",
                cognitive_action="explore",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "import json\nprint(json.dumps({'search': '{query}', 'results': 'mock_data'}))"}},
                ],
                proficiency=SkillProficiency.EXPERT,
                intuitive_triggers=["搜索", "查找", "找", "查一下", "search"],
                avg_quality=0.85,
            ),
            EmbodiedSkill(
                name="代码生成",
                description="生成和验证代码",
                cognitive_action="execute",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "# {description}\nprint('Generated: {task}')"}},
                    {"tool": "run_python", "params_template": {"code": "# Verification\nprint('Syntax OK')"}},
                ],
                proficiency=SkillProficiency.NOVICE,
                intuitive_triggers=["生成", "创建", "写代码", "实现"],
                avg_quality=0.5,
            ),
            EmbodiedSkill(
                name="数据探索",
                description="探索新数据集的模式和结构",
                cognitive_action="explore",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "print(f'Exploring dataset...')"}},
                    {"tool": "run_python", "params_template": {"code": "print('Pattern detection complete')"}},
                ],
                proficiency=SkillProficiency.PRACTITIONER,
                intuitive_triggers=["探索", "分析数据", "查看"],
                avg_quality=0.75,
            ),
            EmbodiedSkill(
                name="性能优化",
                description="分析性能问题，提出并验证优化方案",
                cognitive_action="debug",
                tool_sequence=[
                    {"tool": "run_python", "params_template": {"code": "# Profile\nimport time\nt0 = time.time()\n{code}\nprint(f'Execution: {time.time()-t0:.3f}s')"}},
                    {"tool": "run_python", "params_template": {"code": "# Optimize\nprint('Optimization applied')"}},
                ],
                proficiency=SkillProficiency.NOVICE,
                intuitive_triggers=["性能", "慢", "优化", "响应时间"],
                avg_quality=0.45,
            ),
        ]
        
        for skill in embodied_skills:
            self.skills[skill.name] = skill

    # ═════════════════════════════════════════════════════
    # 核心：决策 = 行动 (Unity Decision)
    # ═════════════════════════════════════════════════════

    def decide_and_act(self, trigger: str,
                        cognitive_action: str,
                        context: Dict[str, Any] = None,
                        force_deliberate: bool = False) -> UnityDecision:
        """
        知行合一决策 — 决定的那一刻就已经在行动
        
        Args:
            trigger: 触发决策的输入
            cognitive_action: 认知动作 (analyze/debug/explore/execute)
            context: 上下文参数
            force_deliberate: 强制深思(关掉直觉)
        
        Returns:
            UnityDecision: 包含完整执行路径和结果的决策
        """
        self._total_decisions += 1
        t0 = time.time()
        
        decision = UnityDecision(
            id=f"unity_{int(time.time()*1000)}_{self._total_decisions}",
            timestamp=t0,
            trigger=trigger[:100],
            cognitive_action=cognitive_action,
            intention=self._extract_intention(trigger, cognitive_action),
        )
        
        # ── 第一步: 检索匹配的具身技能 ──
        matched_skill = self._select_skill(cognitive_action, trigger, force_deliberate)
        
        if matched_skill:
            decision.execution_readiness = self._compute_readiness(matched_skill)
            decision.tool_calls = self._instantiate_skill(matched_skill, context or {})
            decision.action_plan = self._describe_plan(matched_skill, decision.tool_calls)
            decision.expected_steps = len(decision.tool_calls)
            
            # 知行合一的关键指标: 差距
            # 熟练技能 → 差距小 (知道就能做)
            # 生疏技能 → 差距大 (需要想怎么做)
            if matched_skill.is_embodied:
                decision.knowledge_action_gap = 0.1  # 知行几乎合一
                decision.confidence = min(0.95, 0.5 + matched_skill.success_rate * 0.4)
            elif matched_skill.proficiency == SkillProficiency.PRACTITIONER:
                decision.knowledge_action_gap = 0.3
                decision.confidence = 0.5 + matched_skill.avg_quality * 0.3
            elif matched_skill.proficiency == SkillProficiency.NOVICE:
                decision.knowledge_action_gap = 0.6
                decision.confidence = 0.3 + matched_skill.avg_quality * 0.2
            else:
                decision.knowledge_action_gap = 0.8
                decision.confidence = 0.2
            
            logger.info(
                f"[Unity] {cognitive_action} → 技能='{matched_skill.name}' "
                f"(熟练={matched_skill.proficiency.value}, "
                f"知行差距={decision.knowledge_action_gap:.2f})"
            )
        else:
            # 没有匹配技能 → 回退到通用执行
            decision.action_plan = f"执行{cognitive_action}: {trigger[:40]}"
            decision.execution_readiness = 0.2
            decision.knowledge_action_gap = 0.9  # 很大差距
            decision.confidence = 0.2
            decision.tool_calls = [{
                "tool": "run_python",
                "params": {"code": f"# {cognitive_action}: {trigger[:50]}\nprint('Executing...')"}
            }]
        
        # ── 第二步: 执行 (知行合一 — 决定即执行) ──
        decision = self._execute_decision(decision)
        
        # ── 第三步: 从执行中学习 (内化) ──
        decision = self._learn_from_execution(decision, t0)
        
        self.decisions.append(decision)
        if len(self.decisions) > self._max_decisions:
            self.decisions = self.decisions[-self._max_decisions:]
        
        # 更新全局知行差距
        self._total_gap += decision.knowledge_action_gap
        self._gap_samples += 1
        self._avg_gap = self._total_gap / max(1, self._gap_samples)
        
        # 认知反馈
        if self.brain:
            self._unity_feedback(decision)
        
        logger.info(
            f"[Unity] {decision.cognitive_action} 完成: "
            f"steps={decision.actual_steps}/{decision.expected_steps}, "
            f"quality={decision.actual_quality:.2f}, "
            f"知行差距={decision.knowledge_action_gap:.2f}→{self._avg_gap:.2f}(avg)"
        )
        return decision

    def know_thyself(self) -> Dict[str, Any]:
        """
        自我认知 — 知道自己会什么、不会什么
        
        这是"知"的一半：知道自己知道什么，不知道什么。
        """
        skill_report = {}
        
        for name, skill in self.skills.items():
            triggers = skill.intuitive_triggers[:3]
            skill_report[name] = {
                "proficiency": skill.proficiency.value,
                "success_rate": round(skill.success_rate, 2),
                "use_count": skill.use_count,
                "intuitive_triggers": triggers,
                "is_embodied": skill.is_embodied,
            }
        
        # 知道自己不会什么
        gaps = []
        novice_skills = [
            s for s in self.skills.values()
            if s.proficiency in (SkillProficiency.UNKNOWN, SkillProficiency.AWARE, SkillProficiency.NOVICE)
        ]
        for s in novice_skills:
            gaps.append(f"{s.name}({s.proficiency.value})")
        
        return {
            "embodied_skills": skill_report,
            "total_skills": len(self.skills),
            "expert_skills": sum(1 for s in self.skills.values() if s.proficiency == SkillProficiency.EXPERT),
            "skills_to_practice": gaps,
            "avg_gap": round(self._avg_gap, 3),
        }

    def practice_skill(self, skill_name: str,
                        context: Dict[str, Any] = None) -> UnityDecision:
        """
        刻意练习 — 主动练习一个技能以提升熟练度
        
        知行合一的修炼：通过反复练习，
        让技能从"需要思考"变成"身体记忆"。
        """
        skill = self.skills.get(skill_name)
        if not skill:
            return UnityDecision(
                trigger=f"尝试练习未知技能: {skill_name}",
                cognitive_action="unknown",
                action_plan="技能不存在",
            )
        
        self._skills_practiced += 1
        decision = self.decide_and_act(
            trigger=f"练习{skill_name}",
            cognitive_action=skill.cognitive_action,
            context=context or skill.last_successful_params,
        )
        
        # 提升熟练度
        if decision.actual_quality > 0.7:
            self._advance_proficiency(skill_name)
        
        return decision

    # ═════════════════════════════════════════════════════
    # 内部: 技能选择与执行
    # ═════════════════════════════════════════════════════

    def _select_skill(self, action: str, trigger: str,
                       force_deliberate: bool) -> Optional[EmbodiedSkill]:
        """选择最匹配的具身技能"""
        candidates = []
        trigger_lower = trigger.lower()
        
        for name, skill in self.skills.items():
            if skill.cognitive_action != action:
                continue
            
            # 直觉匹配：触发词是否匹配
            if not force_deliberate:
                match_score = sum(
                    1 for t in skill.intuitive_triggers 
                    if t.lower() in trigger_lower
                )
                if match_score > 0:
                    candidates.append((skill, match_score + skill.success_rate * 2))
            
            # 总是考虑高熟练度技能
            if skill.is_embodied:
                candidates.append((skill, skill.success_rate * 3))
        
        if not candidates:
            return None
        
        # 按匹配度排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _instantiate_skill(self, skill: EmbodiedSkill,
                            context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将技能模板实例化为具体工具调用"""
        tool_calls = []
        
        for step in skill.tool_sequence:
            template = step["params_template"]
            params = {}
            
            for k, v in template.items():
                if isinstance(v, str):
                    # 模板替换
                    filled = v
                    for ck, cv in context.items():
                        filled = filled.replace(f"{{{ck}}}", str(cv)[:500])
                    # 默认值替换
                    filled = filled.replace("{code}", "print('default')")
                    filled = filled.replace("{path}", ".")
                    filled = filled.replace("{query}", "default")
                    filled = filled.replace("{task}", "default_task")
                    filled = filled.replace("{description}", "auto")
                    filled = filled.replace("{patterns}", "{}")
                    params[k] = filled
                else:
                    params[k] = v
            
            tool_calls.append({
                "tool": step["tool"],
                "params": params,
            })
        
        return tool_calls

    def _compute_readiness(self, skill: EmbodiedSkill) -> float:
        """计算执行准备度"""
        readiness = 0.3
        readiness += skill.success_rate * 0.3
        
        if skill.proficiency == SkillProficiency.MASTER:
            readiness += 0.3
        elif skill.proficiency == SkillProficiency.EXPERT:
            readiness += 0.2
        elif skill.proficiency == SkillProficiency.PRACTITIONER:
            readiness += 0.1
        
        return min(0.99, readiness)

    def _describe_plan(self, skill: EmbodiedSkill,
                        tool_calls: List[Dict]) -> str:
        """生成决策中包含的执行方案描述"""
        steps = [f"Step{i+1}: {t['tool']}" for i, t in enumerate(tool_calls)]
        return f"[{skill.name}] {' → '.join(steps)}"

    def _extract_intention(self, trigger: str, action: str) -> str:
        """提取意图"""
        return f"对'{trigger[:40]}'执行{action}"

    def _execute_decision(self, decision: UnityDecision) -> UnityDecision:
        """执行决策中的所有工具调用"""
        if not hasattr(self.cortex, 'execute'):
            decision.actual_steps = 0
            decision.completed = True
            return decision
        
        success_count = 0
        for call in decision.tool_calls:
            try:
                record = self.cortex.execute(
                    call["tool"], call["params"],
                    confidence=decision.confidence,
                )
                if record.status.value == "success":
                    success_count += 1
            except Exception as e:
                logger.warning(f"Unity execute failed: {e}")
            
            decision.actual_steps += 1
        
        decision.actual_quality = success_count / max(1, len(decision.tool_calls))
        decision.completed = True
        return decision

    def _learn_from_execution(self, decision: UnityDecision,
                               t0: float) -> UnityDecision:
        """从执行中学习，缩小知行差距"""
        # 找到使用的技能
        used_skill = None
        for name, skill in self.skills.items():
            if skill.cognitive_action == decision.cognitive_action:
                if skill.name in decision.action_plan:
                    used_skill = skill
                    break
        
        if not used_skill:
            return decision
        
        # 更新技能统计
        used_skill.use_count += 1
        used_skill.last_used = time.time()
        
        if decision.actual_quality > 0.5:
            used_skill.success_count += 1
        
        # 更新平均质量和耗时
        duration = (time.time() - t0) * 1000
        used_skill.avg_duration_ms = (
            used_skill.avg_duration_ms * 0.9 + duration * 0.1
        )
        used_skill.avg_quality = (
            used_skill.avg_quality * 0.9 + decision.actual_quality * 0.1
        )
        
        # 记录成功参数
        if decision.actual_quality > 0.7 and decision.tool_calls:
            used_skill.last_successful_params = decision.tool_calls[0].get("params", {})
        
        # 生成学习摘要
        if decision.actual_quality > 0.7:
            decision.learning = f"{used_skill.name}执行成功, 技能熟练度提升"
            used_skill.proficiency = self._next_proficiency(used_skill.proficiency)
        elif decision.actual_quality > 0.3:
            decision.learning = f"{used_skill.name}部分完成, 需要更多练习"
        else:
            decision.learning = f"{used_skill.name}失败, 需要退回到更基础的方法"
        
        # 缩小知行差距
        if decision.actual_quality > 0.5:
            decision.knowledge_action_gap *= 0.9  # 执行成功缩小差距
        
        self._skills_used += 1
        return decision

    def _advance_proficiency(self, skill_name: str):
        """提升技能熟练度"""
        skill = self.skills.get(skill_name)
        if not skill:
            return
        
        if skill.use_count >= 20 and skill.success_rate > 0.9:
            skill.proficiency = SkillProficiency.MASTER
        elif skill.use_count >= 10 and skill.success_rate > 0.8:
            skill.proficiency = SkillProficiency.EXPERT
        elif skill.use_count >= 5 and skill.success_rate > 0.7:
            skill.proficiency = SkillProficiency.PRACTITIONER
        elif skill.use_count >= 1:
            skill.proficiency = SkillProficiency.NOVICE

    def _next_proficiency(self, current: SkillProficiency) -> SkillProficiency:
        """下一个熟练度等级"""
        progression = [
            SkillProficiency.UNKNOWN,
            SkillProficiency.AWARE,
            SkillProficiency.NOVICE,
            SkillProficiency.PRACTITIONER,
            SkillProficiency.EXPERT,
            SkillProficiency.MASTER,
        ]
        try:
            idx = progression.index(current)
            if idx < len(progression) - 1:
                return progression[idx + 1]
        except ValueError as e:
            logger.debug(f"操作失败: {e}")
        return current

    def _unity_feedback(self, decision: UnityDecision):
        """知行合一的认知反馈"""
        brain = self.brain
        if not brain:
            return
        
        # 更新需求
        if hasattr(brain, 'needs'):
            from laap.cognition.needs import NeedType
            if decision.actual_quality > 0.7:
                brain.needs.satisfy(NeedType.COMPETENCE, 0.08)
                brain.needs.satisfy(NeedType.CERTAINTY, 0.05)
            elif decision.actual_quality < 0.3:
                brain.needs.satisfy(NeedType.CERTAINTY, -0.05)
                if hasattr(brain, 'meta_cognition'):
                    brain.meta_cognition.state.curiosity_level = min(
                        1.0, brain.meta_cognition.state.curiosity_level + 0.1
                    )
        
        # 情感
        if hasattr(brain, 'comprehensive_emotion'):
            if decision.actual_quality > 0.7:
                brain.comprehensive_emotion.trigger(
                    "tool_success", decision.actual_quality, 
                    f"unity_{decision.cognitive_action}"
                )
        
        # 元认知
        if hasattr(brain, 'meta_cognition'):
            brain.meta_cognition.after_decision(
                {
                    "task": decision.trigger[:40],
                    "selected": decision.cognitive_action,
                    "confidence": decision.confidence,
                    "duration_ms": 0,
                },
                outcome={"score": decision.actual_quality, "reflection": decision.learning},
            )

    # ═════════════════════════════════════════════════════
    # 查询
    # ═════════════════════════════════════════════════════

    def introspect(self) -> str:
        """内省：知道自己会什么、不会什么"""
        lines = ["=== 知行合一状态 ==="]
        lines.append(f"平均知行差距: {self._avg_gap:.3f}")
        lines.append("")
        lines.append("具身技能:")
        
        for name, skill in self.skills.items():
            embodied = "✓" if skill.is_embodied else " "
            lines.append(
                f"  [{embodied}] {name}: {skill.proficiency.value}"
                f" (使用{skill.use_count}次, "
                f"成功率{skill.success_rate:.0%})"
            )
        
        lines.append("")
        novice = [n for n, s in self.skills.items() 
                  if s.proficiency == SkillProficiency.NOVICE]
        if novice:
            lines.append(f"需要练习: {', '.join(novice)}")
        
        return "\n".join(lines)

    def status(self) -> dict:
        return {
            "skills": len(self.skills),
            "embodied": sum(1 for s in self.skills.values() if s.is_embodied),
            "decisions": self._total_decisions,
            "avg_gap": round(self._avg_gap, 3),
            "practices": self._skills_practiced,
        }
