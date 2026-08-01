"""LAAP Sandbox 技能库

SkillLibrary 是全局只读技能库，所有 Cognitive Sandbox 共享引用。
使用单例模式确保一个进程内只有一个实例。
Skill 注册后即只读，sandbox 通过 lookup 查询技能。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.sandbox.skill_library")

__all__ = ["Skill", "SkillLibrary"]


@dataclass
class Skill:
    """可执行技能模板"""

    name: str  # 唯一名，如 "analyze_dependencies"
    description: str = ""
    category: str = ""  # analysis / refactor / test / doc / security
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)  # 依赖的工具/权限
    tags: List[str] = field(default_factory=list)
    # 可选的执行实现（函数引用）
    execute: Optional[callable] = None


# ── 默认技能执行实现 ──────────────────────────────────────────

def _exec_analyze_dependencies(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """分析项目依赖关系图（默认实现：返回可用性确认）"""
    return {"status": "available", "tool": "analyze_dependencies",
            "message": "分析项目依赖关系图 — 实现待加载"}

def _exec_detect_circular_imports(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "detect_circular_imports",
            "message": "检测循环导入 — 实现待加载"}

def _exec_suggest_refactor(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "suggest_refactor",
            "message": "建议重构方案 — 实现待加载"}

def _exec_find_uncovered_paths(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "find_uncovered_paths",
            "message": "查找未覆盖代码路径 — 实现待加载"}

def _exec_suggest_test_cases(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "suggest_test_cases",
            "message": "建议新测试用例 — 实现待加载"}

def _exec_detect_flaky_tests(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "detect_flaky_tests",
            "message": "检测不稳定测试 — 实现待加载"}

def _exec_generate_docstring(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "generate_docstring",
            "message": "生成文档字符串 — 实现待加载"}

def _exec_update_readme(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "update_readme",
            "message": "更新 README — 实现待加载"}

def _exec_scan_vulnerabilities(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "scan_vulnerabilities",
            "message": "扫描依赖漏洞 — 实现待加载"}

def _exec_check_secrets(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "available", "tool": "check_secrets",
            "message": "检查密钥泄漏 — 实现待加载"}

# 默认执行映射
_DEFAULT_EXECUTORS: Dict[str, Optional[callable]] = {
    "analyze_dependencies": _exec_analyze_dependencies,
    "detect_circular_imports": _exec_detect_circular_imports,
    "suggest_refactor": _exec_suggest_refactor,
    "find_uncovered_paths": _exec_find_uncovered_paths,
    "suggest_test_cases": _exec_suggest_test_cases,
    "detect_flaky_tests": _exec_detect_flaky_tests,
    "generate_docstring": _exec_generate_docstring,
    "update_readme": _exec_update_readme,
    "scan_vulnerabilities": _exec_scan_vulnerabilities,
    "check_secrets": _exec_check_secrets,
}


class SkillLibrary:
    """全局只读技能库——所有 sandbox 共享引用。

    使用单例模式（一个进程内只有一个实例）。
    Skill 注册后即只读，sandbox 通过 lookup 查询技能。
    """

    _instance: Optional["SkillLibrary"] = None
    _skills: Dict[str, Skill] = {}
    _initialized: bool = False

    def __new__(cls) -> "SkillLibrary":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._skills = {}
            self._register_defaults()
            self.__class__._initialized = True

    def register(self, skill: Skill) -> None:
        """注册新技能（仅首次注册有效，后续只读）"""
        if skill.name in self._skills:
            logger.debug(f"Skill '{skill.name}' already registered, skipped")
            return
        # 附加默认执行实现（如果未指定且存在默认）
        if skill.execute is None and skill.name in _DEFAULT_EXECUTORS:
            skill.execute = _DEFAULT_EXECUTORS[skill.name]
        self._skills[skill.name] = skill
        logger.debug(f"Skill registered: {skill.name} (executor={'yes' if skill.execute else 'no'})")

    def lookup(self, name: str) -> Optional[Skill]:
        """查询技能"""
        return self._skills.get(name)

    def execute_skill(self, name: str, inputs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """执行技能（如果可执行）。

        Args:
            name: 技能名称
            inputs: 技能输入参数

        Returns:
            执行结果字典，或 None（技能不存在 / 无可执行实现）
        """
        skill = self._skills.get(name)
        if not skill or not skill.execute:
            return None
        try:
            return skill.execute(inputs or {})
        except Exception as e:
            logger.error(f"Skill '{name}' execution failed: {e}")
            return {"status": "error", "tool": name, "error": str(e)}

    def list_skills(self, category: Optional[str] = None) -> List[Skill]:
        """列出所有技能，可按类别过滤"""
        if category is None:
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.category == category]

    def has(self, name: str) -> bool:
        return name in self._skills

    def _register_defaults(self) -> None:
        """注册内置默认技能"""
        defaults = [
            # 架构相关
            Skill(name="analyze_dependencies", description="分析项目依赖关系图",
                  category="analysis", tags=["architect", "deps"]),
            Skill(name="detect_circular_imports", description="检测循环导入",
                  category="analysis", tags=["architect", "imports"]),
            Skill(name="suggest_refactor", description="建议重构方案",
                  category="refactor", tags=["architect"]),
            # 测试相关
            Skill(name="find_uncovered_paths", description="识别未覆盖的代码路径",
                  category="test", tags=["test_engineer"]),
            Skill(name="suggest_test_cases", description="建议新测试用例",
                  category="test", tags=["test_engineer"]),
            Skill(name="detect_flaky_tests", description="检测不稳定的测试",
                  category="test", tags=["test_engineer"]),
            # 文档相关
            Skill(name="generate_docstring", description="生成函数/类的文档字符串",
                  category="doc", tags=["doc_maintainer"]),
            Skill(name="update_readme", description="更新 README 文档",
                  category="doc", tags=["doc_maintainer"]),
            # 安全相关
            Skill(name="scan_vulnerabilities", description="扫描依赖漏洞",
                  category="security", tags=["security_watcher"]),
            Skill(name="check_secrets", description="检查代码中的密钥泄漏",
                  category="security", tags=["security_watcher"]),
        ]
        for skill in defaults:
            self.register(skill)
