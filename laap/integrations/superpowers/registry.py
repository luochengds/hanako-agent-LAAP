"""SuperpowerSkillRegistry — Superpowers技能注册表与激活管理"""
from __future__ import annotations
import json, logging, os, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("integrations.superpowers.registry")

class ActivationTrigger(str, Enum):
    BEFORE_CODE = "before_code"          # brainstorming
    BEFORE_PLAN = "before_plan"          # writing-plans
    WHEN_PLAN_READY = "when_plan_ready"  # subagent-driven-development / executing-plans
    BEFORE_COMMIT = "before_commit"      # requesting-code-review
    AFTER_REVIEW = "after_review"        # receiving-code-review
    WHILE_DEBUGGING = "while_debugging"  # systematic-debugging
    BEFORE_BRANCH = "before_branch"      # using-git-worktrees
    BEFORE_MERGE = "before_merge"        # finishing-a-development-branch
    DURING_TEST = "during_test"          # test-driven-development
    VERIFY_BEFORE_DONE = "verify_before_done" # verification-before-completion
    DISPATCH_WORK = "dispatch_work"      # dispatching-parallel-agents
    META = "meta"                        # writing-skills, using-superpowers

@dataclass
class SuperpowerSkill:
    name: str = ""
    trigger: ActivationTrigger = ActivationTrigger.META
    priority: int = 0  # higher = runs first
    description: str = ""
    instructions_path: str = ""
    active: bool = True
    is_mandatory: bool = False

class SuperpowerSkillRegistry:
    """Superpowers技能注册表 — 管理所有技能和激活规则"""
    
    SKILLS = [
        SuperpowerSkill("brainstorming", ActivationTrigger.BEFORE_CODE, 10,
                       "Refine rough ideas through Socratic questions before coding"),
        SuperpowerSkill("writing-plans", ActivationTrigger.BEFORE_PLAN, 9,
                       "Break work into bite-sized tasks with exact file paths"),
        SuperpowerSkill("subagent-driven-development", ActivationTrigger.WHEN_PLAN_READY, 8,
                       "Dispatch subagents per task with two-stage review"),
        SuperpowerSkill("executing-plans", ActivationTrigger.WHEN_PLAN_READY, 7,
                       "Batch execution with human checkpoints"),
        SuperpowerSkill("test-driven-development", ActivationTrigger.DURING_TEST, 10,
                       "RED-GREEN-REFACTOR: write failing test first", is_mandatory=True),
        SuperpowerSkill("requesting-code-review", ActivationTrigger.BEFORE_COMMIT, 8,
                       "Pre-review checklist against plan", is_mandatory=True),
        SuperpowerSkill("receiving-code-review", ActivationTrigger.AFTER_REVIEW, 6,
                       "Responding to feedback systematically"),
        SuperpowerSkill("systematic-debugging", ActivationTrigger.WHILE_DEBUGGING, 9,
                       "4-phase root cause debugging", is_mandatory=True),
        SuperpowerSkill("verification-before-completion", ActivationTrigger.VERIFY_BEFORE_DONE, 10,
                       "Ensure it's actually fixed", is_mandatory=True),
        SuperpowerSkill("using-git-worktrees", ActivationTrigger.BEFORE_BRANCH, 7,
                       "Isolated development branches for context isolation"),
        SuperpowerSkill("finishing-a-development-branch", ActivationTrigger.BEFORE_MERGE, 8,
                       "Merge/PR decision workflow"),
        SuperpowerSkill("dispatching-parallel-agents", ActivationTrigger.DISPATCH_WORK, 5,
                       "Concurrent subagent workflows"),
        SuperpowerSkill("writing-skills", ActivationTrigger.META, 0,
                       "Create new skills following best practices"),
        SuperpowerSkill("using-superpowers", ActivationTrigger.META, 0,
                       "Introduction to the skills system"),
    ]
    
    def __init__(self, base_path: str = ""):
        self.base_path = base_path or os.path.join(os.path.dirname(__file__))
        self._skills: Dict[str, SuperpowerSkill] = {s.name: s for s in self.SKILLS}
    
    def get(self, name: str) -> Optional[SuperpowerSkill]:
        return self._skills.get(name)
    
    def find_by_trigger(self, trigger: ActivationTrigger) -> List[SuperpowerSkill]:
        return sorted([s for s in self._skills.values() if s.trigger == trigger and s.active],
                     key=lambda x: -x.priority)
    
    def get_instructions(self, name: str) -> str:
        path = os.path.join(self.base_path, name, "SKILL.md")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return f"# {name}\n\nNo instructions found."
    
    def activate(self, trigger: ActivationTrigger) -> List[dict]:
        skills = self.find_by_trigger(trigger)
        return [{"name": s.name, "description": s.description, "instructions": self.get_instructions(s.name)[:500],
                 "mandatory": s.is_mandatory} for s in skills]
    
    def get_all(self) -> List[dict]:
        return [{"name": s.name, "trigger": s.trigger.value, "priority": s.priority,
                 "desc": s.description, "mandatory": s.is_mandatory} for s in self._skills.values()]
    
    def get_stats(self) -> dict:
        return {"total": len(self._skills), "active": sum(1 for s in self._skills.values() if s.active),
                "mandatory": sum(1 for s in self._skills.values() if s.is_mandatory)}
