"""LAAP Living Workspace CLI — 命令行接口

用法：
    laap-workspace scan [--full] [--output=json|text]
    laap-workspace watch [--interval=60]
    laap-workspace suggest [--event=file_open|build_failed|idle|commit|periodic]
    laap-workspace status
    laap-workspace agents list
    laap-workspace agents analyze <agent_name>
    laap-workspace --help
    laap-workspace --version

子命令：
    scan      — 扫描项目状态，输出报告
    watch     — 启动文件监听模式
    suggest   — 手动触发建议生成
    status    — 显示工作区状态
    agents    — 管理数字生命体
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

from laap.colony.architect import ArchitectAgent
from laap.colony.test_engineer import TestEngineerAgent
from laap.sandbox._types import WorkspaceEvent
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.skill_library import SkillLibrary
from laap.workspace.advisor import ProactiveAdvisor
from laap.workspace.perception import ProjectPerception
from laap.workspace.storage import SuggestionQueue

__version__ = "0.1.0"


def main() -> None:
    """CLI 入口点。"""
    parser = argparse.ArgumentParser(
        prog="laap-workspace",
        description="LAAP Living Workspace — 项目状态感知与主动建议引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令说明：
    scan      — 扫描项目状态，输出报告（文件数、代码行数、技术债、测试用例、依赖数等）
    watch     — 启动文件监听模式，持续监控文件变更
    suggest   — 手动触发建议生成，可指定事件类型
    status    — 显示工作区状态（监听状态、缓存命中率、扫描次数等）
    agents    — 管理数字生命体（Architect、TestEngineer）
        """,
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="扫描项目状态，输出报告")
    scan_parser.add_argument("--full", action="store_true", help="强制全量扫描")
    scan_parser.add_argument(
        "--output", choices=["json", "text"], default="text", help="输出格式"
    )

    watch_parser = subparsers.add_parser("watch", help="启动文件监听模式")
    watch_parser.add_argument(
        "--interval", type=int, default=60, help="状态输出间隔（秒）"
    )

    suggest_parser = subparsers.add_parser("suggest", help="手动触发建议生成")
    suggest_parser.add_argument(
        "--event",
        choices=["file_open", "build_failed", "idle", "commit", "periodic"],
        default="file_open",
        help="触发事件类型",
    )

    subparsers.add_parser("status", help="显示工作区状态")

    agents_parser = subparsers.add_parser("agents", help="管理数字生命体")
    agents_subparsers = agents_parser.add_subparsers(dest="agents_command", required=True)
    agents_subparsers.add_parser("list", help="列出已注册的数字生命体")

    agents_analyze_parser = agents_subparsers.add_parser(
        "analyze", help="分析指定数字生命体"
    )
    agents_analyze_parser.add_argument("agent_name", help="数字生命体名称")

    args = parser.parse_args()

    if args.command == "scan":
        _cmd_scan(args)
    elif args.command == "watch":
        _cmd_watch(args)
    elif args.command == "suggest":
        _cmd_suggest(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "agents":
        if args.agents_command == "list":
            _cmd_agents_list(args)
        elif args.agents_command == "analyze":
            _cmd_agents_analyze(args)


def _cmd_scan(args: argparse.Namespace) -> None:
    """处理 scan 子命令。"""
    perception = ProjectPerception(root_path=os.getcwd())
    snapshot = perception.perceive(full=args.full)

    report = _build_report(snapshot)
    _print_report(report, format=args.output)


def _build_report(snapshot: Any) -> Dict[str, Any]:
    """构建扫描报告。"""
    return {
        "root_path": snapshot.root_path,
        "timestamp": snapshot.timestamp,
        "file_tree": {
            "total_files": snapshot.file_tree.total_files,
            "total_lines": snapshot.file_tree.total_lines,
            "languages": snapshot.file_tree.languages,
        },
        "tech_debt": {
            "total_markers": snapshot.tech_debt.total_markers,
            "todo_count": snapshot.tech_debt.todo_count,
            "fixme_count": snapshot.tech_debt.fixme_count,
            "xxx_count": snapshot.tech_debt.xxx_count,
            "hotspots": snapshot.tech_debt.hotspots,
        },
        "test_state": {
            "framework": snapshot.test_state.framework,
            "total_cases": snapshot.test_state.total_cases,
            "passed": snapshot.test_state.passed,
            "failed": snapshot.test_state.failed,
            "coverage_percent": snapshot.test_state.coverage_percent,
        },
        "build_state": {
            "build_system": snapshot.build_state.build_system,
            "last_build_status": snapshot.build_state.last_build_status,
            "warnings": snapshot.build_state.warnings,
        },
        "dependencies": {
            "total": snapshot.dependencies.total,
            "direct": [d["name"] for d in snapshot.dependencies.direct],
            "outdated_count": len(snapshot.dependencies.outdated),
            "vulnerabilities_count": len(snapshot.dependencies.vulnerabilities),
        },
        "git_state": {
            "current_branch": snapshot.git_state.current_branch,
            "uncommitted_count": snapshot.git_state.uncommitted_count,
            "recent_commits_count": len(snapshot.git_state.recent_commits),
        },
    }


def _cmd_watch(args: argparse.Namespace) -> None:
    """处理 watch 子命令。"""
    perception = ProjectPerception(root_path=os.getcwd())
    perception.start_watching()

    print(f"开始监听项目目录: {perception.root_path}")
    print(f"状态输出间隔: {args.interval} 秒")
    print("按 Ctrl+C 停止监听\n")

    try:
        while True:
            stats = perception.stats()
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]")
            print(f"  扫描次数: {stats['scan_count']}")
            print(f"  缓存命中: {stats['cache_hit_count']}")
            print(f"  缓存未命中: {stats['cache_miss_count']}")
            print(f"  监听状态: {'运行中' if perception._is_watching else '已停止'}")
            print("-" * 40)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n正在停止监听...")
        perception.stop_watching()
        print("监听已停止")


def _cmd_suggest(args: argparse.Namespace) -> None:
    """处理 suggest 子命令。"""
    perception = ProjectPerception(root_path=os.getcwd())
    event_bus = ColonyEventBus()
    skill_lib = SkillLibrary()

    architect = ArchitectAgent(
        sandbox_id="sb-architect-cli",
        skill_library=skill_lib,
        event_bus=event_bus,
    )
    test_engineer = TestEngineerAgent(
        sandbox_id="sb-test-engineer-cli",
        skill_library=skill_lib,
        event_bus=event_bus,
    )

    snapshot = perception.perceive(full=True)
    architect.perceive(snapshot)
    test_engineer.perceive(snapshot)

    queue = SuggestionQueue(db_path="laap_workspace_cli.db")

    advisor = ProactiveAdvisor(
        perception=perception,
        sandboxes=[architect, test_engineer],
        queue=queue,
    )

    event_payloads = {
        "file_open": {"file_path": "laap/workspace/cli.py"},
        "build_failed": {"error_message": "test error"},
        "idle": {},
        "commit": {"message": "test commit"},
        "periodic": {},
    }

    event = WorkspaceEvent(
        event_type=args.event,
        payload=event_payloads.get(args.event, {}),
    )

    suggestions = advisor.evaluate(event)

    print(f"\n触发事件: {args.event}")
    print(f"生成建议数: {len(suggestions)}")
    print("-" * 60)

    for i, suggestion in enumerate(suggestions, 1):
        print(f"\n建议 #{i}")
        print(f"  ID: {suggestion.suggestion_id}")
        print(f"  标题: {suggestion.title}")
        print(f"  优先级: {suggestion.priority}")
        print(f"  相关性: {suggestion.relevance:.2f}")
        print(f"  类别: {suggestion.category}")
        print(f"  目标文件: {suggestion.target_file or 'N/A'}")
        print(f"  来源: {suggestion.source_sandbox or 'N/A'}")
        print(f"  描述: {suggestion.description}")
        if suggestion.actions:
            print("  建议动作:")
            for j, action in enumerate(suggestion.actions, 1):
                print(f"    {j}. {action}")

    queue.close()
    os.remove("laap_workspace_cli.db")


def _cmd_status(args: argparse.Namespace) -> None:
    """处理 status 子命令。"""
    perception = ProjectPerception(root_path=os.getcwd())
    stats = perception.stats()

    cache_total = stats["cache_hit_count"] + stats["cache_miss_count"]
    hit_rate = (stats["cache_hit_count"] / cache_total * 100) if cache_total > 0 else 0.0

    print("LAAP Living Workspace 状态")
    print("=" * 40)
    print(f"项目根目录: {stats['root_path']}")
    print(f"\n扫描统计:")
    print(f"  总扫描次数: {stats['scan_count']}")
    print(f"  缓存命中: {stats['cache_hit_count']}")
    print(f"  缓存未命中: {stats['cache_miss_count']}")
    print(f"  缓存命中率: {hit_rate:.1f}%")
    print(f"\n监听状态:")
    print(f"  是否正在监听: {'是' if perception._is_watching else '否'}")
    print(f"\n上次扫描时间:")
    if stats["last_scan_at"] > 0:
        print(f"  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats['last_scan_at']))}")
    else:
        print(f"  从未扫描")


def _cmd_agents_list(args: argparse.Namespace) -> None:
    """处理 agents list 子命令。"""
    agents = [
        {
            "name": "Architect",
            "role": "architect",
            "description": "项目架构分析与重构建议",
            "skills": ["analyze_dependencies", "detect_circular_imports", "suggest_refactor"],
        },
        {
            "name": "TestEngineer",
            "role": "test_engineer",
            "description": "测试分析与测试覆盖建议",
            "skills": ["find_uncovered_paths", "suggest_test_cases", "detect_flaky_tests"],
        },
    ]

    print("已注册的数字生命体:")
    print("=" * 40)

    for i, agent in enumerate(agents, 1):
        print(f"\n{i}. {agent['name']}")
        print(f"   角色: {agent['role']}")
        print(f"   描述: {agent['description']}")
        print(f"   技能:")
        for skill in agent["skills"]:
            print(f"     - {skill}")


def _cmd_agents_analyze(args: argparse.Namespace) -> None:
    """处理 agents analyze 子命令。"""
    event_bus = ColonyEventBus()
    skill_lib = SkillLibrary()

    perception = ProjectPerception(root_path=os.getcwd())
    snapshot = perception.perceive(full=True)

    if args.agent_name.lower() == "architect":
        agent = ArchitectAgent(
            sandbox_id="sb-architect-analysis",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        agent.perceive(snapshot)
        result = agent.analyze_project_structure()

        print(f"Architect 分析结果:")
        print("=" * 40)
        print(f"模块总数: {result['total_modules']}")
        print(f"循环依赖数: {result['circular_dependencies']}")
        print(f"技术债评分: {result['tech_debt_score']:.4f}")
        print(f"架构健康度: {result['architecture_health']}")
        print(f"\n复杂度热点 (Top-5):")
        for i, hotspot in enumerate(result["complexity_hotspots"], 1):
            print(f"\n  {i}. {hotspot['path']}")
            print(f"     行数: {hotspot['lines']}")
            print(f"     TODO密度: {hotspot['todo_density']:.4f}")
            print(f"     评分: {hotspot['score']:.4f}")

    elif args.agent_name.lower() == "testengineer":
        agent = TestEngineerAgent(
            sandbox_id="sb-test-engineer-analysis",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        agent.perceive(snapshot)
        result = agent.analyze_test_quality()

        print(f"TestEngineer 分析结果:")
        print("=" * 40)
        print(f"测试用例总数: {result['total_test_cases']}")
        print(f"测试通过率: {result['pass_rate']:.1f}%")
        print(f"覆盖率: {result['coverage_percent']:.1f}%")
        print(f"测试质量: {result['test_quality']}")
        print(f"\n未覆盖模块数: {len(result['uncovered_modules'])}")
        print(f"Flaky 测试数: {len(result['flaky_tests'])}")

    else:
        print(f"未知的数字生命体: {args.agent_name}")
        print("可用的数字生命体: Architect, TestEngineer")
        sys.exit(1)


def _print_report(report: Dict[str, Any], format: str = "text") -> None:
    """打印报告（支持 text 和 json 格式）。"""
    if format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("LAAP 项目扫描报告")
        print("=" * 60)
        print(f"\n项目信息:")
        print(f"  根目录: {report['root_path']}")
        print(f"  扫描时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report['timestamp']))}")

        print(f"\n文件统计:")
        print(f"  总文件数: {report['file_tree']['total_files']}")
        print(f"  总行数: {report['file_tree']['total_lines']}")
        print(f"  语言分布:")
        for lang, count in sorted(report['file_tree']['languages'].items(), key=lambda x: -x[1]):
            print(f"    {lang}: {count}")

        print(f"\n技术债:")
        print(f"  总标记数: {report['tech_debt']['total_markers']}")
        print(f"  TODO: {report['tech_debt']['todo_count']}")
        print(f"  FIXME: {report['tech_debt']['fixme_count']}")
        print(f"  XXX: {report['tech_debt']['xxx_count']}")
        if report['tech_debt']['hotspots']:
            print(f"\n  技术债热点 (Top-5):")
            for i, hotspot in enumerate(report['tech_debt']['hotspots'][:5], 1):
                print(f"    {i}. {hotspot['path']} (标记数: {hotspot['marker_count']}, 密度: {hotspot['todo_density']:.4f})")

        print(f"\n测试状态:")
        print(f"  测试框架: {report['test_state']['framework']}")
        print(f"  测试用例数: {report['test_state']['total_cases']}")
        print(f"  通过/失败: {report['test_state']['passed']}/{report['test_state']['failed']}")
        coverage = report['test_state']['coverage_percent']
        print(f"  覆盖率: {coverage:.1f}%" if coverage is not None else "  覆盖率: 未检测")

        print(f"\n构建状态:")
        print(f"  构建系统: {report['build_state']['build_system']}")
        print(f"  上次构建状态: {report['build_state']['last_build_status']}")
        print(f"  构建警告数: {report['build_state']['warnings']}")

        print(f"\n依赖统计:")
        print(f"  总依赖数: {report['dependencies']['total']}")
        print(f"  过期依赖数: {report['dependencies']['outdated_count']}")
        print(f"  潜在漏洞数: {report['dependencies']['vulnerabilities_count']}")

        print(f"\nGit 状态:")
        print(f"  当前分支: {report['git_state']['current_branch']}")
        print(f"  未提交文件数: {report['git_state']['uncommitted_count']}")
        print(f"  最近提交数: {report['git_state']['recent_commits_count']}")


if __name__ == "__main__":
    main()
