from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Optional

from laap.sandbox._types import (
    ProjectSnapshot,
    SandboxConfig,
    Suggestion,
)
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.container import CognitiveSandbox
from laap.sandbox.resource_budget import DegradationLevel
from laap.sandbox.skill_library import Skill, SkillLibrary


class ArchitectAgent(CognitiveSandbox):
    """架构师数字生命体——负责项目架构分析与重构建议。
    
    继承 CognitiveSandbox，特化角色为"architect"。
    
    核心职责：
    1. 分析项目依赖结构，识别循环依赖
    2. 检测过度复杂模块（代码行数 + 技术债密度）
    3. 提出架构重构建议
    4. 监控架构风险趋势
    
    注册的技能：
    - "analyze_dependencies" — 依赖分析
    - "detect_circular_imports" — 循环依赖检测
    - "suggest_refactor" — 重构建议
    
    用法：
        event_bus = ColonyEventBus()
        skill_lib = SkillLibrary()
        architect = ArchitectAgent(
            sandbox_id="sb-architect-001",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        snapshot = perception.perceive(full=True)
        architect.perceive(snapshot)
        suggestion = architect.think()
    """

    def __init__(self, sandbox_id: str, skill_library: SkillLibrary,
                 event_bus: ColonyEventBus, config: Optional[SandboxConfig] = None):
        super().__init__(
            sandbox_id=sandbox_id,
            name="Architect",
            role="architect",
            skill_library=skill_library,
            event_bus=event_bus,
            config=config,
        )

        self._register_architect_skills()

    def _register_architect_skills(self) -> None:
        """注册架构师特有的技能到 skill_library。"""
        architect_skills = [
            Skill(
                name="analyze_dependencies",
                description="分析项目依赖关系图",
                category="analysis",
                tags=["architect", "deps"],
            ),
            Skill(
                name="detect_circular_imports",
                description="检测循环导入",
                category="analysis",
                tags=["architect", "imports"],
            ),
            Skill(
                name="suggest_refactor",
                description="建议重构方案",
                category="refactor",
                tags=["architect"],
            ),
        ]
        for skill in architect_skills:
            self.skill_library.register(skill)

    def think(self) -> Optional[Suggestion]:
        """架构师特化思考循环。
        
        基于 world_model 的项目状态，识别：
        1. 循环依赖
        2. 过度复杂模块（Top-5）
        3. 技术债热点（Top-5）
        4. 架构风险趋势
        
        返回：
            优先级最高的重构建议（或 None）
        """
        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        circular_deps = self._detect_circular_dependencies()
        complexity_hotspots = self._identify_complexity_hotspots()

        if circular_deps:
            dep = circular_deps[0]
            suggestion = Suggestion(
                title=f"修复循环依赖: {dep['module_a']} <-> {dep['module_b']}",
                description=f"检测到循环依赖: {dep['path_a']} 和 {dep['path_b']} 相互导入",
                priority="critical",
                relevance=0.9,
                category="refactor",
                target_file=dep['path_a'],
                source_sandbox=self.sandbox_id,
                actions=[
                    "提取公共模块消除循环",
                    "使用延迟导入",
                    "重构模块边界",
                ],
            )
            return suggestion

        if complexity_hotspots:
            hotspot = complexity_hotspots[0]
            return self._generate_refactor_suggestion(hotspot)

        return None

    def _detect_circular_dependencies(self) -> List[Dict[str, Any]]:
        """检测循环依赖。
        
        分析 file_tree 中的模块结构，识别循环导入。
        
        返回：[{module_a, module_b, path_a, path_b}, ...]
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return []

        result = []
        python_files = [f for f in snapshot.file_tree.file_paths if f.endswith('.py')]
        imports_map: Dict[str, List[str]] = {}

        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module.split('.')[0])

            module_name = os.path.basename(file_path)[:-3]
            imports_map[module_name] = imports

        for module_a, deps_a in imports_map.items():
            for module_b in deps_a:
                if module_b in imports_map and module_a in imports_map[module_b]:
                    path_a = next((f for f in python_files if f.endswith(f'{module_a}.py')), '')
                    path_b = next((f for f in python_files if f.endswith(f'{module_b}.py')), '')
                    if path_a and path_b and path_a != path_b:
                        exists = any(
                            (r['module_a'] == module_a and r['module_b'] == module_b) or
                            (r['module_a'] == module_b and r['module_b'] == module_a)
                            for r in result
                        )
                        if not exists:
                            result.append({
                                'module_a': module_a,
                                'module_b': module_b,
                                'path_a': path_a,
                                'path_b': path_b,
                            })

        return result

    def _identify_complexity_hotspots(self) -> List[Dict[str, Any]]:
        """识别复杂度热点。
        
        基于文件行数 + 技术债密度，输出 Top-5 热点。
        
        返回：[{path, lines, todo_density, score}, ...]
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return []

        hotspots = []
        file_paths = snapshot.file_tree.file_paths
        tech_debt_by_file = snapshot.tech_debt.by_file

        if not file_paths:
            return []

        total_lines = 0
        total_markers = 0
        valid_files = []

        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
                line_count = len(lines)
                markers = tech_debt_by_file.get(file_path, 0)
                valid_files.append((file_path, line_count, markers))
                total_lines += line_count
                total_markers += markers
            except (OSError, UnicodeDecodeError):
                continue

        if not valid_files:
            return []

        avg_lines = total_lines / len(valid_files)
        avg_markers = total_markers / len(valid_files) if total_markers > 0 else 1

        for file_path, line_count, markers in valid_files:
            if line_count == 0:
                continue
            todo_density = markers / line_count
            lines_score = (line_count / avg_lines) * 0.6
            density_score = (todo_density / avg_markers) * 0.4
            score = lines_score + density_score

            hotspots.append({
                'path': file_path,
                'lines': line_count,
                'todo_density': round(todo_density, 4),
                'score': round(score, 4),
            })

        hotspots.sort(key=lambda x: x['score'], reverse=True)
        return hotspots[:5]

    def _generate_refactor_suggestion(self, hotspot: Dict[str, Any]) -> Suggestion:
        """基于热点生成重构建议。"""
        score = hotspot['score']
        lines = hotspot['lines']
        density = hotspot['todo_density']

        if score > 3.0:
            priority = "high"
            relevance = 0.85
        elif score > 1.5:
            priority = "medium"
            relevance = 0.7
        else:
            priority = "low"
            relevance = 0.5

        actions = []
        if lines > 1000:
            actions.append("拆分为多个小模块")
        if density > 0.05:
            actions.append("清理技术债务标记")
        if not actions:
            actions = ["审查模块职责", "考虑重构"]

        return Suggestion(
            title=f"重构复杂模块: {os.path.basename(hotspot['path'])}",
            description=f"模块复杂度评分 {score:.2f}（行数: {lines}, TODO密度: {density:.2%}）",
            priority=priority,
            relevance=relevance,
            category="refactor",
            target_file=hotspot['path'],
            source_sandbox=self.sandbox_id,
            actions=actions,
        )

    def analyze_project_structure(self) -> Dict[str, Any]:
        """分析项目整体架构结构。
        
        返回：{
            "total_modules": int,
            "circular_dependencies": int,
            "complexity_hotspots": [...],
            "tech_debt_score": float,
            "architecture_health": str,  # healthy / warning / critical
        }
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return {
                "total_modules": 0,
                "circular_dependencies": 0,
                "complexity_hotspots": [],
                "tech_debt_score": 0.0,
                "architecture_health": "healthy",
            }

        python_files = [f for f in snapshot.file_tree.file_paths if f.endswith('.py')]
        circular_deps = self._detect_circular_dependencies()
        complexity_hotspots = self._identify_complexity_hotspots()
        tech_debt = snapshot.tech_debt

        tech_debt_score = min(tech_debt.total_markers / 100, 1.0) if tech_debt.total_markers > 0 else 0.0

        if len(circular_deps) > 0 or tech_debt_score > 0.8:
            architecture_health = "critical"
        elif len(circular_deps) == 0 and tech_debt_score > 0.4:
            architecture_health = "warning"
        else:
            architecture_health = "healthy"

        return {
            "total_modules": len(python_files),
            "circular_dependencies": len(circular_deps),
            "complexity_hotspots": complexity_hotspots,
            "tech_debt_score": round(tech_debt_score, 4),
            "architecture_health": architecture_health,
        }
