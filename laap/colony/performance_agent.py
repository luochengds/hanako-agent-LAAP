"""性能分析数字生命体——负责系统性能监控、瓶颈分析及优化建议。

PerformanceAgent 继承 CognitiveSandbox，特化角色为"performance_watcher"，
专注于静态性能分析（N+1 查询、嵌套循环、大对象分配）、
复杂度评估（时间/空间复杂度估算）以及瓶颈检测与优化建议。
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any, Dict, List, Optional

from laap.sandbox._types import ProjectSnapshot, SandboxConfig, Suggestion
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.container import CognitiveSandbox
from laap.sandbox.skill_library import Skill, SkillLibrary


# 数据库/ORM 调用模式（用于 N+1 查询识别）
# 注：此处存储的是属性名（不带前导点），与 ast.Attribute.attr 对齐
_DB_CALL_PATTERNS = {
    "query", "filter", "filter_by", "all", "execute",
    "fetchone", "fetchall", "first", "get", "one",
}


class PerformanceAgent(CognitiveSandbox):
    """性能分析数字生命体——负责系统性能监控、瓶颈分析及优化建议。

    继承 CognitiveSandbox，特化角色为"performance_watcher"。

    核心职责：
    1. 静态性能分析（N+1 查询、嵌套循环 O(n²)、大对象分配）
    2. 复杂度估算（时间复杂度与空间复杂度）
    3. 瓶颈检测与优化建议
    4. 监控性能趋势

    注册的技能：
    - "perf_analyze" — 性能分析
    - "bottleneck_detect" — 瓶颈检测
    - "optimize_suggest" — 优化建议

    用法：
        event_bus = ColonyEventBus()
        skill_lib = SkillLibrary()
        perf_agent = PerformanceAgent(
            sandbox_id="sb-perf-001",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        snapshot = perception.perceive(full=True)
        perf_agent.perceive(snapshot)
        suggestion = perf_agent.think()
    """

    AGENT_ID = "perf-agent"
    ROLE = "performance_watcher"

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
            name="PerformanceAgent",
            role=self.ROLE,
            skill_library=skill_library,
            event_bus=event_bus,
            config=config,
        )

        # 类标识（与文档接口对齐）
        self.agent_id = self.AGENT_ID
        self.skills = ["perf_analyze", "bottleneck_detect", "optimize_suggest"]

        self._register_performance_skills()

    def _register_performance_skills(self) -> None:
        """注册性能分析特有的技能到 skill_library。"""
        perf_skills = [
            Skill(
                name="perf_analyze",
                description="静态性能分析，识别 N+1 查询、嵌套循环与大对象分配",
                category="analysis",
                tags=["performance_watcher", "static-analysis"],
            ),
            Skill(
                name="bottleneck_detect",
                description="基于分析结果检测性能瓶颈",
                category="analysis",
                tags=["performance_watcher", "bottleneck"],
            ),
            Skill(
                name="optimize_suggest",
                description="为性能瓶颈提供优化建议",
                category="refactor",
                tags=["performance_watcher", "optimization"],
            ),
        ]
        for skill in perf_skills:
            self.skill_library.register(skill)

    # ------------------------------------------------------------
    # 认知循环
    # ------------------------------------------------------------

    def think(self) -> Optional[Suggestion]:
        """性能分析特化思考循环。

        基于 world_model 中的项目快照，识别：
        1. N+1 查询模式
        2. 嵌套循环导致的 O(n²) 复杂度
        3. 大对象分配
        4. 整体性能瓶颈

        返回：
            优先级最高的性能优化建议（或 None）
        """
        from laap.sandbox.resource_budget import DegradationLevel

        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        file_contents = self._collect_source_files(snapshot)
        if not file_contents:
            return None

        static_issues = self.analyze_static(file_contents)
        complexity_issues = self.analyze_complexity(file_contents)
        all_issues = static_issues + complexity_issues
        bottlenecks = self.detect_bottlenecks(all_issues)

        if not bottlenecks:
            return None

        # 取估算改进最大的瓶颈
        worst = bottlenecks[0]
        impact = worst.get('estimated_improvement', '0%')
        impact_value = self._parse_improvement_value(impact)

        if impact_value >= 30:
            priority = "high"
            relevance = 0.85
        elif impact_value >= 15:
            priority = "medium"
            relevance = 0.7
        else:
            priority = "low"
            relevance = 0.5

        return Suggestion(
            title=f"优化性能瓶颈: {worst['type']}（{worst.get('file', 'unknown')}）",
            description=f"检测到性能瓶颈类型: {worst['type']}，"
                       f"预计优化可提升约 {impact}。{worst.get('description', '')}",
            priority=priority,
            relevance=relevance,
            category="refactor",
            target_file=worst.get('file'),
            source_sandbox=self.sandbox_id,
            actions=self._suggest_optimization_actions(worst),
        )

    # ------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------

    def analyze_static(self, file_contents: Dict[str, str]) -> List[Dict[str, Any]]:
        """静态性能分析。

        检测以下模式：
        - N+1 查询：循环内执行数据库/ORM 调用
        - 循环嵌套（O(n²) 以上）
        - 大对象分配：list(range(...)) 等大列表构造

        Args:
            file_contents: 文件路径到内容的映射

        返回:
            [{"type": "n_plus_1", "file": "...", "line": 42,
              "impact": "high", "description": "..."}]
        """
        results: List[Dict[str, Any]] = []

        for file_path, content in file_contents.items():
            if not file_path.endswith('.py'):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            # 1. N+1 查询检测：循环内有数据库调用
            for node in ast.walk(tree):
                if isinstance(node, (ast.For, ast.While)):
                    if self._contains_db_call(node):
                        results.append({
                            "type": "n_plus_1",
                            "file": file_path,
                            "line": getattr(node, 'lineno', 0),
                            "impact": "high",
                            "description": "循环内存在数据库/ORM 调用，可能引发 N+1 查询",
                        })

            # 2. 嵌套循环 O(n²) 检测
            results.extend(self._detect_nested_loops(tree, file_path))

            # 3. 大对象分配检测
            results.extend(self._detect_large_allocation(tree, file_path))

        # 按 impact 排序
        impact_order = {"high": 0, "medium": 1, "low": 2}
        results.sort(key=lambda r: impact_order.get(r.get('impact', 'low'), 99))
        return results

    def analyze_complexity(self, file_contents: Dict[str, str]) -> List[Dict[str, Any]]:
        """复杂度分析。

        估算每个函数的时间与空间复杂度。

        Args:
            file_contents: 文件路径到内容的映射

        返回:
            [{"file": "...", "function": "...", "time_complexity": "O(n²)",
              "space_complexity": "O(n)"}]
        """
        results: List[Dict[str, Any]] = []

        for file_path, content in file_contents.items():
            if not file_path.endswith('.py'):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                func_name = node.name
                if func_name.startswith('_'):
                    continue
                time_c, space_c = self._estimate_function_complexity(node)
                results.append({
                    "file": file_path,
                    "function": func_name,
                    "line": getattr(node, 'lineno', 0),
                    "time_complexity": time_c,
                    "space_complexity": space_c,
                })

        # 优先展示复杂度高的函数
        complexity_rank = {"O(2^n)": 0, "O(n²)": 1, "O(n log n)": 2,
                           "O(n)": 3, "O(log n)": 4, "O(1)": 5}
        results.sort(key=lambda r: complexity_rank.get(r['time_complexity'], 99))
        return results

    def detect_bottlenecks(self, analysis_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """瓶颈检测。

        基于静态分析与复杂度分析结果识别性能瓶颈。

        Args:
            analysis_results: analyze_static 与 analyze_complexity 的合并结果

        返回:
            [{"type": "hotspot", "file": "...", "description": "...",
              "estimated_improvement": "30%"}]
        """
        bottlenecks: List[Dict[str, Any]] = []

        # N+1 查询瓶颈（通常可大幅改进）
        n_plus_1 = [r for r in analysis_results if r.get('type') == 'n_plus_1']
        for issue in n_plus_1:
            bottlenecks.append({
                "type": "n_plus_1_query",
                "file": issue.get('file', 'unknown'),
                "line": issue.get('line'),
                "description": "循环内执行数据库查询，建议改用批量查询或预加载",
                "estimated_improvement": "60%",
            })

        # 嵌套循环瓶颈
        nested_loops = [r for r in analysis_results if r.get('type') == 'nested_loop']
        for issue in nested_loops:
            improvement = "40%" if issue.get('impact') == 'high' else "20%"
            bottlenecks.append({
                "type": "nested_loop",
                "file": issue.get('file', 'unknown'),
                "line": issue.get('line'),
                "description": "嵌套循环导致 O(n²) 或更高复杂度，建议优化算法或使用更高效数据结构",
                "estimated_improvement": improvement,
            })

        # 大对象分配瓶颈
        large_alloc = [r for r in analysis_results if r.get('type') == 'large_allocation']
        for issue in large_alloc:
            bottlenecks.append({
                "type": "large_allocation",
                "file": issue.get('file', 'unknown'),
                "line": issue.get('line'),
                "description": "检测到大对象分配，建议使用生成器或分批处理",
                "estimated_improvement": "25%",
            })

        # 高复杂度函数瓶颈
        high_complexity = [
            r for r in analysis_results
            if r.get('time_complexity') in ("O(n²)", "O(2^n)")
        ]
        for issue in high_complexity:
            improvement = "50%" if issue.get('time_complexity') == "O(2^n)" else "35%"
            bottlenecks.append({
                "type": "high_complexity_function",
                "file": issue.get('file', 'unknown'),
                "function": issue.get('function'),
                "line": issue.get('line'),
                "description": f"函数 {issue.get('function')} 的时间复杂度为 {issue.get('time_complexity')}",
                "estimated_improvement": improvement,
            })

        # 按估算改进幅度排序
        bottlenecks.sort(
            key=lambda b: self._parse_improvement_value(b.get('estimated_improvement', '0%')),
            reverse=True,
        )
        return bottlenecks

    # ------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------

    def _collect_source_files(self, snapshot: ProjectSnapshot) -> Dict[str, str]:
        """收集快照中所有 Python 源码文件的内容。"""
        file_contents: Dict[str, str] = {}
        for file_path in snapshot.file_tree.file_paths:
            if not file_path.endswith('.py'):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    file_contents[file_path] = f.read()
            except (OSError, UnicodeDecodeError):
                continue
        return file_contents

    @staticmethod
    def _contains_db_call(loop_node: ast.AST) -> bool:
        """判断循环内是否包含数据库/ORM 调用（N+1 查询模式）。"""
        # 直接遍历循环体，避免误判外层循环中的循环
        for child in ast.iter_child_nodes(loop_node):
            # 进入循环体或条件分支
            if isinstance(child, (ast.For, ast.While, ast.If, ast.Try, ast.With)):
                if PerformanceAgent._contains_db_call(child):
                    return True
                continue
            # 检查调用表达式
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                if PerformanceAgent._is_db_call_expr(child.value):
                    return True
            # 赋值语句中的调用
            if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call):
                if PerformanceAgent._is_db_call_expr(child.value):
                    return True
            # 赋值表达式
            if isinstance(child, ast.AugAssign) and isinstance(child.value, ast.Call):
                if PerformanceAgent._is_db_call_expr(child.value):
                    return True
        return False

    @staticmethod
    def _is_db_call_expr(call_node: ast.Call) -> bool:
        """判断调用表达式是否为数据库/ORM 调用。"""
        func = call_node.func
        # 形如 obj.query() / obj.filter(...) 等
        if isinstance(func, ast.Attribute):
            attr_name = func.attr
            if attr_name in _DB_CALL_PATTERNS:
                return True
            # 嵌套调用：session.query(...).all() 等
            inner = func.value
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                if inner.func.attr in _DB_CALL_PATTERNS:
                    return True
        return False

    @staticmethod
    def _detect_nested_loops(tree: ast.AST, file_path: str) -> List[Dict[str, Any]]:
        """检测嵌套循环（O(n²) 及以上）。"""
        results: List[Dict[str, Any]] = []

        def visit(node: ast.AST, depth: int = 0, parent_lineno: int = 0) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.For, ast.While)):
                    new_depth = depth + 1
                    if new_depth >= 2:
                        # 嵌套深度 >= 2 即视为 O(n²)
                        impact = "high" if new_depth >= 3 else "medium"
                        results.append({
                            "type": "nested_loop",
                            "file": file_path,
                            "line": getattr(child, 'lineno', parent_lineno),
                            "impact": impact,
                            "depth": new_depth,
                            "description": f"嵌套循环深度 {new_depth}，复杂度约 O(n^{new_depth})",
                        })
                    visit(child, new_depth, getattr(child, 'lineno', parent_lineno))
                else:
                    # 仅在控制流节点内继续向下查找循环
                    if isinstance(child, (ast.If, ast.Try, ast.With, ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        visit(child, depth, getattr(child, 'lineno', parent_lineno))

        visit(tree)
        return results

    @staticmethod
    def _detect_large_allocation(tree: ast.AST, file_path: str) -> List[Dict[str, Any]]:
        """检测大对象分配（如 list(range(10000))）。"""
        results: List[Dict[str, Any]] = []

        for node in ast.walk(tree):
            # list(range(N)) / set(range(N)) 等大列表构造
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("list", "set", "dict"):
                    if node.args and isinstance(node.args[0], ast.Call):
                        inner = node.args[0]
                        if isinstance(inner.func, ast.Name) and inner.func.id == "range":
                            # 提取 range 参数判断是否较大
                            magnitude = PerformanceAgent._estimate_range_magnitude(inner)
                            if magnitude >= 1000:
                                results.append({
                                    "type": "large_allocation",
                                    "file": file_path,
                                    "line": getattr(node, 'lineno', 0),
                                    "impact": "medium",
                                    "description": f"一次性构造大小约 {magnitude} 的集合，可能造成内存压力",
                                })

            # 列表/字典/集合推导式（如果出现在循环中也视为潜在大对象分配）
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                # 仅当存在多层 for 时视为大对象分配
                for_count = sum(1 for g in node.generators for _ in [g.iter])
                if for_count >= 2:
                    results.append({
                        "type": "large_allocation",
                        "file": file_path,
                        "line": getattr(node, 'lineno', 0),
                        "impact": "low",
                        "description": "嵌套推导式可能在循环中产生大对象，建议评估必要性",
                    })

        return results

    @staticmethod
    def _estimate_range_magnitude(range_call: ast.Call) -> int:
        """估算 range() 调用的数量级。"""
        args = range_call.args
        if not args:
            return 0
        # 仅支持字面量参数的简化估算
        last_arg = args[-1]
        if isinstance(last_arg, ast.Constant) and isinstance(last_arg.value, int):
            return max(0, last_arg.value)
        if len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, int):
            return max(0, args[1].value)
        # 无法解析则视为可能较大
        return 10000

    @staticmethod
    def _estimate_function_complexity(func_node: ast.AST) -> tuple:
        """估算函数的时间与空间复杂度。"""
        # 统计循环深度
        max_loop_depth = 0

        def visit(node: ast.AST, depth: int) -> int:
            nonlocal max_loop_depth
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.For, ast.While)):
                    new_depth = depth + 1
                    if new_depth > max_loop_depth:
                        max_loop_depth = new_depth
                    visit(child, new_depth)
                else:
                    if isinstance(child, (ast.If, ast.Try, ast.With)):
                        visit(child, depth)
        visit(func_node, 0)

        # 时间复杂度推断
        if max_loop_depth >= 3:
            time_c = "O(n³)"
        elif max_loop_depth == 2:
            time_c = "O(n²)"
        elif max_loop_depth == 1:
            # 检查是否包含对数操作（如二分查找）
            time_c = "O(n)"
        else:
            time_c = "O(1)"

        # 空间复杂度推断：检查列表/字典推导式与显式集合构造
        space_c = "O(1)"
        for node in ast.walk(func_node):
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
                space_c = "O(n)"
                break
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("list", "set", "dict", "sorted"):
                    space_c = "O(n)"
                    break

        return time_c, space_c

    @staticmethod
    def _parse_improvement_value(value: str) -> int:
        """从 "30%" 之类的字符串中提取数值部分。"""
        match = re.search(r'(\d+)', str(value))
        return int(match.group(1)) if match else 0

    @staticmethod
    def _suggest_optimization_actions(bottleneck: Dict[str, Any]) -> List[str]:
        """为瓶颈生成具体的优化动作建议。"""
        btype = bottleneck.get('type', '')
        actions: List[str] = []
        if btype == 'n_plus_1_query':
            actions = [
                "将循环内查询改为批量查询",
                "使用 ORM 预加载（selectinload/joinedload）",
                "缓存重复查询结果",
            ]
        elif btype == 'nested_loop':
            actions = [
                "评估是否可使用哈希表/集合将 O(n²) 降至 O(n)",
                "合并循环以减少遍历次数",
                "考虑更高效的算法",
            ]
        elif btype == 'large_allocation':
            actions = [
                "使用生成器替代列表",
                "分批处理大数据",
                "评估内存使用情况",
            ]
        elif btype == 'high_complexity_function':
            actions = [
                f"重构函数 {bottleneck.get('function', '')} 以降低复杂度",
                "拆分为多个低复杂度函数",
                "使用空间换时间策略（如缓存/查表）",
            ]
        else:
            actions = ["审查代码", "评估性能影响", "应用优化"]
        return actions


__all__ = ["PerformanceAgent"]
