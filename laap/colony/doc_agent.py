"""文档维护数字生命体——负责文档自动生成、更新及知识检索功能。

DocAgent 继承 CognitiveSandbox，特化角色为"doc_maintainer"，
专注于从代码 docstring 生成 API 文档、检测文档与代码不一致、
并维护 README 的内容时效性。
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


# README 文件常见命名
_README_FILENAMES = ("README.md", "README.rst", "README.txt", "README", "readme.md")

# 文档文件扩展名
_DOC_EXTENSIONS = ('.md', '.rst', '.txt', '.adoc')


class DocAgent(CognitiveSandbox):
    """文档维护数字生命体——负责文档自动生成、更新及知识检索功能。

    继承 CognitiveSandbox，特化角色为"doc_maintainer"。

    核心职责：
    1. 从代码 docstring 生成 API 文档
    2. 检测文档与代码的不一致（签名变更未更新文档）
    3. 维护 README 的时效性
    4. 监控文档完整性

    注册的技能：
    - "doc_generate" — 文档生成
    - "doc_update" — 文档更新
    - "readme_maintain" — README 维护

    用法：
        event_bus = ColonyEventBus()
        skill_lib = SkillLibrary()
        doc_agent = DocAgent(
            sandbox_id="sb-doc-001",
            skill_library=skill_lib,
            event_bus=event_bus,
        )
        snapshot = perception.perceive(full=True)
        doc_agent.perceive(snapshot)
        suggestion = doc_agent.think()
    """

    AGENT_ID = "doc-agent"
    ROLE = "doc_maintainer"

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
            name="DocAgent",
            role=self.ROLE,
            skill_library=skill_library,
            event_bus=event_bus,
            config=config,
        )

        # 类标识（与文档接口对齐）
        self.agent_id = self.AGENT_ID
        self.skills = ["doc_generate", "doc_update", "readme_maintain"]

        self._register_doc_skills()

    def _register_doc_skills(self) -> None:
        """注册文档维护特有的技能到 skill_library。"""
        doc_skills = [
            Skill(
                name="doc_generate",
                description="从代码 docstring 自动生成 API 文档",
                category="doc",
                tags=["doc_maintainer", "generation"],
            ),
            Skill(
                name="doc_update",
                description="检测文档与代码不一致并建议更新",
                category="doc",
                tags=["doc_maintainer", "consistency"],
            ),
            Skill(
                name="readme_maintain",
                description="维护 README 时效性",
                category="doc",
                tags=["doc_maintainer", "readme"],
            ),
        ]
        for skill in doc_skills:
            self.skill_library.register(skill)

    # ------------------------------------------------------------
    # 认知循环
    # ------------------------------------------------------------

    def think(self) -> Optional[Suggestion]:
        """文档维护特化思考循环。

        基于 world_model 中的项目快照，识别：
        1. README 缺失或过期
        2. 代码与文档不一致
        3. 关键模块缺少 docstring

        返回：
            优先级最高的文档建议（或 None）
        """
        from laap.sandbox.resource_budget import DegradationLevel

        effective_degradation = self.resource_budget.get_effective_degradation()
        if effective_degradation == DegradationLevel.CACHED:
            return None

        snapshot = getattr(self.world_model, '_project_snapshot', None)
        if not snapshot:
            return None

        readme_info = self._locate_readme(snapshot)
        missing_doc_modules = self._find_modules_missing_docstrings(snapshot)

        # 优先级 1: README 缺失
        if not readme_info['exists']:
            return Suggestion(
                title="项目缺少 README 文档",
                description="未找到 README 文件，建议创建以提升项目可维护性与协作效率",
                priority="high",
                relevance=0.85,
                category="doc",
                source_sandbox=self.sandbox_id,
                actions=["撰写项目简介", "记录安装与使用步骤", "添加示例", "提交 README.md"],
            )

        # 优先级 2: 关键模块缺少 docstring
        if missing_doc_modules:
            worst = missing_doc_modules[0]
            return Suggestion(
                title=f"补充模块文档: {os.path.basename(worst['path'])}",
                description=f"模块 {worst['path']} 有 {worst['missing_count']} 个公开函数/类缺少 docstring",
                priority="medium",
                relevance=0.7,
                category="doc",
                target_file=worst['path'],
                source_sandbox=self.sandbox_id,
                actions=[
                    "为公开类添加 docstring",
                    "为公开函数添加 docstring",
                    "包含参数与返回值说明",
                ],
            )

        # 优先级 3: README 可能过期（最近文件改动多于 README 改动）
        if readme_info.get('potentially_outdated', False):
            return Suggestion(
                title="README 可能已过期",
                description="README 文件的更新时间显著早于大量源码文件，建议核对内容时效性",
                priority="low",
                relevance=0.5,
                category="doc",
                target_file=readme_info['path'],
                source_sandbox=self.sandbox_id,
                actions=["核对 README 与代码现状", "更新功能列表", "更新使用说明"],
            )

        return None

    # ------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------

    def generate_api_doc(self, source_file: str, content: str) -> str:
        """从代码 docstring 生成 API 文档。

        解析源码 AST，提取模块/类/函数的 docstring 并组织为 Markdown 格式。

        Args:
            source_file: 源文件路径（用于推断模块名）
            content: 源文件文本内容

        返回:
            Markdown 格式的 API 文档字符串
        """
        module_name = os.path.basename(source_file)
        if module_name.endswith('.py'):
            module_name = module_name[:-3]

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return f"# {module_name}\n\n> 无法解析此模块（语法错误）\n"

        # 模块级 docstring
        module_doc = ast.get_docstring(tree) or ""

        lines: List[str] = []
        lines.append(f"# 模块: `{module_name}`")
        lines.append("")
        if module_doc:
            lines.append(module_doc)
            lines.append("")

        # 提取类
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        for cls in classes:
            if cls.name.startswith('_'):
                continue
            cls_doc = ast.get_docstring(cls) or ""
            lines.append(f"## 类 `{cls.name}`")
            lines.append("")
            if cls_doc:
                lines.append(cls_doc)
                lines.append("")
            # 列出类的公开方法
            for node in cls.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith('_') and node.name != '__init__':
                        continue
                    self._append_function_doc(lines, node, level=3)

        # 提取模块级函数
        functions = [
            n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('_')
        ]
        for func in functions:
            self._append_function_doc(lines, func, level=2)

        if not classes and not functions and not module_doc:
            lines.append("> 此模块未发现可文档化的公开 API。")
            lines.append("")

        return "\n".join(lines)

    def check_doc_consistency(self, code_files: Dict[str, str],
                              doc_files: Dict[str, str]) -> List[Dict[str, Any]]:
        """检测文档与代码不一致。

        Args:
            code_files: 代码文件路径到内容的映射
            doc_files: 文档文件路径到内容的映射

        返回:
            [{"file": "...", "issue": "签名变更未更新文档", "severity": "medium"}]
        """
        issues: List[Dict[str, Any]] = []

        # 从代码中提取公开符号（函数/类名）
        code_symbols: Dict[str, List[str]] = {}
        for code_path, content in code_files.items():
            if not code_path.endswith('.py'):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            module_name = os.path.basename(code_path)
            if module_name.endswith('.py'):
                module_name = module_name[:-3]
            symbols: List[str] = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                    symbols.append(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
                    symbols.append(node.name)
            code_symbols[module_name] = symbols

        # 合并所有文档内容
        doc_text = "\n".join(doc_files.values())

        # 检查每个代码模块的符号是否在文档中出现
        for module_name, symbols in code_symbols.items():
            for symbol in symbols:
                if symbol not in doc_text:
                    # 仅当代码模块有较多符号时才提示（避免噪声）
                    if len(symbols) >= 2:
                        issues.append({
                            "file": module_name,
                            "issue": f"公开符号 '{symbol}' 未在文档中提及（签名可能已变更）",
                            "severity": "medium",
                        })

        # 检查文档中提到的代码模块是否还存在
        for doc_path, doc_content in doc_files.items():
            # 提取文档中可能引用的代码标识（如反引号包裹）
            referenced = re.findall(r'`([a-zA-Z_][a-zA-Z0-9_]*)`', doc_content)
            for ref in referenced:
                if ref in code_symbols:
                    continue
                # 排除常见非代码引用
                if ref in {'True', 'False', 'None', 'self', 'cls'}:
                    continue
                # 文档引用的符号在代码中不存在（可能代码已删除/重命名）
                if len(referenced) >= 5:
                    issues.append({
                        "file": doc_path,
                        "issue": f"文档引用的符号 '{ref}' 在代码中不存在（可能已重命名或删除）",
                        "severity": "medium",
                    })

        # 按严重程度排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        issues.sort(key=lambda r: severity_order.get(r['severity'], 99))
        return issues

    def suggest_readme_update(self, project_info: Dict[str, Any]) -> Suggestion:
        """README 维护建议。

        Args:
            project_info: 项目信息字典，可包含以下字段：
                - name: 项目名
                - description: 项目描述
                - has_install_section: 是否有安装说明
                - has_usage_section: 是否有使用示例
                - has_license_section: 是否有许可证
                - last_updated_at: README 最近更新时间戳

        返回:
            README 更新建议
        """
        missing_sections: List[str] = []
        if not project_info.get('has_install_section'):
            missing_sections.append("安装说明")
        if not project_info.get('has_usage_section'):
            missing_sections.append("使用示例")
        if not project_info.get('has_license_section'):
            missing_sections.append("许可证信息")

        project_name = project_info.get('name', '本项目')
        description = project_info.get('description', '')

        if missing_sections:
            actions = [f"补充 {section}" for section in missing_sections]
            actions.append("提交更新")
            return Suggestion(
                title=f"完善 README: {project_name}",
                description=f"README 缺少以下部分: {', '.join(missing_sections)}",
                priority="medium",
                relevance=0.7,
                category="doc",
                source_sandbox=self.sandbox_id,
                actions=actions,
            )

        # README 完整但提供优化建议
        return Suggestion(
            title=f"优化 README: {project_name}",
            description="README 内容完整，建议补充贡献指南、变更日志等部分以提升协作体验"
                       + (f"（项目描述: {description[:80]}）" if description else ""),
            priority="low",
            relevance=0.4,
            category="doc",
            source_sandbox=self.sandbox_id,
            actions=["补充贡献指南", "添加变更日志", "增加徽章信息"],
        )

    # ------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------

    def _append_function_doc(self, lines: List[str],
                             node: Any, level: int = 2) -> None:
        """将函数 AST 节点的文档追加到 Markdown 行列表。"""
        prefix = "#" * level
        # 构造函数签名
        args = self._format_function_args(node)
        lines.append(f"{prefix} 函数 `{node.name}({args})`")
        lines.append("")
        doc = ast.get_docstring(node) or ""
        if doc:
            lines.append(doc)
            lines.append("")

    @staticmethod
    def _format_function_args(node: Any) -> str:
        """格式化函数参数列表。"""
        args_list = []
        # 普通参数
        for arg in node.args.args:
            args_list.append(arg.arg)
        # *args
        if node.args.vararg:
            args_list.append(f"*{node.args.vararg.arg}")
        # **kwargs
        if node.args.kwarg:
            args_list.append(f"**{node.args.kwarg.arg}")
        return ", ".join(args_list)

    def _locate_readme(self, snapshot: ProjectSnapshot) -> Dict[str, Any]:
        """定位项目中的 README 文件并判断是否可能过期。"""
        info: Dict[str, Any] = {
            "exists": False,
            "path": None,
            "potentially_outdated": False,
        }
        readme_path = None
        for path in snapshot.file_tree.file_paths:
            basename = os.path.basename(path)
            if basename in _README_FILENAMES:
                readme_path = path
                break

        if readme_path is None:
            return info

        info['exists'] = True
        info['path'] = readme_path

        # 通过比较 README 与源码文件的 mtime 判断时效性
        try:
            readme_mtime = os.path.getmtime(readme_path)
        except OSError:
            return info

        # 统计源码文件中比 README 新的数量
        newer_count = 0
        for path in snapshot.file_tree.file_paths:
            if path == readme_path or not path.endswith('.py'):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime > readme_mtime:
                newer_count += 1

        # 启发式：超过 5 个源码文件比 README 新则视为可能过期
        if newer_count > 5:
            info['potentially_outdated'] = True
        return info

    def _find_modules_missing_docstrings(self, snapshot: ProjectSnapshot) -> List[Dict[str, Any]]:
        """查找缺少 docstring 的模块。"""
        missing: List[Dict[str, Any]] = []

        for file_path in snapshot.file_tree.file_paths:
            if not file_path.endswith('.py'):
                continue
            basename = os.path.basename(file_path)
            # 跳过测试与 __init__ 文件
            if basename.startswith('test_') or basename == '__init__.py':
                continue
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            missing_count = 0
            # 检查模块 docstring
            if not ast.get_docstring(tree):
                missing_count += 1
            # 检查公开类与函数
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                    if not ast.get_docstring(node):
                        missing_count += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith('_'):
                        continue
                    if not ast.get_docstring(node):
                        missing_count += 1

            if missing_count > 0:
                missing.append({
                    "path": file_path,
                    "missing_count": missing_count,
                })

        missing.sort(key=lambda x: -x['missing_count'])
        return missing


__all__ = ["DocAgent"]
