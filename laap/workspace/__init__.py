"""LAAP Living Workspace — 项目状态感知与主动建议引擎

Living Workspace 让数字生命体能够:
  - 感知项目状态（git/文件树/测试/构建/技术债/依赖）
  - 监听文件变更、构建事件、commit 事件
  - 通过触发器生成主动建议
  - 投递建议到持久化队列
"""
from laap.workspace.advisor import ProactiveAdvisor
from laap.workspace.cli import main as cli_main
from laap.workspace.perception import ProjectPerception
from laap.workspace.storage import SuggestionQueue
from laap.workspace.triggers import (
    BuildFailureTrigger,
    CommitTrigger,
    FileOpenTrigger,
    IdleTrigger,
    PeriodicTrigger,
    Trigger,
)

__all__ = [
    "ProjectPerception",
    "ProactiveAdvisor",
    "SuggestionQueue",
    "Trigger",
    "FileOpenTrigger",
    "BuildFailureTrigger",
    "IdleTrigger",
    "CommitTrigger",
    "PeriodicTrigger",
]
