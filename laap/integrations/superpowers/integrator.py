"""SuperpowersIntegrator — 桥接Superpowers方法论到LAAP Agent"""
from __future__ import annotations
import os, json, logging, time, re
from typing import Any, Callable, Dict, List, Optional

from laap.integrations.superpowers.registry import SuperpowerSkillRegistry, ActivationTrigger
from laap.agent_core.plugins.hooks import HookRegistry, HookPoint

logger = logging.getLogger("integrations.superpowers.integrator")

class SuperpowersIntegrator:
    """
    Superpowers → LAAP 积分器
    
    将Superpowers的14项软件开发方法论注册为LAAP的插件hooks。
    每当LAAP Agent遇到对应场景, 自动激活Superpowers技能:
    - 写代码前 → brainstorming
    - 写计划前 → writing-plans  
    - 执行计划 → subagent-driven-development
    - commit前 → requesting-code-review
    - 调试时 → systematic-debugging
    """
    
    def __init__(self):
        self.registry = SuperpowerSkillRegistry()
        self._activated: Dict[str, float] = {}
        self._stats = {"activations": 0, "skills_used": 0}
    
    def install(self):
        """安装所有Superpowers hooks到LAAP系统"""
        
        # 注册所有激活点
        HookRegistry.register(HookPoint.BEFORE_TOOL, self._check_activation, "superpowers")
        
        logger.info(f"Superpowers installed: {len(self.registry.get_all())} skills")
    
    def _check_activation(self, ctx) -> Any:
        """检查是否需要激活Superpowers技能"""
        if not ctx or not ctx.data:
            return ctx.data
        
        text = str(ctx.data).lower()
        activations = []
        
        # 检测场景 → 触发对应技能
        if self._is_coding_request(text):
            activations.extend(self.registry.activate(ActivationTrigger.BEFORE_CODE))
        if self._is_planning_request(text):
            activations.extend(self.registry.activate(ActivationTrigger.BEFORE_PLAN))
        if self._is_debugging_request(text):
            activations.extend(self.registry.activate(ActivationTrigger.WHILE_DEBUGGING))
        if self._is_testing_request(text):
            activations.extend(self.registry.activate(ActivationTrigger.DURING_TEST))
        
        if activations:
            self._stats["activations"] += 1
            self._stats["skills_used"] += len(activations)
            
            # 记录激活
            for a in activations:
                self._activated[a["name"]] = time.time()
                logger.info(f"Superpower activated: {a['name']}")
            
            # 给Agent上下文注入技能指令
            ctx.result = self._format_activation(activations)
        
        return ctx.result or ctx.data
    
    def _is_coding_request(self, text: str) -> bool:
        patterns = [r"(?i)(write|create|implement|build|code|make|开发|编写|创建).*(function|class|api|app|module|feature)",
                   r"(?i)refactor|重构|优化|modify|change|update|add .*(feature|function)"]
        return any(re.search(p, text) for p in patterns)
    
    def _is_planning_request(self, text: str) -> bool:
        patterns = [r"(?i)(plan|design|architecture|spec|设计|架构|规范|方案)",
                   r"(?i)(how.*(implement|build)|实现方案|技术方案|设计方案)"]
        return any(re.search(p, text) for p in patterns)
    
    def _is_debugging_request(self, text: str) -> bool:
        patterns = [r"(?i)(debug|fix|bug|error|issue|修复|问题|bug|报错|异常|错误)"]
        return any(re.search(p, text) for p in patterns)
    
    def _is_testing_request(self, text: str) -> bool:
        patterns = [r"(?i)(test|testing|unit test|集成测试|测试|tdd)"]
        return any(re.search(p, text) for p in patterns)
    
    def _format_activation(self, activations: List[dict]) -> str:
        """格式化激活的技能为Agent上下文"""
        parts = ["\n## 🔋 Superpowers Activated\n"]
        for a in activations:
            status = "⚠️ MANDATORY" if a.get("mandatory") else "💡 Suggested"
            parts.append(f"### {status}: {a['name']}")
            parts.append(f"{a['description']}")
            # Extract key steps (first 200 chars of instructions)
            instr = a.get("instructions", "")
            if instr:
                steps = instr.split("\n")[:5]
                parts.append("```")
                parts.extend(steps)
                parts.append("```")
        return "\n".join(parts)
    
    def get_stats(self) -> dict:
        skills_status = [{"name": n, "activated_at": t} for n, t in self._activated.items()]
        return dict(self._stats, registry=self.registry.get_stats(), recent_skills=skills_status[-5:])
    
    def get_workflow_for(self, task: str) -> List[dict]:
        """推荐当前任务的Superpowers工作流"""
        workflow = []
        text = task.lower()
        
        if self._is_coding_request(text):
            workflow.append(self.registry.get("brainstorming"))
            workflow.append(self.registry.get("writing-plans"))
            workflow.append(self.registry.get("test-driven-development"))
            workflow.append(self.registry.get("subagent-driven-development"))
            workflow.append(self.registry.get("requesting-code-review"))
        
        if self._is_debugging_request(text):
            workflow.append(self.registry.get("systematic-debugging"))
            workflow.append(self.registry.get("verification-before-completion"))
        
        return [s for s in workflow if s]
