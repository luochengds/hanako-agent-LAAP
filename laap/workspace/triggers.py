"""触发器系统——事件匹配与建议生成

定义五个核心触发器：
- FileOpenTrigger — 文件打开事件
- BuildFailureTrigger — 构建失败事件
- IdleTrigger — 空闲事件
- CommitTrigger — 提交事件
- PeriodicTrigger — 定时周期事件

每个触发器负责：
1. 判断事件是否匹配（matches）
2. 基于项目快照生成建议（generate_suggestions）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from laap.sandbox._types import ProjectSnapshot, Suggestion, WorkspaceEvent


class Trigger(ABC):
    """触发器抽象基类。

    所有触发器必须实现：
    - `matches(event: WorkspaceEvent) -> bool` — 判断事件是否匹配
    - `generate_suggestions(snapshot: ProjectSnapshot, event: WorkspaceEvent) -> List[Suggestion]` — 生成建议

    Args:
        name: 触发器名称
        priority: 优先级（用于排序建议）
        enabled: 是否启用
    """

    def __init__(self, name: str, priority: int = 50, enabled: bool = True):
        self.name = name
        self.priority = priority
        self.enabled = enabled

    @abstractmethod
    def matches(self, event: WorkspaceEvent) -> bool:
        """判断事件是否匹配。"""

    @abstractmethod
    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        """生成建议列表。"""


class FileOpenTrigger(Trigger):
    """文件打开时触发。

    检查：
    - 该文件的历史 TODO 标记
    - 影响分析（该文件被哪些模块引用）
    - 技术债提醒

    建议类型：tech_debt、refactor
    """

    EVENT_TYPE = "file_open"

    def __init__(self, priority: int = 60, enabled: bool = True):
        super().__init__("FileOpenTrigger", priority, enabled)

    def matches(self, event: WorkspaceEvent) -> bool:
        if not self.enabled:
            return False
        return event.event_type == self.EVENT_TYPE

    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        suggestions: List[Suggestion] = []
        file_path = event.payload.get("file_path")

        if not file_path or not snapshot.tech_debt.by_file:
            return suggestions

        todo_count = snapshot.tech_debt.by_file.get(file_path, 0)
        if todo_count > 0:
            suggestions.append(Suggestion(
                title=f"该文件有 {todo_count} 个 TODO 标记待处理",
                description=f"文件 {file_path} 中发现 {todo_count} 个技术债标记，建议及时处理。",
                priority="high" if todo_count >= 5 else "medium",
                relevance=min(0.9, 0.5 + todo_count * 0.08),
                category="tech_debt",
                target_file=file_path,
                actions=[f"处理 {file_path} 中的 TODO 标记"],
            ))

        for hotspot in snapshot.tech_debt.hotspots:
            if hotspot.get("path") == file_path:
                density = hotspot.get("todo_density", 0)
                suggestions.append(Suggestion(
                    title=f"技术债热点文件",
                    description=f"文件 {file_path} 的 TODO 密度较高 ({density:.2f}/行)，建议重构。",
                    priority="medium",
                    relevance=min(0.8, density * 2),
                    category="refactor",
                    target_file=file_path,
                    actions=[f"重构 {file_path} 降低技术债密度"],
                ))
                break

        return suggestions


class BuildFailureTrigger(Trigger):
    """构建失败时触发。

    根因分析：
    - 检查错误日志中的关键词
    - 识别编译错误、依赖缺失、语法错误

    建议类型：bug、dependency
    """

    EVENT_TYPE = "build_failed"

    def __init__(self, priority: int = 90, enabled: bool = True):
        super().__init__("BuildFailureTrigger", priority, enabled)

    def matches(self, event: WorkspaceEvent) -> bool:
        if not self.enabled:
            return False
        return event.event_type == self.EVENT_TYPE

    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        suggestions: List[Suggestion] = []
        error_message = event.payload.get("error_message", "")

        if not error_message:
            return suggestions

        lower_error = error_message.lower()

        if any(kw in lower_error for kw in ["syntax error", "import error", "nameerror", "typeerror"]):
            suggestions.append(Suggestion(
                title="代码语法或类型错误",
                description=f"构建失败：检测到语法或类型错误。\n错误详情：{error_message[:200]}",
                priority="critical",
                relevance=0.95,
                category="bug",
                target_file=event.payload.get("file_path"),
                actions=["检查并修复代码语法错误"],
            ))

        if any(kw in lower_error for kw in ["no module named", "missing dependency", "dependency not found", "cannot import"]):
            suggestions.append(Suggestion(
                title="依赖缺失",
                description=f"构建失败：缺少依赖包。\n错误详情：{error_message[:200]}",
                priority="high",
                relevance=0.9,
                category="dependency",
                actions=["安装缺失的依赖包"],
            ))

        if any(kw in lower_error for kw in ["version conflict", "incompatible version", "requires python"]):
            suggestions.append(Suggestion(
                title="依赖版本冲突",
                description=f"构建失败：依赖版本不兼容。\n错误详情：{error_message[:200]}",
                priority="high",
                relevance=0.85,
                category="dependency",
                actions=["检查依赖版本并更新"],
            ))

        if not suggestions:
            suggestions.append(Suggestion(
                title="构建失败",
                description=f"构建失败，请检查错误日志。\n错误详情：{error_message[:200]}",
                priority="medium",
                relevance=0.7,
                category="bug",
                actions=["查看构建日志排查问题"],
            ))

        return suggestions


class IdleTrigger(Trigger):
    """空闲时触发（默认 5 分钟无操作）。

    周期性背景分析：
    - 技术债统计
    - 测试覆盖率分析
    - 依赖过期检查

    建议类型：tech_debt、dependency、test_gap
    """

    EVENT_TYPE = "idle"

    def __init__(self, priority: int = 40, enabled: bool = True):
        super().__init__("IdleTrigger", priority, enabled)

    def matches(self, event: WorkspaceEvent) -> bool:
        if not self.enabled:
            return False
        return event.event_type == self.EVENT_TYPE

    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        suggestions: List[Suggestion] = []

        if snapshot.tech_debt.total_markers > 0:
            suggestions.append(Suggestion(
                title=f"项目存在 {snapshot.tech_debt.total_markers} 个技术债标记",
                description=f"TODO: {snapshot.tech_debt.todo_count}, FIXME: {snapshot.tech_debt.fixme_count}, XXX: {snapshot.tech_debt.xxx_count}",
                priority="high" if snapshot.tech_debt.total_markers >= 20 else "medium",
                relevance=min(0.8, snapshot.tech_debt.total_markers * 0.02),
                category="tech_debt",
                actions=["查看技术债热点文件并处理"],
            ))

        if snapshot.test_state.coverage_percent is not None:
            coverage = snapshot.test_state.coverage_percent
            if coverage < 80:
                suggestions.append(Suggestion(
                    title=f"测试覆盖率不足 ({coverage:.1f}%)",
                    description=f"当前测试覆盖率为 {coverage:.1f}%，低于建议的 80% 阈值。",
                    priority="high" if coverage < 50 else "medium",
                    relevance=min(0.85, (80 - coverage) * 0.01),
                    category="test_gap",
                    actions=["增加测试用例提升覆盖率"],
                ))

        if snapshot.dependencies.outdated:
            outdated_count = len(snapshot.dependencies.outdated)
            suggestions.append(Suggestion(
                title=f"发现 {outdated_count} 个过期依赖",
                description=f"{outdated_count} 个依赖包有可用更新，建议及时升级。",
                priority="medium",
                relevance=min(0.7, outdated_count * 0.05),
                category="dependency",
                actions=["运行依赖更新命令升级过期包"],
            ))

        return suggestions


class CommitTrigger(Trigger):
    """git commit 后触发。

    扫描：
    - 新引入的 TODO 标记
    - 新增代码的测试覆盖情况
    - 代码复杂度变化

    建议类型：tech_debt、test_gap、refactor
    """

    EVENT_TYPE = "commit"

    def __init__(self, priority: int = 70, enabled: bool = True):
        super().__init__("CommitTrigger", priority, enabled)

    def matches(self, event: WorkspaceEvent) -> bool:
        if not self.enabled:
            return False
        return event.event_type == self.EVENT_TYPE

    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        suggestions: List[Suggestion] = []
        commit_message = event.payload.get("message", "")

        if "todo" in commit_message.lower():
            suggestions.append(Suggestion(
                title="Commit 中引入了新的 TODO",
                description=f"Commit 消息包含 TODO，建议及时处理。\nCommit: {commit_message}",
                priority="medium",
                relevance=0.75,
                category="tech_debt",
                actions=["查看本次提交中的 TODO 项并处理"],
            ))

        if snapshot.tech_debt.hotspots:
            top_hotspot = snapshot.tech_debt.hotspots[0]
            score = top_hotspot.get("score", 0)
            if score > 0:
                suggestions.append(Suggestion(
                    title=f"技术债热点：{top_hotspot['path']}",
                    description=f"文件 {top_hotspot['path']} 技术债密度较高，建议关注。",
                    priority="medium",
                    relevance=min(0.7, score * 0.1),
                    category="refactor",
                    target_file=top_hotspot.get("path"),
                    actions=["分析热点文件并制定重构计划"],
                ))

        if snapshot.test_state.failed > 0:
            suggestions.append(Suggestion(
                title=f"{snapshot.test_state.failed} 个测试用例失败",
                description=f"当前有 {snapshot.test_state.failed} 个测试失败，建议修复。",
                priority="high",
                relevance=0.8,
                category="test_gap",
                actions=["运行测试并修复失败用例"],
            ))

        if snapshot.test_state.coverage_percent is not None:
            coverage = snapshot.test_state.coverage_percent
            if coverage < 60:
                suggestions.append(Suggestion(
                    title=f"测试覆盖率较低 ({coverage:.1f}%)",
                    description=f"提交后测试覆盖率为 {coverage:.1f}%，建议补充测试。",
                    priority="medium",
                    relevance=0.7,
                    category="test_gap",
                    actions=["为新增代码编写测试用例"],
                ))

        return suggestions


class PeriodicTrigger(Trigger):
    """周期性触发（默认 10 分钟）。

    深度扫描：
    - 测试盲区检测
    - 依赖过期检查
    - 安全漏洞扫描（简化）

    建议类型：test_gap、dependency、security
    """

    EVENT_TYPE = "periodic"

    def __init__(self, priority: int = 30, enabled: bool = True):
        super().__init__("PeriodicTrigger", priority, enabled)

    def matches(self, event: WorkspaceEvent) -> bool:
        if not self.enabled:
            return False
        return event.event_type == self.EVENT_TYPE

    def generate_suggestions(self, snapshot: ProjectSnapshot,
                             event: WorkspaceEvent) -> List[Suggestion]:
        suggestions: List[Suggestion] = []

        if snapshot.test_state.total_cases == 0 and snapshot.file_tree.total_files > 0:
            suggestions.append(Suggestion(
                title="项目缺少测试用例",
                description=f"项目有 {snapshot.file_tree.total_files} 个文件，但测试用例数量为 0。",
                priority="high",
                relevance=0.8,
                category="test_gap",
                actions=["为项目编写基础测试用例"],
            ))

        if snapshot.dependencies.outdated:
            outdated_count = len(snapshot.dependencies.outdated)
            suggestions.append(Suggestion(
                title=f"{outdated_count} 个依赖需要更新",
                description=f"检测到 {outdated_count} 个过期依赖包。",
                priority="medium",
                relevance=min(0.75, outdated_count * 0.05),
                category="dependency",
                actions=["检查并升级过期依赖"],
            ))

        if snapshot.dependencies.vulnerabilities:
            vuln_count = len(snapshot.dependencies.vulnerabilities)
            suggestions.append(Suggestion(
                title=f"检测到 {vuln_count} 个潜在安全漏洞",
                description=f"部分依赖包存在已知安全风险，建议检查。",
                priority="high",
                relevance=0.85,
                category="security",
                actions=["审查安全漏洞并采取修复措施"],
            ))

        if snapshot.build_state.last_build_status == "failed":
            suggestions.append(Suggestion(
                title="上次构建失败",
                description="项目上次构建未成功，建议修复构建问题。",
                priority="high",
                relevance=0.75,
                category="bug",
                actions=["运行构建命令并修复问题"],
            ))

        return suggestions