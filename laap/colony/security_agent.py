"""安全审计数字生命体——负责系统安全扫描、漏洞检测及安全建议生成。

SecurityAgent 继承 CognitiveSandbox，特化角色为"security_watcher"，
专注于代码层面的安全漏洞检测、依赖漏洞审查和安全建议输出。
所有漏洞检测均基于正则模式匹配，不引入额外依赖。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from laap.sandbox._types import ProjectSnapshot, SandboxConfig, Suggestion
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.container import CognitiveSandbox
from laap.sandbox.skill_library import Skill, SkillLibrary


# ============================================================
# 漏洞检测正则模式定义
# ============================================================

# SQL 注入：字符串拼接构造 SQL 语句（execute / query 等调用）
_SQL_INJECTION_PATTERNS = [
    re.compile(r'execute\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\b.*?["\']\s*\+', re.IGNORECASE),
    re.compile(r'execute\s*\(\s*f["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\b', re.IGNORECASE),
    re.compile(r'execute\s*\(\s*["\'].*?%s.*?["\']\s*%', re.IGNORECASE),
    re.compile(r'cursor\.\w+\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE)\b.*?["\']\s*\+', re.IGNORECASE),
]

# XSS：未转义的输出（innerHTML、document.write、render_template_string 等）
_XSS_PATTERNS = [
    re.compile(r'\.innerHTML\s*=\s*[^"\'<]', re.IGNORECASE),
    re.compile(r'document\.write\s*\(', re.IGNORECASE),
    re.compile(r'render_template_string\s*\(', re.IGNORECASE),
    re.compile(r'\|\s*safe\b', re.IGNORECASE),  # Jinja2 |safe 过滤器
]

# 硬编码密钥：API key、密码、token 等
_HARDCODED_SECRET_PATTERNS = [
    re.compile(r'\b(?:api[_-]?key|apikey)\s*=\s*["\'][A-Za-z0-9_\-]{8,}["\']', re.IGNORECASE),
    re.compile(r'\bpassword\s*=\s*["\'][^"\']{4,}["\']', re.IGNORECASE),
    re.compile(r'\b(?:access[_-]?token|auth[_-]?token|secret[_-]?key)\s*=\s*["\'][A-Za-z0-9_\-]{8,}["\']', re.IGNORECASE),
    re.compile(r'\b(?:AWS_SECRET_ACCESS_KEY|PRIVATE_KEY)\s*=\s*["\'][^"\']+["\']', re.IGNORECASE),
]

# 路径遍历：用户输入拼接 ../ 拼接
_PATH_TRAVERSAL_PATTERNS = [
    re.compile(r'open\s*\(\s*[^)]*?\.\./', re.IGNORECASE),
    re.compile(r'os\.path\.join\s*\([^)]*?\.\./', re.IGNORECASE),
    re.compile(r'\.\.\/.*?\+', re.IGNORECASE),
]

# 已知 CVE 漏洞依赖模式（package_name, safe_version, vulnerability, severity）
# 当检测到的版本严格低于 safe_version 时，视为存在漏洞。
# 仅做模式匹配示例，非完整 CVE 库。
_KNOWN_VULNERABLE_DEPS = [
    ("requests", "2.25.0", "CVE-2023-32681: Requests leaking Proxy-Authorization", "high"),
    ("django", "3.2.0", "Multiple Django CVEs in versions < 3.2", "critical"),
    ("flask", "1.0", "Flask < 1.0 multiple security issues", "high"),
    ("pyyaml", "5.4", "CVE-2020-14343: PyYAML arbitrary code execution", "critical"),
    ("jinja2", "2.11.3", "CVE-2020-28493: Jinja2 ReDoS", "high"),
    ("urllib3", "1.26.5", "CVE-2021-33503: urllib3 ReDoS", "high"),
    ("cryptography", "3.3.2", "CVE-2020-36177: cryptography weak digest", "medium"),
    ("sqlalchemy", "1.3.0", "SQLAlchemy < 1.3 multiple issues", "medium"),
]


class SecurityAgent(CognitiveSandbox):
    """安全审计数字生命体——负责系统安全扫描、漏洞检测及安全建议生成。

    继承 CognitiveSandbox，特化角色为"security_watcher"。

    核心职责：
    1. 静态扫描代码漏洞（SQL 注入、XSS、硬编码密钥、路径遍历）
    2. 检查依赖中已知的 CVE 漏洞
    3. 输出按严重程度排序的安全建议
    4. 监控项目整体安全态势

    注册的技能：
    - "security_scan" — 安全扫描
    - "vulnerability_detect" — 漏洞检测

    用法：
        event_bus = ColonyEventBus()
        skill_lib = SkillLibrary()
        security = SecurityAgent(
            sandbox_id="sb-security-001",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        snapshot = perception.perceive(full=True)
        security.perceive(snapshot)
        suggestion = security.think()
    """

    AGENT_ID = "security-agent"
    ROLE = "security_watcher"

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
            name="SecurityAgent",
            role=self.ROLE,
            skill_library=skill_library,
            event_bus=event_bus,
            config=config,
        )

        # 类标识（与文档接口对齐）
        self.agent_id = self.AGENT_ID
        self.skills = ["security_scan", "vulnerability_detect"]

        self._register_security_skills()

    def _register_security_skills(self) -> None:
        """注册安全审计特有的技能到 skill_library。"""
        security_skills = [
            Skill(
                name="security_scan",
                description="对代码进行静态安全扫描，识别 SQL 注入/XSS/硬编码密钥/路径遍历",
                category="security",
                tags=["security_watcher", "static-analysis"],
            ),
            Skill(
                name="vulnerability_detect",
                description="基于已知 CVE 模式匹配检测依赖漏洞",
                category="security",
                tags=["security_watcher", "dependencies"],
            ),
        ]
        for skill in security_skills:
            self.skill_library.register(skill)

    # ------------------------------------------------------------
    # 认知循环
    # ------------------------------------------------------------

    def think(self) -> Optional[Suggestion]:
        """安全审计特化思考循环。

        基于 world_model 中的项目快照，识别：
        1. 代码漏洞（按严重程度排序）
        2. 依赖漏洞（基于已知 CVE 模式）
        3. 整体安全态势评估

        返回：
            优先级最高的安全建议（或 None）
        """
        from laap.sandbox.resource_budget import DegradationLevel

        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        # 收集代码漏洞
        code_vulnerabilities = self._scan_codebase_vulnerabilities(snapshot)
        # 收集依赖漏洞
        dependency_vulns = self._check_snapshot_dependencies(snapshot)

        # 优先处理 critical 级别
        critical_vulns = [v for v in code_vulnerabilities if v.get('severity') == 'critical']
        critical_deps = [v for v in dependency_vulns if v.get('severity') == 'critical']
        if critical_vulns:
            worst = critical_vulns[0]
            return Suggestion(
                title=f"修复严重漏洞: {worst['type']}",
                description=f"文件 {worst['file']} 第 {worst['line']} 行检测到 {worst['type']} 漏洞。"
                           f"修复建议: {worst.get('fix', '审查相关代码')}",
                priority="critical",
                relevance=0.95,
                category="security",
                target_file=worst['file'],
                source_sandbox=self.sandbox_id,
                actions=["立即审查漏洞位置", "应用推荐修复方案", "增加对应单元测试", "复查相似代码"],
            )
        if critical_deps:
            worst = critical_deps[0]
            return Suggestion(
                title=f"升级有严重漏洞的依赖: {worst['package']}",
                description=f"依赖 {worst['package']} 存在严重漏洞: {worst['vulnerability']}",
                priority="critical",
                relevance=0.9,
                category="dependency",
                source_sandbox=self.sandbox_id,
                actions=["确认当前版本", "升级到安全版本", "运行测试验证兼容性", "提交变更"],
            )

        # 处理 high 级别
        high_vulns = [v for v in code_vulnerabilities if v.get('severity') == 'high']
        high_deps = [v for v in dependency_vulns if v.get('severity') == 'high']
        if high_vulns:
            worst = high_vulns[0]
            return Suggestion(
                title=f"修复高危漏洞: {worst['type']}",
                description=f"文件 {worst['file']} 第 {worst['line']} 行存在高危漏洞。"
                           f"修复建议: {worst.get('fix', '审查相关代码')}",
                priority="high",
                relevance=0.8,
                category="security",
                target_file=worst['file'],
                source_sandbox=self.sandbox_id,
                actions=["审查漏洞位置", "应用推荐修复方案", "补充测试"],
            )
        if high_deps:
            worst = high_deps[0]
            return Suggestion(
                title=f"升级有漏洞的依赖: {worst['package']}",
                description=f"依赖 {worst['package']} 存在漏洞: {worst['vulnerability']}",
                priority="high",
                relevance=0.75,
                category="dependency",
                source_sandbox=self.sandbox_id,
                actions=["确认当前版本", "升级到安全版本", "验证兼容性"],
            )

        # 处理 medium 级别
        medium_vulns = [v for v in code_vulnerabilities if v.get('severity') == 'medium']
        if medium_vulns:
            worst = medium_vulns[0]
            return Suggestion(
                title=f"修复中危漏洞: {worst['type']}",
                description=f"文件 {worst['file']} 第 {worst['line']} 行存在中危漏洞",
                priority="medium",
                relevance=0.6,
                category="security",
                target_file=worst['file'],
                source_sandbox=self.sandbox_id,
                actions=["审查相关代码", "应用修复方案"],
            )

        # 存在漏洞但级别较低时给汇总建议
        if code_vulnerabilities or dependency_vulns:
            return Suggestion(
                title=f"共发现 {len(code_vulnerabilities) + len(dependency_vulns)} 个低危安全问题",
                description="建议定期审查并修复低危安全问题，保持良好的安全态势",
                priority="low",
                relevance=0.4,
                category="security",
                source_sandbox=self.sandbox_id,
                actions=["汇总低危问题", "排期修复", "持续监控"],
            )

        return None

    # ------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------

    def scan_security(self, file_contents: Dict[str, str]) -> List[Dict[str, Any]]:
        """检测已知漏洞模式。

        扫描内容包含以下类别：
        - SQL 注入（字符串拼接 SQL 语句）
        - XSS（未转义输出）
        - 硬编码密钥（API key、密码、token）
        - 路径遍历（../ 拼接）

        Args:
            file_contents: 文件路径到文件内容的映射

        返回:
            [{"type": "sql_injection", "file": "...", "line": 42,
              "severity": "high", "fix": "..."}]
        """
        results: List[Dict[str, Any]] = []

        for file_path, content in file_contents.items():
            lines = content.splitlines()
            for line_no, line_text in enumerate(lines, start=1):
                # SQL 注入检测
                for pattern in _SQL_INJECTION_PATTERNS:
                    if pattern.search(line_text):
                        results.append({
                            "type": "sql_injection",
                            "file": file_path,
                            "line": line_no,
                            "severity": "high",
                            "snippet": line_text.strip()[:120],
                            "fix": "使用参数化查询（占位符）替代字符串拼接",
                        })
                        break

                # XSS 检测
                for pattern in _XSS_PATTERNS:
                    if pattern.search(line_text):
                        results.append({
                            "type": "xss",
                            "file": file_path,
                            "line": line_no,
                            "severity": "medium",
                            "snippet": line_text.strip()[:120],
                            "fix": "对输出进行 HTML 转义，避免直接插入不可信数据",
                        })
                        break

                # 硬编码密钥检测
                for pattern in _HARDCODED_SECRET_PATTERNS:
                    if pattern.search(line_text):
                        results.append({
                            "type": "hardcoded_secret",
                            "file": file_path,
                            "line": line_no,
                            "severity": "critical",
                            "snippet": line_text.strip()[:120],
                            "fix": "从环境变量或密钥管理服务中读取，禁止硬编码",
                        })
                        break

                # 路径遍历检测
                for pattern in _PATH_TRAVERSAL_PATTERNS:
                    if pattern.search(line_text):
                        results.append({
                            "type": "path_traversal",
                            "file": file_path,
                            "line": line_no,
                            "severity": "high",
                            "snippet": line_text.strip()[:120],
                            "fix": "对路径输入进行规范化与白名单校验，禁止 ../ 拼接",
                        })
                        break

        # 按严重程度排序：critical > high > medium > low
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        results.sort(key=lambda r: severity_order.get(r['severity'], 99))
        return results

    def check_dependencies(self, dependencies: List[str]) -> List[Dict[str, Any]]:
        """依赖漏洞检查（基于已知 CVE 模式匹配）。

        通过将检测到的版本与已知漏洞依赖列表中的安全版本进行元组比较，
        识别存在漏洞的依赖。比较使用 Python 内置元组比较，不引入新依赖。

        Args:
            dependencies: 依赖项列表，格式如 ["requests==2.20.0", "django>=3.0"]

        返回:
            [{"package": "...", "vulnerability": "...", "severity": "critical"}]
        """
        results: List[Dict[str, Any]] = []

        for dep in dependencies:
            package_name, version = self._parse_dependency_spec(dep)
            if not package_name:
                continue

            for known_pkg, safe_version, vuln_desc, severity in _KNOWN_VULNERABLE_DEPS:
                if known_pkg.lower() != package_name.lower():
                    continue
                # 仅当可解析出当前版本且严格低于安全版本时，视为存在漏洞
                if version and self._is_version_below(version, safe_version):
                    results.append({
                        "package": package_name,
                        "current_version": version,
                        "safe_version": safe_version,
                        "vulnerability": vuln_desc,
                        "severity": severity,
                        "fix": f"升级 {package_name} 到 {safe_version} 或更高版本",
                    })
                    break

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        results.sort(key=lambda r: severity_order.get(r['severity'], 99))
        return results

    # ------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------

    def _scan_codebase_vulnerabilities(self, snapshot: ProjectSnapshot) -> List[Dict[str, Any]]:
        """扫描快照中所有源码文件的漏洞。"""
        file_contents: Dict[str, str] = {}
        for file_path in snapshot.file_tree.file_paths:
            # 仅扫描源码文件
            if not self._is_source_file(file_path):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    file_contents[file_path] = f.read()
            except (OSError, UnicodeDecodeError):
                continue
        return self.scan_security(file_contents)

    def _check_snapshot_dependencies(self, snapshot: ProjectSnapshot) -> List[Dict[str, Any]]:
        """从快照的 DependencyReport 提取依赖列表并检测漏洞。"""
        dep_specs: List[str] = []
        for dep in snapshot.dependencies.direct:
            name = dep.get('name', '')
            version = dep.get('version', '')
            if name:
                dep_specs.append(f"{name}=={version}" if version else name)
        # 包含过期的依赖（已知有更新版本，更可能有漏洞）
        for dep in snapshot.dependencies.outdated:
            name = dep.get('name', '')
            version = dep.get('version', '')
            if name:
                dep_specs.append(f"{name}=={version}" if version else name)
        return self.check_dependencies(dep_specs)

    @staticmethod
    def _is_source_file(file_path: str) -> bool:
        """判断是否为需要扫描的源码文件。"""
        source_exts = ('.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.java', '.go', '.rb', '.php')
        return file_path.endswith(source_exts)

    @staticmethod
    def _parse_dependency_spec(dep: str) -> tuple:
        """解析依赖规范，返回 (package_name, version)。

        支持 "requests==2.20.0"、"requests>=2.0"、"requests" 等格式。
        """
        if not dep:
            return "", ""
        # 匹配包名与版本（支持 ==, >=, <=, ~=, >, <）
        match = re.match(r'^\s*([A-Za-z0-9_][A-Za-z0-9_\-.]*)\s*(?:==|>=|<=|~=|>|<)?\s*([0-9][0-9a-zA-Z.\-]*)?', dep)
        if not match:
            return dep.strip(), ""
        return match.group(1), match.group(2) or ""

    @staticmethod
    def _is_version_below(current: str, threshold: str) -> bool:
        """比较两个版本字符串，current 严格低于 threshold 时返回 True。

        使用元组比较实现语义化版本判断（仅比较数字部分），不引入新依赖。
        例如 "2.20.0" < "2.25.0" 为 True，"2.25.0" < "2.25.0" 为 False。
        """
        def _to_tuple(ver: str) -> tuple:
            # 仅提取数字部分用于比较，忽略 "rc1" / "beta" 等后缀
            parts = re.findall(r'\d+', ver)
            return tuple(int(p) for p in parts)
        try:
            return _to_tuple(current) < _to_tuple(threshold)
        except (ValueError, TypeError):
            return False


__all__ = ["SecurityAgent"]
