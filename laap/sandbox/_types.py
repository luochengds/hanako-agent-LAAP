"""LAAP Sandbox 数据类型定义

定义 Cognitive Sandbox 容器内部使用的全部数据结构，
包括配置、建议、项目快照、Git/文件树/测试/构建状态、
技术债报告、依赖报告、以及跨 sandbox 通信事件。

所有字段均提供合理默认值，便于直接构造与序列化。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 类型别名
SandboxID = str  # sandbox 唯一标识，例如 "sb-architect-001"


@dataclass
class SandboxConfig:
    """Sandbox 配置"""

    name: str
    role: str  # architect / test_engineer / doc_maintainer / security_watcher
    sandbox_id: SandboxID = field(default_factory=lambda: f"sb-{uuid.uuid4().hex[:8]}")
    llm_calls_per_hour: int = 100
    cpu_seconds_per_min: int = 30
    memory_mb: int = 512
    inference_time_sec: int = 60
    created_at: float = field(default_factory=time.time)


@dataclass
class Suggestion:
    """主动建议"""

    suggestion_id: str = field(default_factory=lambda: f"sug-{uuid.uuid4().hex[:8]}")
    title: str = ""  # 简短标题
    description: str = ""  # 详细描述
    priority: str = "medium"  # critical / high / medium / low
    relevance: float = 0.5  # 0.0-1.0
    category: str = ""  # tech_debt / test_gap / dependency / refactor / bug
    target_file: Optional[str] = None  # 相关文件路径
    actions: List[str] = field(default_factory=list)  # 建议动作
    source_sandbox: Optional[SandboxID] = None  # 来自哪个 sandbox
    created_at: float = field(default_factory=time.time)
    # Phase 2.1: 因果链分析相关字段
    causal_chain: List[Dict[str, Any]] = field(default_factory=list)  # 因果链数组
    explanation: str = ""  # 可解释性描述
    confidence: float = 0.5  # 置信度 0-1
    source_data: str = ""  # 数据来源标记

    @property
    def task_id(self) -> str:
        """去重用 ID（基于 target_file + category）"""
        return f"{self.category}:{self.target_file or 'global'}"


@dataclass
class GitState:
    """Git 状态快照"""

    current_branch: str = ""
    recent_commits: List[Dict[str, Any]] = field(default_factory=list)  # [{hash, author, date, message}]
    uncommitted_count: int = 0
    branches: List[str] = field(default_factory=list)
    remotes: List[str] = field(default_factory=list)
    last_commit_at: Optional[float] = None


@dataclass
class FileTreeState:
    """文件树状态"""

    total_files: int = 0
    total_lines: int = 0
    languages: Dict[str, int] = field(default_factory=dict)  # {python: 50, javascript: 30, ...}
    file_paths: List[str] = field(default_factory=list)
    largest_files: List[Dict[str, Any]] = field(default_factory=list)  # [{path, lines, language}]
    module_structure: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestState:
    """测试状态"""

    framework: str = ""  # pytest / jest / unknown
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    coverage_percent: Optional[float] = None
    recent_failures: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BuildState:
    """构建状态"""

    build_system: str = ""  # pyproject / setup.py / package.json
    last_build_status: str = "unknown"  # success / failed / unknown
    last_build_at: Optional[float] = None
    build_duration_sec: Optional[float] = None
    warnings: int = 0


@dataclass
class TechDebtReport:
    """技术债报告"""

    todo_count: int = 0
    fixme_count: int = 0
    xxx_count: int = 0
    total_markers: int = 0
    hotspots: List[Dict[str, Any]] = field(default_factory=list)  # Top-10 [{path, lines, todo_density, score}]
    by_file: Dict[str, int] = field(default_factory=dict)  # {file_path: marker_count}


@dataclass
class DependencyReport:
    """依赖报告"""

    total: int = 0
    direct: List[Dict[str, Any]] = field(default_factory=list)  # [{name, version, latest}]
    outdated: List[Dict[str, Any]] = field(default_factory=list)
    vulnerabilities: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectSnapshot:
    """完整项目快照"""

    root_path: str = ""
    git_state: GitState = field(default_factory=GitState)
    file_tree: FileTreeState = field(default_factory=FileTreeState)
    test_state: TestState = field(default_factory=TestState)
    build_state: BuildState = field(default_factory=BuildState)
    tech_debt: TechDebtReport = field(default_factory=TechDebtReport)
    dependencies: DependencyReport = field(default_factory=DependencyReport)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> Dict[str, Any]:
        """简短摘要（用于 memory_stream 记录）"""
        return {
            "root": self.root_path,
            "branch": self.git_state.current_branch,
            "files": self.file_tree.total_files,
            "lines": self.file_tree.total_lines,
            "tech_debt_markers": self.tech_debt.total_markers,
            "test_cases": self.test_state.total_cases,
            "deps": self.dependencies.total,
            "snapshot_at": self.timestamp,
        }


@dataclass
class WorkspaceEvent:
    """Workspace 事件"""

    event_type: str  # file_open / file_save / build_failed / build_success / commit / idle / periodic
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)  # 事件特定数据
    source: str = ""  # user / system / scheduler


@dataclass
class ColonyEvent:
    """Colony 事件（跨 sandbox 通信）"""

    event_type: str  # shared_fact / resource_request / resource_approved / resource_rejected / colony_task / experience_propagation
    source_sandbox: Optional[SandboxID] = None
    target_sandbox: Optional[SandboxID] = None  # None = 广播
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
