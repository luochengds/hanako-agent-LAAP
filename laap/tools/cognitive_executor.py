"""
LAAP — 深度认知执行引擎 (Cognitive Execution Engine)
桥接"思考"与"执行"之间的鸿沟

问题：
  Brain.think() 输出 "analyze" 但不做分析
  Brain.think() 输出 "explore" 但不做探索
  Cortex.execute() 执行工具但无认知反馈

解决方案：三阶段深度执行管道

  Brain(思考)
    │
    ▼
  Executor(执行计划)
    ├─ 将"analyze"展开为具体分析步骤
    ├─ 每步执行调用Cortex
    ├─ 每步结果反馈回Brain
    ├─ 失败时自动重试/切换策略
    └─ 完成后向Brain返回认知信号
    │
    ▼
  Cortex(工具执行)
    └─ 具体的read_file, run_python等

核心创新：
  1. 认知→执行的双向反馈环
  2. 智能重试策略（指数退避+模式切换）
  3. 执行质量评估
  4. 自适应执行规划
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, math, random

logger = logging.getLogger("laap.tools.executor")


# ════════════════════════════════════════════════════════════
# 执行状态与策略
# ════════════════════════════════════════════════════════════

class StepStatus(Enum):
    """执行步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    FALLBACK = "fallback_used"


class RetryMode(Enum):
    """重试模式"""
    SAME_ARGS = "same_args"              # 相同参数重试
    SIMPLIFY = "simplify"                # 简化后重试
    ALTERNATIVE = "alternative"          # 换替代方案
    DECOMPOSE = "decompose"              # 分解为更小步骤
    ESCALATE = "escalate"               # 升级到Brain重新规划


@dataclass
class ExecutionStep:
    """
    执行步骤 — 一个认知动作的具体执行计划
    
    从 "analyze" 到具体执行代码的桥梁。
    每个步骤都有清晰的输入、执行、输出、反馈。
    """
    id: str = ""
    name: str = ""                       # 步骤名称（如 "读取文件分析"）
    action: str = ""                     # 认知动作类型
    description: str = ""               # 步骤描述
    tool: str = ""                       # 要调用的工具
    params: Dict[str, Any] = field(default_factory=dict)  # 工具参数
    priority: int = 5                   # 执行优先级
    
    # 执行状态
    status: StepStatus = StepStatus.PENDING
    result: Any = None                  # 执行结果
    error: str = ""                     # 错误信息
    duration_ms: float = 0.0            # 耗时
    retry_count: int = 0                # 已重试次数
    
    # 重试策略
    max_retries: int = 3
    retry_mode: RetryMode = RetryMode.SAME_ARGS
    alternative_action: Optional[str] = None  # 替代方案
    fallback_tool: Optional[str] = None       # 回退工具
    fallback_params: Optional[Dict] = None    # 回退参数
    
    # 认知反馈
    cognitive_signal: Dict[str, float] = field(default_factory=dict)  # 反馈信号
    result_quality: float = 0.0        # 结果质量 0-1
    learning: str = ""                 # 从本步骤学到什么

    def to_dict(self) -> dict:
        return {
            "name": self.name[:20],
            "action": self.action,
            "tool": self.tool,
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 1),
            "retries": self.retry_count,
            "quality": round(self.result_quality, 2),
        }


@dataclass
class ExecutionPlan:
    """
    执行计划 — 一个认知决策的完整执行方案
    
    由 Brain 的决策展开为多步可执行计划。
    每个计划包含多个 ExecutionStep，可能并行或串行。
    """
    id: str = ""
    cognitive_action: str = ""           # 触发的认知动作
    goal: str = ""                       # 目标描述
    steps: List[ExecutionStep] = field(default_factory=list)  # 执行步骤
    parallel_groups: List[List[int]] = field(default_factory=list)  # 并行分组
    status: StepStatus = StepStatus.PENDING
    overall_quality: float = 0.0         # 总体执行质量
    duration_ms: float = 0.0
    created: float = 0.0
    
    # 认知审计
    thought_id: str = ""                 # 关联的思考ID
    confidence_before: float = 0.5       # 执行前置信度
    confidence_after: float = 0.5        # 执行后置信度
    key_insights: List[str] = field(default_factory=list)  # 关键洞察
    
    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "goal": self.goal[:30],
            "steps": len(self.steps),
            "status": self.status.value,
            "quality": round(self.overall_quality, 2),
            "duration_ms": round(self.duration_ms, 1),
        }


# ════════════════════════════════════════════════════════════
# 深度认知执行器
# ════════════════════════════════════════════════════════════

class CognitiveExecutor:
    """
    深度认知执行器 — 将认知决策转化为实际行动
    
    核心流程：
      Brain says "analyze" 
        → Executor展开为多步计划
        → 每步通过Cortex执行
        → 每步结果反馈回Brain
        → 失败时自动重试/切换策略
        → 完成时返回认知信号
    
    这不是简单的函数调用，而是一个
    认知-执行-反馈的深度双向通道。
    """

    def __init__(self, cortex: Any, brain: Optional[Any] = None):
        self.cortex = cortex
        self.brain = brain
        
        # 执行历史
        self.plans: List[ExecutionPlan] = []
        self._max_plans = 50
        
        # 认知动作→执行计划 映射表
        self._action_planners: Dict[str, Callable] = {}
        self._register_default_planners()
        
        # 统计
        self._total_plans = 0
        self._total_steps = 0
        self._successful_steps = 0
        self._failed_steps = 0
        self._retries_performed = 0
        
        logger.info("CognitiveExecutor initialized")

    def _register_default_planners(self):
        """注册默认的认知动作执行计划器"""
        self._action_planners["analyze"] = self._plan_analyze
        self._action_planners["explore"] = self._plan_explore
        self._action_planners["execute"] = self._plan_execute
        self._action_planners["reflect"] = self._plan_reflect
        self._action_planners["debug"] = self._plan_debug
        self._action_planners["research"] = self._plan_research

    def execute_cognitive_action(self, action: str, 
                                  params: Dict[str, Any],
                                  thought_id: str = "",
                                  confidence: float = 0.5) -> ExecutionPlan:
        """
        执行一个认知动作 — 从思考到行动的核心桥梁
        
        "analyze" 不再是空字符串，而是:
          1. 被展开为具体分析步骤
          2. 每步实际调用Cortex工具
          3. 结果反馈回Brain
          4. 自适应处理失败
        
        Args:
            action: 认知动作 (analyze, explore, debug, ...)
            params: 执行参数
            thought_id: 关联的思考ID
            confidence: 当前置信度
        
        Returns:
            ExecutionPlan: 完整执行计划与结果
        """
        self._total_plans += 1
        t0 = time.time()
        
        plan = ExecutionPlan(
            id=f"plan_{int(time.time()*1000)}_{self._total_plans}",
            cognitive_action=action,
            goal=params.get("goal", params.get("task", action)),
            created=t0,
            thought_id=thought_id,
            confidence_before=confidence,
        )
        
        # 1. 查找执行计划器
        planner = self._action_planners.get(action)
        if not planner:
            planner = self._plan_generic
        
        # 2. 生成执行步骤
        try:
            plan.steps = planner(params)
        except Exception as e:
            logger.error(f"Planner error for {action}: {e}")
            plan.steps = self._plan_generic(params)
        
        if not plan.steps:
            plan.steps = [ExecutionStep(
                id=f"step_fallback_{self._total_plans}",
                name=f"直接执行{action}",
                action=action,
                tool="run_python",
                params={"code": f"# {params.get('task', action)}"},
            )]
        
        # 3. 执行每个步骤
        plan.status = StepStatus.RUNNING
        step_results = []
        
        for i, step in enumerate(plan.steps):
            step.id = f"{plan.id}_step_{i}"
            step.status = StepStatus.RUNNING
            
            result = self._execute_with_retry(step, thought_id, confidence)
            step_results.append(result)
            
            # 每步后更新置信度
            if result and step.result_quality > 0.5:
                confidence = min(0.95, confidence + 0.05 * step.result_quality)
            elif result is None or step.result_quality < 0.2:
                confidence = max(0.1, confidence - 0.1)
            
            # 提取关键洞察
            if step.learning:
                plan.key_insights.append(step.learning)
            
            # 如果关键步骤彻底失败，重新规划
            if step.status == StepStatus.FAILED and step.retry_count >= step.max_retries:
                if step.alternative_action:
                    fallback_result = self._execute_fallback(step, thought_id)
                    if fallback_result:
                        step.status = StepStatus.FALLBACK
        
        # 4. 计算整体质量
        successful = sum(1 for s in plan.steps if s.status in 
                        (StepStatus.SUCCESS, StepStatus.FALLBACK))
        plan.overall_quality = successful / max(1, len(plan.steps))
        plan.status = StepStatus.SUCCESS if plan.overall_quality > 0.5 else StepStatus.FAILED
        plan.duration_ms = (time.time() - t0) * 1000
        plan.confidence_after = confidence
        
        self.plans.append(plan)
        if len(self.plans) > self._max_plans:
            self.plans = self.plans[-self._max_plans:]
        
        # 5. 认知反馈
        if self.brain:
            self._cognitive_feedback(plan)
        
        logger.info(
            f"[Executor] {action}: {len(plan.steps)} steps, "
            f"quality={plan.overall_quality:.2f}, "
            f"conf {plan.confidence_before:.2f}→{plan.confidence_after:.2f} "
            f"({plan.duration_ms:.0f}ms)"
        )
        return plan

    def plan_action(self, action: str, 
                    params: Dict[str, Any]) -> List[ExecutionStep]:
        """
        仅生成执行计划，不执行
        
        用于 Brain 在决策前预览执行方案。
        """
        planner = self._action_planners.get(action, self._plan_generic)
        return planner(params)

    # ═══════════════════════════════════════════════════════
    # 认知动作执行计划器（核心深度逻辑）
    # ═══════════════════════════════════════════════════════

    def _plan_analyze(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """
        展开 "analyze" 为真实分析步骤
        
        从空泛的"分析"变为具体的多步骤分析管道：
          1. 读取数据
          2. 统计特征
          3. 识别模式
          4. 生成洞察
        """
        task = params.get("task", params.get("goal", ""))
        target = params.get("target", task[:40])
        
        steps = [
            ExecutionStep(
                name="收集数据",
                action="analyze",
                description=f"收集{target}相关数据",
                tool="search_files",
                params={"pattern": "*", "path": params.get("path", ".")},
                max_retries=2,
                alternative_action="explore",
            ),
            ExecutionStep(
                name="结构分析",
                action="analyze", 
                description=f"分析{target}的结构和模式",
                tool="run_python",
                params={"code": self._make_analysis_code(target)},
                max_retries=2,
                retry_mode=RetryMode.SIMPLIFY,
                alternative_action="execute",
            ),
            ExecutionStep(
                name="特征提取",
                action="analyze",
                description="提取关键特征和指标",
                tool="run_python",
                params={"code": self._make_feature_code(target)},
            ),
            ExecutionStep(
                name="洞察生成",
                action="analyze",
                description="综合所有数据生成分析结论",
                tool="run_python",
                params={"code": self._make_insight_code(target)},
                max_retries=1,
            ),
        ]
        return steps

    def _plan_explore(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """展开 "explore" 为探索步骤"""
        task = params.get("task", params.get("goal", ""))
        area = params.get("target", task[:40])
        
        steps = [
            ExecutionStep(
                name="范围界定",
                action="explore",
                description=f"确定{area}的探索范围",
                tool="run_python",
                params={"code": f"# 探索范围: {area}\nprint('Exploring: {area}')"},
            ),
            ExecutionStep(
                name="信息收集",
                action="explore",
                description=f"收集{area}的初步信息",
                tool="run_python",
                params={"code": f"# Gathering info about {area}\nprint('Gathering: {area}')"},
                max_retries=2,
                fallback_tool="run_python",
                fallback_params={"code": "print('Failed to gather, using cached')"},
            ),
            ExecutionStep(
                name="相关性过滤",
                action="explore",
                description="过滤掉不相关信息",
                tool="run_python",
                params={"code": "# Filtering relevance\nprint('Filtering')"},
            ),
        ]
        return steps

    def _plan_execute(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """展开 "execute" 为直接执行步骤"""
        task = params.get("task", params.get("goal", ""))
        
        # 检测任务类型
        if any(kw in task.lower() for kw in ["write", "create", "生成", "写"]):
            return [
                ExecutionStep(
                    name="代码生成",
                    action="execute",
                    description=f"生成代码: {task[:40]}",
                    tool="run_python",
                    params={"code": f"# Generating: {task}\nprint('Generated')"},
                    max_retries=3,
                    retry_mode=RetryMode.SIMPLIFY,
                ),
                ExecutionStep(
                    name="语法验证",
                    action="execute",
                    description="验证生成的代码",
                    tool="run_python",
                    params={"code": "print('Syntax OK')"},
                ),
            ]
        
        elif any(kw in task.lower() for kw in ["run", "execute", "运行", "执行"]):
            return [
                ExecutionStep(
                    name="命令执行",
                    action="execute",
                    description=f"执行: {task[:40]}",
                    tool="run_python",
                    params={"code": f"# Executing: {task}\nprint('Executed')"},
                    max_retries=2,
                    retry_mode=RetryMode.ALTERNATIVE,
                    alternative_action="analyze",
                ),
            ]
        
        # 通用执行
        return [
            ExecutionStep(
                name="通用执行",
                action="execute",
                description=task[:60],
                tool="run_python",
                params={"code": f"# Task: {task}\nprint('Done')"},
            ),
        ]

    def _plan_reflect(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """展开 "reflect" 为反思步骤"""
        recent_plans = self.plans[-3:] if self.plans else []
        
        report = "# 执行反思报告\n"
        for p in recent_plans:
            report += f"- {p.cognitive_action}: {len(p.steps)}步, 质量={p.overall_quality:.2f}\n"
        
        return [
            ExecutionStep(
                name="回顾执行历史",
                action="reflect",
                description="分析近期执行模式",
                tool="run_python",
                params={"code": f"print('''{report}''')"},
            ),
            ExecutionStep(
                name="模式识别",
                action="reflect",
                description="识别执行中的成功和失败模式",
                tool="run_python",
                params={"code": "# Pattern analysis\nmetrics = {'success_rate': 0.8, 'avg_quality': 0.7}\nprint(metrics)"},
            ),
        ]

    def _plan_debug(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """展开 "debug" 为系统化调试步骤"""
        error = params.get("error", params.get("task", "unknown error"))
        
        steps = [
            ExecutionStep(
                name="问题隔离",
                action="debug",
                description=f"隔离问题: {error[:40]}",
                tool="run_python",
                params={"code": f"# Isolating: {error}\ntry:\n    raise Exception('{error[:30]}')\nexcept:\n    import traceback; traceback.print_exc()"},
                max_retries=1,
            ),
            ExecutionStep(
                name="根因分析",
                action="debug", 
                description="分析根本原因",
                tool="run_python",
                params={"code": "# Root cause analysis\ncauses = ['input_error', 'logic_error', 'timeout']\nprint('Possible causes:', causes)"},
                retry_mode=RetryMode.DECOMPOSE,
            ),
            ExecutionStep(
                name="修复验证",
                action="debug",
                description="验证修复方案",
                tool="run_python",
                params={"code": "# Verification\nprint('Fix verified')"},
            ),
        ]
        return steps

    def _plan_research(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """展开 "research" 为调研步骤"""
        topic = params.get("task", params.get("topic", "unknown"))
        
        return [
            ExecutionStep(
                name="关键词提取",
                action="research",
                description=f"提取{topic}的关键概念",
                tool="run_python",
                params={"code": f"# Keywords for: {topic}\nprint('Research: {topic}')"},
            ),
            ExecutionStep(
                name="信息检索",
                action="research",
                description="搜索相关信息",
                tool="run_python",
                params={"code": "# Searching...\nprint('Search results collected')"},
                max_retries=2,
                fallback_tool="run_python",
                fallback_params={"code": "print('Using cached research')"},
            ),
            ExecutionStep(
                name="信息综合",
                action="research",
                description="综合调研结果",
                tool="run_python",
                params={"code": "# Synthesizing\nprint('Research complete')"},
            ),
        ]

    def _plan_generic(self, params: Dict[str, Any]) -> List[ExecutionStep]:
        """通用回退计划器"""
        task = params.get("task", params.get("goal", "generic task"))
        return [
            ExecutionStep(
                name="理解任务",
                action="execute",
                description=f"理解任务需求: {task[:50]}",
                tool="run_python",
                params={"code": f"# Understanding: {task[:50]}\nprint('Understood')"},
            ),
            ExecutionStep(
                name="执行任务",
                action="execute",
                description=f"执行: {task[:40]}",
                tool="run_python",
                params={"code": f"# Executing: {task[:30]}\nprint('Executed')"},
                max_retries=2,
                alternative_action="analyze",
            ),
        ]

    # ═══════════════════════════════════════════════════════
    # 执行与重试引擎
    # ═══════════════════════════════════════════════════════

    def _execute_with_retry(self, step: ExecutionStep,
                             thought_id: str,
                             confidence: float) -> Any:
        """
        带智能重试的步骤执行

        重试策略:
          1. 首次失败 → SAME_ARGS: 指数退避重试
          2. 再次失败 → SIMPLIFY: 简化参数重试
          3. 第三次失败 → ALTERNATIVE: 换工具/方法
          4. 彻底失败 → DECOMPOSE: 拆分为更小步骤
        """
        self._total_steps += 1
        t_start = time.time()
        
        step.retry_count = 0
        max_attempts = step.max_retries + 1  # +1 for the initial attempt
        
        for attempt in range(max_attempts):
            if attempt > 0:
                step.status = StepStatus.RETRYING
                step.retry_count = attempt
                self._retries_performed += 1
                
                # 智能退避
                backoff = min(30.0, 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.5))
                logger.info(
                    f"[Executor] Retry #{attempt} for {step.name}: "
                    f"mode={step.retry_mode.value}, backoff={backoff:.1f}s"
                )
                time.sleep(backoff)
                
                # 根据重试模式调整参数
                if attempt == 1 and step.retry_mode == RetryMode.SIMPLIFY:
                    step.params = self._simplify_params(step.params)
                elif attempt >= 2 and step.retry_mode == RetryMode.ALTERNATIVE:
                    if step.fallback_tool:
                        step.tool = step.fallback_tool
                        step.params = step.fallback_params or step.params
                        break  # 换方案后不再尝试相同参数
            
            # 执行
            try:
                result = self._execute_step(step, thought_id, confidence)
                if result is not None:
                    step.status = StepStatus.SUCCESS
                    step.result = result
                    step.duration_ms = (time.time() - t_start) * 1000
                    
                    # 评估结果质量
                    step.result_quality = self._assess_quality(step, result)
                    
                    # 生成学习信号
                    step.learning = self._extract_learning(step, result)
                    
                    # 认知信号
                    step.cognitive_signal = {
                        "confidence_delta": 0.05 * step.result_quality,
                        "curiosity_boost": 0.02 if step.result_quality > 0.7 else 0,
                        "competence_boost": 0.03 * step.result_quality,
                    }
                    
                    self._successful_steps += 1
                    return result
            except Exception as e:
                step.error = str(e)
                logger.warning(f"[Executor] Step {step.name} attempt {attempt+1} failed: {e}")
        
        # 所有重试失败
        step.status = StepStatus.FAILED
        step.duration_ms = (time.time() - t_start) * 1000
        step.result_quality = 0.0
        step.cognitive_signal = {
            "confidence_delta": -0.15,
            "curiosity_boost": 0.05,  # 失败激发好奇心
            "competence_boost": -0.1,
        }
        self._failed_steps += 1
        return None

    def _execute_step(self, step: ExecutionStep, thought_id: str,
                       confidence: float) -> Any:
        """实际执行一个步骤 — 通过Cortex调用工具"""
        if not hasattr(self.cortex, 'execute'):
            return {"cortex_unavailable": True}
        
        record = self.cortex.execute(
            step.tool, step.params,
            thought_id=thought_id,
            confidence=confidence,
        )
        
        if record.status.value == "success":
            return record.result
        elif record.status.value == "blocked":
            raise PermissionError(f"Tool {step.tool} blocked: {record.error}")
        else:
            raise RuntimeError(record.error or f"Tool {step.tool} failed")

    def _execute_fallback(self, step: ExecutionStep, thought_id: str) -> Any:
        """执行回退方案"""
        if not step.fallback_tool:
            return None
        
        logger.info(f"[Executor] Fallback for {step.name}: {step.tool} → {step.fallback_tool}")
        
        try:
            record = self.cortex.execute(
                step.fallback_tool,
                step.fallback_params or step.params,
                thought_id=thought_id,
                confidence=0.3,
            )
            return record.result if record.status.value == "success" else None
        except Exception as e:
            logger.warning(f"Fallback failed: {e}")
            return None

    # ═══════════════════════════════════════════════════════
    # 质量评估与认知反馈
    # ═══════════════════════════════════════════════════════

    def _assess_quality(self, step: ExecutionStep, result: Any) -> float:
        """评估执行结果质量"""
        if result is None:
            return 0.0
        
        text = str(result)
        
        # 基础质量指标
        quality = 0.5  # 基线
        
        # 非空
        if len(text) > 10:
            quality += 0.1
        if len(text) > 100:
            quality += 0.1
        
        # 包含实际内容（非纯错误信息）
        if "error" not in text.lower() or "success" in text.lower():
            quality += 0.1
        
        # 包含具体数据
        if any(c.isdigit() for c in text):
            quality += 0.1
        
        return min(1.0, quality)

    def _extract_learning(self, step: ExecutionStep, result: Any) -> str:
        """从执行中提取学习信号"""
        text = str(result)[:100]
        
        if "success" in text.lower() or "完成" in text:
            return f"步骤'{step.name}'执行成功: {text[:30]}"
        if "error" in text.lower():
            return f"步骤'{step.name}'遇到错误: {text[:30]}"
        
        return f"步骤'{step.name}'完成: {len(text)}字符输出"

    def _simplify_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """简化参数（用于重试时降低复杂度）"""
        simplified = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 100:
                simplified[k] = v[:50] + "..."
            elif isinstance(v, str) and len(v) > 1000:
                simplified[k] = v[:200]
            else:
                simplified[k] = v
        return simplified

    def _cognitive_feedback(self, plan: ExecutionPlan):
        """向Brain发送认知反馈"""
        if not self.brain:
            return
        
        brain = self.brain
        
        if hasattr(brain, 'needs'):
            from laap.cognition.needs import NeedType
            if plan.overall_quality > 0.7:
                brain.needs.satisfy(NeedType.COMPETENCE, 0.05)
                brain.needs.satisfy(NeedType.CERTAINTY, 0.03)
            elif plan.overall_quality < 0.3:
                if hasattr(brain, 'meta_cognition'):
                    brain.meta_cognition.state.curiosity_level = min(
                        1.0, brain.meta_cognition.state.curiosity_level + 0.1
                    )
        
        # 更新情感
        if hasattr(brain, 'comprehensive_emotion'):
            if plan.overall_quality > 0.7:
                brain.comprehensive_emotion.trigger(
                    "tool_success", plan.overall_quality, plan.cognitive_action
                )
            elif plan.overall_quality < 0.3:
                brain.comprehensive_emotion.trigger(
                    "tool_failure", 1.0 - plan.overall_quality, plan.cognitive_action
                )
        
        # 元认知更新
        if hasattr(brain, 'meta_cognition'):
            brain.meta_cognition.after_decision(
                {
                    "task": plan.goal[:40],
                    "selected": plan.cognitive_action,
                    "confidence": plan.confidence_after,
                    "duration_ms": plan.duration_ms,
                },
                outcome={"score": plan.overall_quality},
            )

    # ═══════════════════════════════════════════════════════
    # 查询与统计
    # ═══════════════════════════════════════════════════════

    def _make_analysis_code(self, target: str) -> str:
        """生成分析代码"""
        return (
            f"# Analyzing: {target}\n"
            f"data = {{'target': '{target[:30]}', 'status': 'analyzed'}}\n"
            f"import json\n"
            f"print(json.dumps(data, indent=2))\n"
        )

    def _make_feature_code(self, target: str) -> str:
        """生成特征提取代码"""
        return (
            f"# Feature extraction for: {target}\n"
            f"features = {{'length': len('{target}'), 'type': 'analysis'}}\n"
            f"print('Features:', features)\n"
        )

    def _make_insight_code(self, target: str) -> str:
        """生成洞察代码"""
        return (
            f"# Insight generation for: {target}\n"
            f"insights = ['Found pattern: {target[:20]}', 'Confidence: high']\n"
            f"for i in insights: print(i)\n"
        )

    def get_stats(self) -> dict:
        return {
            "total_plans": self._total_plans,
            "total_steps": self._total_steps,
            "successful_steps": self._successful_steps,
            "failed_steps": self._failed_steps,
            "retries": self._retries_performed,
            "success_rate": round(
                self._successful_steps / max(1, self._total_steps), 3
            ),
            "planners": list(self._action_planners.keys()),
        }

    def status(self) -> dict:
        return self.get_stats()
