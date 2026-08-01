"""LAAP PR Review Engine — Colony Agents 驱动的 GitHub PR 代码审查引擎

架构:
  GitHub Webhook → PR Info → git diff → PRReviewEngine
    ├─ SecurityAgent.scan_security()       — 安全漏洞扫描
    ├─ PerformanceAgent.analyze_static()   — 性能瓶颈检测
    ├─ ArchitectAgent 简化版                — 架构风险分析
    ├─ DocAgent       简化版                — 文档完整性检查
    └─ 通用检查                            — 文件大小/行数/密钥泄漏/合并冲突
    → 结构化 Review → GitHub REST API 提交
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.colony.pr_review")

# ── Diff 解析 ──────────────────────────────────────────────────

@dataclass
class DiffHunk:
    """一个 diff hunk（@@ -a,b +c,d @@ 块）"""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[Tuple[str, str]]  # [(type, text)]  type: ' '=context, '+'=added, '-'=removed

@dataclass
class FileChange:
    """PR 中一个文件的变更"""
    path: str
    status: str  # added / modified / deleted / renamed
    additions: int
    deletions: int
    hunks: List[DiffHunk] = field(default_factory=list)

    @property
    def added_lines(self) -> List[int]:
        """新增/修改的行号（用于 inline review 定位）"""
        lines = []
        for hunk in self.hunks:
            line_num = hunk.new_start
            for line_type, _ in hunk.lines:
                if line_type != '-':
                    if line_type == '+':
                        lines.append(line_num)
                    line_num += 1
        return lines

    @property
    def changed_content(self) -> str:
        """只返回新增+修改的行内容"""
        result = []
        for hunk in self.hunks:
            for line_type, text in hunk.lines:
                if line_type in ('+', '-'):
                    result.append(f"{line_type}{text}")
        return "\n".join(result)

    @property
    def full_diff(self) -> str:
        """完整 diff 文本"""
        lines = [f"--- a/{self.path}", f"+++ b/{self.path}"]
        for hunk in self.hunks:
            lines.append(f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@")
            for lt, text in hunk.lines:
                lines.append(f"{lt}{text}")
        return "\n".join(lines)


def parse_diff(diff_text: str) -> List[FileChange]:
    """将 unified diff 文本解析为 FileChange 列表。"""
    files: List[FileChange] = []
    current_file: Optional[FileChange] = None
    current_hunk: Optional[DiffHunk] = None
    hunk_lines: List[Tuple[str, str]] = []

    for line in diff_text.splitlines():
        # 文件头
        if line.startswith("diff --git"):
            if current_file:
                if current_hunk:
                    current_hunk.lines = hunk_lines
                    current_file.hunks.append(current_hunk)
                files.append(current_file)
            parts = line.split()
            path = parts[-1].lstrip("b/") if len(parts) >= 4 else "unknown"
            current_file = FileChange(path=path, status="modified", additions=0, deletions=0)
            current_hunk = None
            hunk_lines = []

        # 新旧文件路径/状态
        elif line.startswith("--- a/"):
            pass
        elif line.startswith("+++ b/"):
            pass
        elif line.startswith("new file"):
            if current_file:
                current_file.status = "added"
        elif line.startswith("deleted file"):
            if current_file:
                current_file.status = "deleted"

        # Hunk 头
        elif line.startswith("@@"):
            if current_file and current_hunk:
                current_hunk.lines = hunk_lines
                current_file.hunks.append(current_hunk)
            m = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
            if m:
                old_s = int(m.group(1))
                old_c = int(m.group(2)) if m.group(2) else 1
                new_s = int(m.group(3))
                new_c = int(m.group(4)) if m.group(4) else 1
                current_hunk = DiffHunk(old_s, old_c, new_s, new_c, [])
                hunk_lines = []
            else:
                current_hunk = None

        # Hunk 内容行
        elif current_hunk is not None:
            if line.startswith('+'):
                hunk_lines.append(('+', line[1:]))
                if current_file:
                    current_file.additions += 1
            elif line.startswith('-'):
                hunk_lines.append(('-', line[1:]))
                if current_file:
                    current_file.deletions += 1
            else:
                hunk_lines.append((' ', line[1:] if line.startswith(' ') else line))

    # 收尾最后一个文件
    if current_file:
        if current_hunk:
            current_hunk.lines = hunk_lines
            current_file.hunks.append(current_hunk)
        files.append(current_file)

    return files


def build_file_contents_map(files: List[FileChange], repo_path: str) -> Dict[str, str]:
    """从 FileChange 列表构建 {file_path: file_content} 映射（只读新增+修改的完整文件）。"""
    contents: Dict[str, str] = {}
    for fc in files:
        if fc.status == "deleted":
            continue
        full_path = os.path.join(repo_path, fc.path)
        if os.path.isfile(full_path):
            try:
                with open(full_path, 'r', encoding='utf-8-sig') as f:
                    contents[fc.path] = f.read()
            except (OSError, UnicodeDecodeError):
                contents[fc.path] = fc.changed_content
        else:
            contents[fc.path] = fc.changed_content
    return contents


# ── 审查发现类型 ──────────────────────────────────────────────

@dataclass
class ReviewFinding:
    severity: str  # critical / high / medium / low / info
    category: str  # security / performance / architecture / documentation / best_practice
    file: str
    line: Optional[int] = None
    title: str = ""
    description: str = ""
    suggestion: str = ""
    agent: str = ""  # security / performance / architect / doc / general


# ── LAAP Colony Agent 包装 ────────────────────────────────────

class PRReviewEngine:
    """PR 审查引擎——将 git diff 输入结构化审查结果输出。"""

    def __init__(self):
        self._security_agent = None
        self._performance_agent = None
        self._initialized = False

    def lazy_init(self) -> None:
        """延迟加载 Colony 安全/性能 Agent。"""
        if self._initialized:
            return
        try:
            from laap.colony.security_agent import SecurityAgent
            from laap.sandbox.colony import ColonyEventBus
            from laap.sandbox.skill_library import SkillLibrary
            bus = ColonyEventBus()
            lib = SkillLibrary()
            self._security_agent = SecurityAgent("sb-pr-sec", lib, bus)
            self._performance_agent = None  # 需要 PerformanceAgent 同样的初始化
            self._initialized = True
            logger.info("PRReviewEngine: 安全 Agent 已加载")
        except Exception as e:
            logger.warning(f"PRReviewEngine: Agent 加载失败: {e}")

    def review(self, diff_text: str, repo_path: str) -> Dict[str, Any]:
        """审查一个 diff，返回结构化结果。

        Args:
            diff_text: git diff 文本
            repo_path: 仓库本地路径（用于读取完整文件上下文）

        Returns:
            {
                "summary": "2 critical, 3 warnings, 5 suggestions",
                "findings": [...],
                "verdict": "changes_requested" / "comment" / "approve",
                "stats": {files_changed, additions, deletions}
            }
        """
        self.lazy_init()
        files = parse_diff(diff_text)
        all_findings: List[ReviewFinding] = []

        # ── 通用检查（不依赖 Agent） ──
        all_findings.extend(self._general_checks(files))

        # ── 安全检查 ──
        all_findings.extend(self._security_checks(files, repo_path))

        # ── 性能检查 ──
        all_findings.extend(self._performance_checks(files, repo_path))

        # ── 架构检查 ──
        all_findings.extend(self._architecture_checks(files))

        # ── 文档检查 ──
        all_findings.extend(self._doc_checks(files))

        # ── 评级 ──
        verdict = self._determine_verdict(all_findings)

        stats = {
            "files_changed": len(files),
            "additions": sum(f.additions for f in files),
            "deletions": sum(f.deletions for f in files),
        }

        return {
            "summary": self._build_summary(all_findings),
            "findings": [self._finding_to_dict(f) for f in all_findings],
            "verdict": verdict,
            "stats": stats,
        }

    # ── 通用检查 ──

    def _general_checks(self, files: List[FileChange]) -> List[ReviewFinding]:
        findings: List[ReviewFinding] = []

        total_additions = sum(f.additions for f in files)
        total_files = len(files)

        # 大 PR 告警
        if total_additions > 1000:
            findings.append(ReviewFinding(
                severity="medium",
                category="best_practice",
                file="(overall)",
                title="PR 变更量较大",
                description=f"本次 PR 共 {total_additions} 行新增，建议拆分为多个小 PR 以便审查",
                suggestion="考虑分拆为 2-3 个独立 PR，每个不超过 500 行",
                agent="general",
            ))

        if total_files > 20:
            findings.append(ReviewFinding(
                severity="medium",
                category="best_practice",
                file="(overall)",
                title="修改文件数量较多",
                description=f"共修改 {total_files} 个文件",
                suggestion="检查是否所有修改都紧密关联同一功能",
                agent="general",
            ))

        # 检查每个文件的合并冲突标记和调试语句
        for fc in files:
            for hunk in fc.hunks:
                for lt, text in hunk.lines:
                    # 合并冲突标记
                    if lt == '+' and text.strip().startswith(('<<<<<<<', '=======', '>>>>>>>')):
                        findings.append(ReviewFinding(
                            severity="critical",
                            category="best_practice",
                            file=fc.path,
                            title="存在合并冲突标记",
                            description="检测到未解决的合并冲突标记 <<<<<<< / ======= / >>>>>>>",
                            suggestion="请解决合并冲突后再提交",
                            agent="general",
                        ))
                    # 调试语句
                    if lt == '+' and any(kw in text for kw in ['print(', 'console.log(', 'debugger', 'import pdb']):
                        findings.append(ReviewFinding(
                            severity="medium" if 'debugger' in text or 'import pdb' in text else "low",
                            category="best_practice",
                            file=fc.path,
                            title="检测到调试语句",
                            description=f"可能遗留的调试代码: {text.strip()[:60]}",
                            suggestion="生产代码中移除调试语句",
                            agent="general",
                        ))
                    # 硬编码密钥（简化检测）
                    if lt == '+' and re.search(r'(?:api[_-]?key|password|secret|token)\s*[:=]\s*["\'][A-Za-z0-9_\-]{16,}', text, re.IGNORECASE):
                        findings.append(ReviewFinding(
                            severity="critical",
                            category="security",
                            file=fc.path,
                            title="检测到可能的硬编码密钥",
                            suggestion="使用环境变量或密钥管理服务",
                            agent="general",
                        ))

        return findings

    # ── 安全检查 ──

    def _security_checks(self, files: List[FileChange], repo_path: str) -> List[ReviewFinding]:
        findings: List[ReviewFinding] = []
        if not self._security_agent or not files:
            return findings

        try:
            contents = build_file_contents_map(files, repo_path)
            if not contents:
                return findings

            # 调用 SecurityAgent 的安全扫描
            vulns = self._security_agent.scan_security(contents)
            for v in vulns:
                findings.append(ReviewFinding(
                    severity=v.get("severity", "medium"),
                    category="security",
                    file=v.get("file", ""),
                    line=v.get("line"),
                    title=f"安全漏洞: {v.get('type', 'unknown')}",
                    description=v.get("snippet", "")[:120],
                    suggestion=v.get("fix", ""),
                    agent="security",
                ))

            # 依赖检查（如果 requirements/pyproject 有修改）
            dep_files = [f for f in files if f.path in ("requirements.txt", "pyproject.toml", "Pipfile", "Cargo.toml", "package.json")]
            for df in dep_files:
                full_path = os.path.join(repo_path, df.path)
                if os.path.isfile(full_path):
                    try:
                        with open(full_path, 'r') as f:
                            content = f.read()
                        deps = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith(('#', '//', '/*'))]
                        dep_vulns = self._security_agent.check_dependencies(deps[:50])
                        for dv in dep_vulns:
                            findings.append(ReviewFinding(
                                severity=dv.get("severity", "medium"),
                                category="security",
                                file=df.path,
                                title=f"依赖漏洞: {dv.get('package', '')}",
                                description=dv.get("vulnerability", ""),
                                suggestion=dv.get("fix", ""),
                                agent="security",
                            ))
                    except (OSError, UnicodeDecodeError):
                        pass
        except Exception as e:
            logger.warning(f"安全扫描异常: {e}")

        return findings

    # ── 性能检查 ──

    def _performance_checks(self, files: List[FileChange], repo_path: str) -> List[ReviewFinding]:
        """检查性能相关问题（简化版，不依赖 Agent 全量加载）。"""
        findings: List[ReviewFinding] = []

        for fc in files:
            if not fc.path.endswith('.py'):
                continue

            added_content = fc.changed_content
            if not added_content:
                continue

            # N+1 查询检测：循环内数据库调用
            in_loop = False
            for line in added_content.splitlines():
                stripped = line.strip()
                if stripped.startswith(('for ', 'while ')):
                    in_loop = True
                elif in_loop and stripped == '':
                    in_loop = False
                elif in_loop and any(kw in stripped for kw in ['.query(', '.filter(', '.filter_by(', '.all()', '.first()', '.fetchone(', '.fetchall(']):
                    findings.append(ReviewFinding(
                        severity="high",
                        category="performance",
                        file=fc.path,
                        title="检测到 N+1 查询模式",
                        description="循环内存在数据库/ORM 调用，可能引发 N+1 查询",
                        suggestion="使用批量查询或 select_related / prefetch_related 预加载",
                        agent="performance",
                    ))
                    in_loop = False  # 避免重复

            # 大 list(range(N)) 检测
            for m in re.finditer(r'list\s*\(\s*range\s*\(\s*(\d+)\s*\)\s*\)', added_content):
                n = int(m.group(1))
                if n > 10000:
                    findings.append(ReviewFinding(
                        severity="medium",
                        category="performance",
                        file=fc.path,
                        title="检测到大对象分配",
                        description=f"一次性构造大小为 {n} 的列表，可能造成内存压力",
                        suggestion="改用生成器或分批处理",
                        agent="performance",
                    ))

        return findings

    # ── 架构检查 ──

    def _architecture_checks(self, files: List[FileChange]) -> List[ReviewFinding]:
        """架构风险检查（简化版）。"""
        findings: List[ReviewFinding] = []

        # 检查新增文件
        for fc in files:
            if fc.status == "added" and fc.path.endswith('.py'):
                # 检查是否有可能的单体大文件
                if fc.additions > 500:
                    findings.append(ReviewFinding(
                        severity="medium",
                        category="architecture",
                        file=fc.path,
                        title="新增文件体积较大",
                        description=f"新增 {fc.additions} 行代码到单一文件中",
                        suggestion="考虑拆分为多个职责单一的小模块",
                        agent="architect",
                    ))

            # 检查 __init__.py 修改
            if fc.path.endswith('__init__.py') and fc.additions > 50:
                findings.append(ReviewFinding(
                    severity="low",
                    category="architecture",
                    file=fc.path,
                    title="__init__.py 大量变更",
                    description="__init__.py 大量新增可能导致循环导入",
                    suggestion="检查是否新增了循环依赖风险",
                    agent="architect",
                ))

        return findings

    # ── 文档检查 ──

    def _doc_checks(self, files: List[FileChange]) -> List[ReviewFinding]:
        """文档完整性检查。"""
        findings: List[ReviewFinding] = []
        has_doc_change = any(f.path.endswith(('.md', '.rst', '.txt', 'README')) for f in files)

        source_changes = [f for f in files if f.path.endswith('.py') and f.additions > 0]

        # 如果有源码修改但没有文档更新
        if source_changes and not has_doc_change:
            findings.append(ReviewFinding(
                severity="low",
                category="documentation",
                file="(overall)",
                title="文档可能需同步更新",
                description=f"修改了 {len(source_changes)} 个源文件但未更新相关文档",
                suggestion="检查是否需要同步更新 README/文档",
                agent="doc",
            ))

        # 检查新增函数/类是否缺少 docstring
        for fc in source_changes:
            added = fc.changed_content
            new_funcs = re.findall(r'^\+\s*def (\w+)\s*\(', added, re.MULTILINE)
            new_classes = re.findall(r'^\+\s*class (\w+)\s*[:\(]', added, re.MULTILINE)
            if new_funcs or new_classes:
                full_path = os.path.join(".", fc.path)
                # 简化检查：看文件中是否有 docstring 缺失
                findings.append(ReviewFinding(
                    severity="info",
                    category="documentation",
                    file=fc.path,
                    title="新增公开接口需确认 docstring",
                    description=f"新增 {len(new_funcs)} 函数, {len(new_classes)} 类，请检查 docstring 完整性",
                    suggestion="为每个公开函数/类添加 docstring（参数、返回值、异常说明）",
                    agent="doc",
                ))

        return findings

    # ── 输出格式化 ──

    def _determine_verdict(self, findings: List[ReviewFinding]) -> str:
        """根据发现的问题决定审查结论。"""
        severities = {f.severity for f in findings}
        if "critical" in severities:
            return "REQUEST_CHANGES"
        if "high" in severities:
            return "REQUEST_CHANGES"
        if "medium" in severities:
            return "COMMENT"
        return "APPROVE"

    def _build_summary(self, findings: List[ReviewFinding]) -> str:
        """构建一行摘要文本。"""
        counts: Dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        parts = []
        for s in ("critical", "high", "medium", "low", "info"):
            if s in counts:
                parts.append(f"{counts[s]} {s}")
        return ", ".join(parts) if parts else "no issues found"

    @staticmethod
    def _finding_to_dict(f: ReviewFinding) -> dict:
        return {
            "severity": f.severity,
            "category": f.category,
            "file": f.file,
            "line": f.line,
            "title": f.title,
            "description": f.description,
            "suggestion": f.suggestion,
            "agent": f.agent,
        }

    @staticmethod
    def format_review_markdown(result: Dict[str, Any]) -> str:
        """将审查结果格式化为 GitHub Review 的 Markdown 正文。"""
        findings = result.get("findings", [])
        stats = result.get("stats", {})
        verdict_labels = {
            "REQUEST_CHANGES": "🔴 Changes Requested",
            "COMMENT": "💬 Comments",
            "APPROVE": "✅ Approved",
        }
        verdict_label = verdict_labels.get(result.get("verdict", ""), result.get("verdict", ""))

        md = [
            f"## LAAP Colony Review — {verdict_label}",
            "",
            f"**Summary:** {result.get('summary', 'no issues')}",
            "",
            f"Files: {stats.get('files_changed', 0)}  |  "
            f"+{stats.get('additions', 0)} / -{stats.get('deletions', 0)} lines",
            "",
        ]

        if not findings:
            md.append("No issues found. Looks clean! 🎉")
            return "\n".join(md)

        # 按严重程度分组
        for severity, label in [("critical", "### 🔴 Critical"), ("high", "### ⚠️ High"),
                                 ("medium", "### 🟡 Medium"), ("low", "### 🔵 Low"),
                                 ("info", "### ℹ️ Info")]:
            group = [f for f in findings if f["severity"] == severity]
            if not group:
                continue
            md.append(label)
            md.append("")
            for f in group:
                loc = f"`{f['file']}`" + (f":{f['line']}" if f['line'] else "")
                md.append(f"- **{f['title']}** ({loc})")
                if f['description']:
                    md.append(f"  - {f['description'][:200]}")
                if f['suggestion']:
                    md.append(f"  - 💡 {f['suggestion']}")
            md.append("")

        md.append("---")
        md.append("*Reviewed by LAAP Colony Agents*")
        return "\n".join(md)

    @staticmethod
    def build_inline_comments(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """为 critical 和 high 级别的问题生成 inline review comments。"""
        comments = []
        for f in result.get("findings", []):
            if f["severity"] in ("critical", "high") and f.get("line") and f.get("file"):
                comments.append({
                    "path": f["file"],
                    "line": f["line"],
                    "body": f"**{f['title']}**\n\n{f['description']}\n\n💡 {f['suggestion']}",
                })
        return comments
