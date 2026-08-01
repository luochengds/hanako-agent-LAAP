"""测试工程师数字生命体——负责测试分析与测试覆盖建议。

TestEngineerAgent 继承 CognitiveSandbox，特化角色为"test_engineer"，
专注于测试质量分析、覆盖率评估和测试用例建议。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from laap.sandbox._types import ProjectSnapshot, SandboxConfig, Suggestion
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.container import CognitiveSandbox
from laap.sandbox.skill_library import Skill, SkillLibrary


class TestEngineerAgent(CognitiveSandbox):
    """测试工程师数字生命体——负责测试分析与测试覆盖建议。

    继承 CognitiveSandbox，特化角色为"test_engineer"。

    核心职责：
    1. 分析测试覆盖率，识别未覆盖模块
    2. 检测 flaky 测试（不稳定的测试用例）
    3. 提出测试用例建议
    4. 监控测试质量趋势

    注册的技能：
    - "find_uncovered_paths" — 查找未覆盖路径
    - "suggest_test_cases" — 测试用例建议
    - "detect_flaky_tests" — flaky 测试检测

    用法：
        event_bus = ColonyEventBus()
        skill_lib = SkillLibrary()
        test_engineer = TestEngineerAgent(
            sandbox_id="sb-test-engineer-001",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        snapshot = perception.perceive(full=True)
        test_engineer.perceive(snapshot)
        suggestion = test_engineer.think()
    """

    def __init__(self, sandbox_id: str, skill_library: SkillLibrary,
                 event_bus: ColonyEventBus, config: Optional[SandboxConfig] = None):
        """
        Args:
            sandbox_id: 沙箱唯一标识
            skill_library: 技能库（共享只读引用）
            event_bus: 事件总线
            config: 可选的资源限制配置
        """
        super().__init__(
            sandbox_id=sandbox_id,
            name="TestEngineer",
            role="test_engineer",
            skill_library=skill_library,
            event_bus=event_bus,
            config=config,
        )

        self._register_test_skills()

    def _register_test_skills(self) -> None:
        """注册测试工程师特有的技能到 skill_library。"""
        test_skills = [
            Skill(
                name="find_uncovered_paths",
                description="识别未覆盖的代码路径",
                category="test",
                tags=["test_engineer"],
            ),
            Skill(
                name="suggest_test_cases",
                description="建议新测试用例",
                category="test",
                tags=["test_engineer"],
            ),
            Skill(
                name="detect_flaky_tests",
                description="检测不稳定的测试",
                category="test",
                tags=["test_engineer"],
            ),
        ]
        for skill in test_skills:
            self.skill_library.register(skill)

    def think(self) -> Optional[Suggestion]:
        """测试工程师特化思考循环。

        基于 world_model 的项目状态，识别：
        1. 测试覆盖率盲区（未覆盖的模块）
        2. flaky 测试用例
        3. 缺失的测试用例
        4. 测试质量趋势

        返回：
            优先级最高的测试建议（或 None）
        """
        from laap.sandbox.resource_budget import DegradationLevel

        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        flaky_tests = self._detect_flaky_tests()
        uncovered_modules = self._find_uncovered_modules()

        critical_flaky = [t for t in flaky_tests if t.get('flakiness_score', 0) >= 0.7]
        if critical_flaky:
            worst = critical_flaky[0]
            return Suggestion(
                title=f"修复 Flaky 测试: {worst['test_name']}",
                description=f"检测到不稳定测试用例，失败率 {worst['flakiness_score']:.1%}。"
                           f"测试文件: {worst.get('file_path', 'unknown')}",
                priority="critical",
                relevance=0.9,
                category="test_gap",
                target_file=worst.get('file_path'),
                source_sandbox=self.sandbox_id,
                actions=["分析测试失败原因", "消除随机因素", "添加重试机制", "验证稳定性"],
            )

        low_coverage = [m for m in uncovered_modules if m.get('coverage_percent', 0) < 50]
        if low_coverage:
            worst = low_coverage[0]
            return Suggestion(
                title=f"补充测试覆盖: {worst['path']}",
                description=f"模块覆盖率仅 {worst['coverage_percent']:.0f}%，"
                           f"有 {worst.get('lines_uncovered', 0)} 行未覆盖代码。",
                priority="high",
                relevance=0.8,
                category="test_gap",
                target_file=worst['path'],
                source_sandbox=self.sandbox_id,
                actions=["分析未覆盖代码", "编写单元测试", "运行覆盖率报告", "验证提升"],
            )

        medium_coverage = [m for m in uncovered_modules if 50 <= m.get('coverage_percent', 0) < 80]
        if medium_coverage:
            worst = medium_coverage[0]
            return Suggestion(
                title=f"提升测试覆盖: {worst['path']}",
                description=f"模块覆盖率 {worst['coverage_percent']:.0f}%，建议提升至 80% 以上。",
                priority="medium",
                relevance=0.6,
                category="test_gap",
                target_file=worst['path'],
                source_sandbox=self.sandbox_id,
                actions=["分析薄弱环节", "补充边界测试", "优化测试策略"],
            )

        if uncovered_modules:
            return Suggestion(
                title=f"存在 {len(uncovered_modules)} 个未完全覆盖模块",
                description="建议检查并补充测试用例以提升整体覆盖率",
                priority="low",
                relevance=0.4,
                category="test_gap",
                source_sandbox=self.sandbox_id,
                actions=["生成覆盖率报告", "制定测试计划", "逐步补充"],
            )

        return None

    def _find_uncovered_modules(self) -> List[Dict[str, Any]]:
        """查找未覆盖的模块。

        分析 test_state 的覆盖率数据，找出覆盖率 < 80% 的模块。

        返回：[{path, coverage_percent, lines_uncovered}, ...]
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return []

        uncovered = []

        if snapshot.test_state.coverage_percent is not None:
            for file_path in snapshot.file_tree.file_paths:
                if file_path.endswith('.py') and not file_path.startswith('test_'):
                    if 'test' not in file_path.lower():
                        coverage_pct = self._estimate_file_coverage(file_path, snapshot)
                        has_test = self._has_corresponding_test(file_path, snapshot)
                        if coverage_pct < 80:
                            uncovered.append({
                                'path': file_path,
                                'coverage_percent': coverage_pct,
                                'lines_uncovered': self._estimate_uncovered_lines(file_path, snapshot),
                            })
                        elif not has_test:
                            uncovered.append({
                                'path': file_path,
                                'coverage_percent': coverage_pct - 5,
                                'lines_uncovered': self._estimate_uncovered_lines(file_path, snapshot),
                            })
        else:
            for file_path in snapshot.file_tree.file_paths:
                if file_path.endswith('.py') and not file_path.startswith('test_'):
                    if 'test' not in file_path.lower():
                        has_test = self._has_corresponding_test(file_path, snapshot)
                        if not has_test:
                            uncovered.append({
                                'path': file_path,
                                'coverage_percent': 0,
                                'lines_uncovered': self._estimate_uncovered_lines(file_path, snapshot),
                            })

        uncovered.sort(key=lambda x: x['coverage_percent'])
        return uncovered

    def _estimate_file_coverage(self, file_path: str, snapshot: ProjectSnapshot) -> float:
        """估算文件覆盖率（简化实现）。"""
        if snapshot.test_state.coverage_percent is not None:
            base_coverage = snapshot.test_state.coverage_percent
            if file_path.startswith('tests/') or '/tests/' in file_path:
                return 100.0
            return base_coverage
        return 0.0

    def _estimate_uncovered_lines(self, file_path: str, snapshot: ProjectSnapshot) -> int:
        """估算未覆盖行数（简化实现）。"""
        if snapshot.file_tree.largest_files:
            for f in snapshot.file_tree.largest_files:
                if f.get('path') == file_path:
                    lines = f.get('lines', 100)
                    coverage = self._estimate_file_coverage(file_path, snapshot)
                    return int(lines * (1 - coverage / 100))
        return 50

    def _has_corresponding_test(self, file_path: str, snapshot: ProjectSnapshot) -> bool:
        """检查是否存在对应测试文件。"""
        test_name = 'test_' + os.path.basename(file_path)
        return any(test_name in f for f in snapshot.file_tree.file_paths)

    def _detect_flaky_tests(self) -> List[Dict[str, Any]]:
        """检测 flaky 测试。

        基于测试运行历史，识别不稳定的测试用例（时过时而失败）。

        返回：[{test_name, file_path, flakiness_score}, ...]
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return []

        flaky_tests = []

        for failure in snapshot.test_state.recent_failures:
            test_name = failure.get('test_name', '')
            file_path = failure.get('file_path', '')

            flakiness_score = self._calculate_flakiness_score(test_name, failure)
            if flakiness_score > 0.3:
                flaky_tests.append({
                    'test_name': test_name,
                    'file_path': file_path,
                    'flakiness_score': flakiness_score,
                })

        flaky_tests.sort(key=lambda x: -x['flakiness_score'])
        return flaky_tests

    def _calculate_flakiness_score(self, test_name: str, failure: Dict[str, Any]) -> float:
        """计算 flakiness 分数（简化实现）。"""
        score = 0.0

        if 'random' in test_name.lower():
            score += 0.3
        if 'timing' in test_name.lower():
            score += 0.3
        if 'timeout' in test_name.lower():
            score += 0.2
        if 'network' in test_name.lower():
            score += 0.2

        if failure.get('retries', 0) > 0:
            score += 0.3

        if failure.get('occurred_multiple_times', False):
            score += 0.2

        return min(1.0, score)

    def _extract_test_names(self, file_path: str) -> List[str]:
        """从测试文件中提取测试名称（简化实现）。"""
        patterns = ['random', 'timing', 'timeout', 'network', 'concurrent']
        names = []
        for pattern in patterns:
            names.append(f'test_{pattern}_scenario')
            names.append(f'test_{pattern}_edge_case')
        return names

    def _is_potentially_flaky(self, test_name: str) -> bool:
        """判断测试是否可能是 flaky 的。"""
        flaky_patterns = ['random', 'timing', 'timeout', 'network', 'concurrent', 'async']
        return any(pattern in test_name.lower() for pattern in flaky_patterns)

    def _suggest_test_cases(self, uncovered_module: Dict[str, Any]) -> List[Suggestion]:
        """为未覆盖模块生成测试用例建议。"""
        suggestions = []
        module_path = uncovered_module['path']
        coverage_pct = uncovered_module['coverage_percent']

        functions = self._extract_functions_from_path(module_path)

        for func in functions:
            suggestions.append(Suggestion(
                title=f"为 {func} 添加测试用例",
                description=f"模块 {module_path} 中的函数 {func} 未被测试覆盖",
                priority="medium",
                relevance=0.7,
                category="test_gap",
                target_file=module_path,
                source_sandbox=self.sandbox_id,
                actions=[
                    f"编写 test_{func} 测试用例",
                    "覆盖正常路径",
                    "覆盖边界条件",
                    "覆盖异常场景",
                ],
            ))

        if coverage_pct < 30:
            suggestions.append(Suggestion(
                title=f"为 {module_path} 添加全面测试",
                description=f"模块覆盖率仅 {coverage_pct:.0f}%，建议进行全面测试",
                priority="high",
                relevance=0.85,
                category="test_gap",
                target_file=module_path,
                source_sandbox=self.sandbox_id,
                actions=[
                    "分析模块功能",
                    "设计测试用例矩阵",
                    "实现单元测试",
                    "运行并验证",
                ],
            ))

        return suggestions

    def _extract_functions_from_path(self, module_path: str) -> List[str]:
        """从模块路径提取函数名称（简化实现）。"""
        module_name = os.path.basename(module_path).replace('.py', '')
        public_funcs = [
            f'{module_name}_init',
            f'{module_name}_process',
            f'{module_name}_validate',
            f'{module_name}_compute',
        ]
        return public_funcs

    def analyze_test_quality(self) -> Dict[str, Any]:
        """分析测试质量。

        返回：{
            "total_test_cases": int,
            "pass_rate": float,
            "coverage_percent": float,
            "uncovered_modules": [...],
            "flaky_tests": [...],
            "test_quality": str,  # excellent / good / fair / poor
        }
        """
        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return {
                "total_test_cases": 0,
                "pass_rate": 0.0,
                "coverage_percent": 0.0,
                "uncovered_modules": [],
                "flaky_tests": [],
                "test_quality": "poor",
            }

        test_state = snapshot.test_state
        total_cases = test_state.total_cases
        passed = test_state.passed
        coverage = test_state.coverage_percent or 0.0

        pass_rate = (passed / total_cases * 100) if total_cases > 0 else 0.0
        uncovered_modules = self._find_uncovered_modules()
        flaky_tests = self._detect_flaky_tests()

        if coverage >= 90 and pass_rate >= 95 and len(flaky_tests) == 0:
            test_quality = "excellent"
        elif coverage >= 80 and pass_rate >= 85 and len(flaky_tests) <= 2:
            test_quality = "good"
        elif coverage >= 60 and pass_rate >= 70 and len(flaky_tests) <= 5:
            test_quality = "fair"
        else:
            test_quality = "poor"

        return {
            "total_test_cases": total_cases,
            "pass_rate": pass_rate,
            "coverage_percent": coverage,
            "uncovered_modules": uncovered_modules,
            "flaky_tests": flaky_tests,
            "test_quality": test_quality,
        }


__all__ = ["TestEngineerAgent"]