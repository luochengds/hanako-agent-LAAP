"""项目状态感知器

ProjectPerception 负责扫描项目并构建 ProjectSnapshot，
支持全量扫描与增量更新（增量更新在 Task 9 实现）。
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import time
import tomllib
from typing import Any, Callable, Dict, List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEvent = object
    FileSystemEventHandler = object

from laap.sandbox._types import BuildState, DependencyReport, FileTreeState, GitState, ProjectSnapshot, TechDebtReport, TestState


class ProjectPerception:
    """项目状态感知器——扫描项目并构建 ProjectSnapshot。

    支持全量扫描与增量更新（增量更新在 Task 9 实现）。

    用法:
        perception = ProjectPerception(root_path="/path/to/project")
        snapshot = perception.perceive(full=True)
        print(snapshot.git_state.current_branch)
    """

    def __init__(self, root_path: str, max_files: int = 1000,
                 skip_dirs: Optional[List[str]] = None):
        self.root_path = os.path.abspath(root_path)
        self.max_files = max_files
        self.skip_dirs = set(skip_dirs or [
            '.git', '__pycache__', '.pytest_cache', 'node_modules',
            'venv', '.venv', '.env', 'dist', 'build', '.next',
        ])
        self._cache: Optional[ProjectSnapshot] = None
        self._cache_time: float = 0.0
        self._cache_ttl_sec: float = 30.0
        self._scan_count: int = 0
        self._cache_hit_count: int = 0
        self._cache_miss_count: int = 0
        self._watcher: Optional[Observer] = None
        self._watch_handler: Optional[FileSystemEventHandler] = None
        self._is_watching: bool = False
        self._debounce_timers: Dict[str, threading.Timer] = {}

    def perceive(self, full: bool = False) -> ProjectSnapshot:
        """感知项目状态。"""
        import sys as _sys
        if not full and self._cache is not None:
            if time.time() - self._cache_time < self._cache_ttl_sec:
                self._cache_hit_count += 1
                return self._cache

        self._cache_miss_count += 1
        self._scan_count += 1
        file_tree = self._scan_files()
        tech_debt = self._scan_tech_debt(file_tree)
        snapshot = ProjectSnapshot(
            root_path=self.root_path,
            git_state=self._scan_git(),
            file_tree=file_tree,
            tech_debt=tech_debt,
            test_state=self._scan_tests(),
            build_state=self._scan_build(),
            dependencies=self._scan_dependencies(),
            timestamp=time.time(),
        )
        self._cache = snapshot
        self._cache_time = time.time()
        return snapshot

    def invalidate_cache(self) -> None:
        """使缓存失效（强制下次 perceive 全量扫描）。"""
        self._cache = None
        self._cache_time = 0.0

    def start_watching(self) -> None:
        """启动文件监听。

        使用 watchdog 库监听文件变更事件：
        - 文件创建/修改/删除
        - 目录创建/删除

        配置 debounce（防抖）：1 秒
        事件发生后调用 `_on_file_changed()` 处理增量更新。
        """
        if not WATCHDOG_AVAILABLE:
            return

        if self._is_watching:
            return

        self._watch_handler = self._create_file_change_handler()
        self._watcher = Observer()
        self._watcher.schedule(self._watch_handler, self.root_path, recursive=True)
        self._watcher.start()
        self._is_watching = True

    def stop_watching(self) -> None:
        """停止文件监听。"""
        if not self._is_watching or self._watcher is None:
            return

        self._watcher.stop()
        self._watcher.join()
        self._watcher = None
        self._watch_handler = None
        self._is_watching = False

    def _create_file_change_handler(self) -> FileSystemEventHandler:
        """创建文件变更处理器。"""
        perception = self

        class FileChangeHandler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                perception._debounced_file_change(event)

        return FileChangeHandler()

    def _debounced_file_change(self, event: FileSystemEvent) -> None:
        """带防抖的文件变更处理。"""
        timer_key = str(id(event)) + "_" + str(time.time())[:10]

        if timer_key in self._debounce_timers:
            self._debounce_timers[timer_key].cancel()

        timer = threading.Timer(1.0, self._on_file_changed, args=(event,))
        self._debounce_timers[timer_key] = timer
        timer.start()

    def _on_file_changed(self, event: FileSystemEvent) -> None:
        """处理文件变更事件（经 debounce 后）。

        增量更新逻辑：
        - 文件保存 → 更新 file_tree 单项 + 重新扫描该文件的 tech_debt
        - git commit → 重扫 git_state
        - 构建完成 → 重扫 build_state
        """
        cache = self._cache
        if cache is None:
            return

        rel_path = os.path.relpath(event.src_path, self.root_path)

        if ".git" in rel_path:
            cache.git_state = self._scan_git()
        elif any(d in rel_path for d in ["dist", "build", "target"]):
            cache.build_state = self._scan_build()
        elif event.is_directory:
            pass
        elif event.event_type == "deleted":
            if rel_path in cache.file_tree.file_paths:
                cache.file_tree.file_paths.remove(rel_path)
                cache.file_tree.total_files -= 1
            if rel_path in cache.tech_debt.by_file:
                del cache.tech_debt.by_file[rel_path]
        elif event.event_type in ["created", "modified"]:
            if os.path.exists(event.src_path):
                self._update_file_in_cache(rel_path, event.src_path)

        self.invalidate_cache()

    def _update_file_in_cache(self, rel_path: str, abs_path: str) -> None:
        """更新缓存中单个文件的信息。"""
        cache = self._cache
        if cache is None:
            return

        ext = os.path.splitext(os.path.basename(abs_path))[1].lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".md": "markdown",
            ".txt": "text",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".xml": "xml",
            ".html": "html",
            ".css": "css",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".rb": "ruby",
            ".php": "php",
            ".sql": "sql",
            ".sh": "shell",
            ".bat": "batch",
            ".gitignore": "gitignore",
            ".gitkeep": "gitkeep",
        }
        language = lang_map.get(ext, ext.lstrip(".") or "unknown")
        lines = self._count_lines(abs_path)

        if rel_path not in cache.file_tree.file_paths:
            cache.file_tree.file_paths.append(rel_path)
            cache.file_tree.total_files += 1
            cache.file_tree.languages[language] = (
                cache.file_tree.languages.get(language, 0) + 1
            )

        cache.file_tree.total_lines += lines

        code_extensions = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java",
                          ".cpp", ".c", ".rb", ".php", ".sh", ".html", ".css"}
        if ext in code_extensions:
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                marker_pattern = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s]*(.+)?")
                matches = marker_pattern.findall(content)
                count = len(matches)
                cache.tech_debt.by_file[rel_path] = count

                for marker_type, _ in matches:
                    marker_type_upper = marker_type.upper()
                    if marker_type_upper == "TODO":
                        cache.tech_debt.todo_count += 1
                    elif marker_type_upper == "FIXME":
                        cache.tech_debt.fixme_count += 1
                    elif marker_type_upper == "XXX":
                        cache.tech_debt.xxx_count += 1
                    elif marker_type_upper == "HACK":
                        cache.tech_debt.todo_count += 1

                cache.tech_debt.total_markers = (
                    cache.tech_debt.todo_count
                    + cache.tech_debt.fixme_count
                    + cache.tech_debt.xxx_count
                )
            except Exception:
                pass

    def _scan_git(self) -> GitState:
        """扫描 git 状态。

        调用命令：
        - git rev-parse --abbrev-ref HEAD → 当前分支
        - git log -n 50 --pretty=format:'%H|%an|%ad|%s' --date=iso → 最近 50 提交
        - git status --porcelain → 未提交文件计数
        - git branch --list → 本地分支列表
        - git remote -v → 远程仓库
        - git log -1 --format=%ct → 最后提交时间戳

        失败时（非 git 仓库、git 命令不可用）返回空 GitState，不抛异常。
        """
        result = GitState()

        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                result.current_branch = proc.stdout.strip()
        except Exception:
            pass

        try:
            proc = subprocess.run(
                ["git", "log", "-n", "50", "--pretty=format:%H|%an|%ad|%s", "--date=iso"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                result.recent_commits = self._parse_git_log(proc.stdout)
        except Exception:
            pass

        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                result.uncommitted_count = len([line for line in proc.stdout.splitlines() if line.strip()])
        except Exception:
            pass

        try:
            proc = subprocess.run(
                ["git", "branch", "--list"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                result.branches = [
                    line.strip().lstrip("* ")
                    for line in proc.stdout.splitlines()
                    if line.strip()
                ]
        except Exception:
            pass

        try:
            proc = subprocess.run(
                ["git", "remote", "-v"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                result.remotes = self._parse_git_remotes(proc.stdout)
        except Exception:
            pass

        try:
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                ts = proc.stdout.strip()
                if ts:
                    result.last_commit_at = float(ts)
        except Exception:
            pass

        return result

    def _parse_git_log(self, log_output: str) -> List[Dict[str, Any]]:
        """解析 git log 输出。返回 [{hash, author, date, message}, ...]"""
        commits = []
        for line in log_output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0].strip(),
                    "author": parts[1].strip(),
                    "date": parts[2].strip(),
                    "message": parts[3].strip(),
                })
        return commits

    def _parse_git_remotes(self, remote_output: str) -> List[str]:
        """解析 git remote -v 输出。返回去重后的 remote URL 列表。"""
        urls = set()
        for line in remote_output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                urls.add(parts[1])
        return sorted(urls)

    def _scan_files(self) -> FileTreeState:
        """扫描文件树状态。
        
        遍历目录树（尊重 .gitignore），统计：
        - 文件总数
        - 代码总行数
        - 语言分布（按扩展名）
        - 文件路径列表
        - 最大文件列表（Top-10）
        - 模块结构（按目录分组）
        
        Returns:
            FileTreeState 数据类
        """
        result = FileTreeState()
        gitignore_patterns = self._load_gitignore()
        
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".md": "markdown",
            ".txt": "text",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".xml": "xml",
            ".html": "html",
            ".css": "css",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".rb": "ruby",
            ".php": "php",
            ".sql": "sql",
            ".sh": "shell",
            ".bat": "batch",
            ".gitignore": "gitignore",
            ".gitkeep": "gitkeep",
        }
        
        file_info = []
        
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            # 快速修剪: 隐藏目录 + 重型目录 + gitignore
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            dirnames[:] = [d for d in dirnames if d not in self.skip_dirs]
            dirnames[:] = [d for d in dirnames if not self._is_ignored(d, gitignore_patterns)]

            for filename in filenames:
                if filename.startswith('.'):
                    continue
                if self._is_ignored(filename, gitignore_patterns):
                    continue
                if self.max_files > 0 and result.total_files >= self.max_files:
                    file_info.sort(key=lambda x: x["lines"], reverse=True)
                    result.largest_files = file_info[:10]
                    result.module_structure = self._build_module_structure(result.file_paths)
                    return result

                filepath = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(filepath, self.root_path)
                
                ext = os.path.splitext(filename)[1].lower()
                language = lang_map.get(ext, ext.lstrip(".") or "unknown")
                
                lines = self._count_lines(filepath)
                
                result.total_files += 1
                result.total_lines += lines
                result.languages[language] = result.languages.get(language, 0) + 1
                result.file_paths.append(rel_path)
                
                file_info.append({
                    "path": rel_path,
                    "lines": lines,
                    "language": language,
                })
        
        file_info.sort(key=lambda x: x["lines"], reverse=True)
        result.largest_files = file_info[:10]
        
        result.module_structure = self._build_module_structure(result.file_paths)
        
        return result

    def _load_gitignore(self) -> List[str]:
        """加载 .gitignore 文件内容，返回忽略模式列表。"""
        gitignore_path = os.path.join(self.root_path, ".gitignore")
        patterns = []
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass
        patterns.append(".git")
        patterns.append("__pycache__")
        patterns.append(".pytest_cache")
        patterns.append("*.pyc")
        return patterns

    def _is_ignored(self, name: str, patterns: List[str]) -> bool:
        """检查名称是否匹配任何忽略模式。"""
        for pattern in patterns:
            if pattern == name:
                return True
            if pattern.endswith("/") and name == pattern[:-1]:
                return True
            if pattern.startswith("*") and name.endswith(pattern[1:]):
                return True
            if pattern.endswith("*") and name.startswith(pattern[:-1]):
                return True
        return False

    def _count_lines(self, filepath: str) -> int:
        """统计文件行数。

        小文件（<= 64KB）逐行精确计数；大文件用块读取计数换行符，
        兼顾准确性与性能。二进制文件、非普通文件（管道/设备等）返回 0。
        """
        try:
            # 先 lstat 检查文件类型，避免在命名管道、设备等特殊文件上阻塞
            st = os.lstat(filepath)
            if not stat.S_ISREG(st.st_mode):
                return 0
            size = st.st_size
            if size == 0:
                return 0
            # 跳过超大文件，避免读取耗时
            if size > 10 * 1024 * 1024:
                return 0
            # 二进制检测: 只读前 1024 字节
            with open(filepath, "rb") as f:
                header = f.read(1024)
                if b"\x00" in header:
                    return 0
            # 精确计数换行符（块读取，避免逐行开销）
            count = 0
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    count += chunk.count(b"\n")
            # 文件末尾无换行符也算一行
            if count == 0 and size > 0:
                return 1
            return count
        except Exception:
            return 0

    def _build_module_structure(self, file_paths: List[str]) -> Dict[str, Any]:
        """按目录路径分组构建模块结构。"""
        structure = {}
        for filepath in file_paths:
            parts = filepath.split(os.sep)
            current = structure
            for i, part in enumerate(parts):
                if part not in current:
                    if i == len(parts) - 1:
                        current[part] = {"type": "file"}
                    else:
                        current[part] = {"type": "dir", "children": {}}
                if i < len(parts) - 1:
                    current = current[part].setdefault("children", {})
        return structure

    def _scan_tech_debt(self, file_tree: FileTreeState) -> TechDebtReport:
        """扫描技术债标记（基于已收集的文件列表）。"""
        result = TechDebtReport()
        marker_pattern = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s]*(.+)?")

        code_extensions = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java",
                          ".cpp", ".c", ".rb", ".php", ".sh", ".html", ".css"}

        file_lines_map = {info["path"]: info["lines"] for info in file_tree.largest_files}

        # 只扫描 _scan_files 已收集的文件（不再 os.walk）
        for rel_path in file_tree.file_paths:
            ext = os.path.splitext(rel_path)[1].lower()
            if ext not in code_extensions:
                continue

            filepath = os.path.join(self.root_path, rel_path)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                matches = marker_pattern.findall(content)
                if matches:
                    for marker_type, _ in matches:
                        marker_type_upper = marker_type.upper()
                        if marker_type_upper == "TODO":
                            result.todo_count += 1
                        elif marker_type_upper == "FIXME":
                            result.fixme_count += 1
                        elif marker_type_upper == "XXX":
                            result.xxx_count += 1
                        elif marker_type_upper == "HACK":
                            result.todo_count += 1
                    result.by_file[rel_path] = len(matches)
            except Exception:
                pass
        
        result.total_markers = result.todo_count + result.fixme_count + result.xxx_count
        
        hotspots = []
        for rel_path, count in result.by_file.items():
            lines = file_lines_map.get(rel_path, 1)
            density = count / lines
            hotspots.append({
                "path": rel_path,
                "lines": lines,
                "marker_count": count,
                "todo_density": density,
            })
        
        hotspots.sort(key=lambda x: x["todo_density"], reverse=True)
        result.hotspots = hotspots[:10]
        
        return result

    def _find_complexity_hotspots(self, file_tree: FileTreeState, 
                                  tech_debt: TechDebtReport) -> List[Dict[str, Any]]:
        """检测复杂度热点。
        
        基于文件行数 + TODO 密度，输出 Top-10 热点。
        
        返回：[{path, lines, todo_density, score}, ...]
        """
        if file_tree.total_files == 0:
            return []
        
        avg_lines = file_tree.total_lines / file_tree.total_files
        
        total_markers = sum(tech_debt.by_file.values())
        avg_density = total_markers / file_tree.total_lines if file_tree.total_lines > 0 else 0.0
        
        file_lines_map = {info["path"]: info["lines"] for info in file_tree.largest_files}
        
        hotspots = []
        for filepath in file_tree.file_paths:
            lines = file_lines_map.get(filepath, 0)
            marker_count = tech_debt.by_file.get(filepath, 0)
            todo_density = marker_count / lines if lines > 0 else 0.0
            
            lines_score = (lines / avg_lines) if avg_lines > 0 else 0.0
            density_score = (todo_density / avg_density) if avg_density > 0 else 0.0
            score = lines_score * 0.6 + density_score * 0.4
            
            hotspots.append({
                "path": filepath,
                "lines": lines,
                "todo_density": todo_density,
                "score": score,
            })
        
        hotspots.sort(key=lambda x: x["score"], reverse=True)
        return hotspots[:10]

    def _scan_tests(self) -> TestState:
        """扫描测试状态。

        检测：
        - 测试框架（pytest / jest / unknown）
        - 测试用例总数（运行 `pytest --collect-only -q` 获取）
        - 最近失败的测试（从 pytest cache 或最近运行结果）
        - 覆盖率百分比（如果有 .coverage 文件）

        Returns:
            TestState 数据类（已在 _types.py 定义）
        """
        result = TestState()

        try:
            if os.path.exists(os.path.join(self.root_path, "pytest.ini")):
                result.framework = "pytest"
            elif os.path.exists(os.path.join(self.root_path, "pyproject.toml")):
                pyproject_path = os.path.join(self.root_path, "pyproject.toml")
                with open(pyproject_path, "rb") as f:
                    try:
                        config = tomllib.load(f)
                        if "tool" in config and "pytest" in config["tool"]:
                            result.framework = "pytest"
                    except Exception:
                        pass
            elif os.path.exists(os.path.join(self.root_path, "jest.config.js")):
                result.framework = "jest"
            elif os.path.exists(os.path.join(self.root_path, "package.json")):
                package_path = os.path.join(self.root_path, "package.json")
                with open(package_path, "r", encoding="utf-8") as f:
                    import json

                    try:
                        config = json.load(f)
                        if "scripts" in config and "jest" in config["scripts"]:
                            result.framework = "jest"
                    except Exception:
                        pass
        except Exception:
            pass

        if result.framework == "pytest":
            try:
                proc = subprocess.run(
                    ["python", "-m", "pytest", "--collect-only", "-q"],
                    cwd=self.root_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0:
                    lines = proc.stdout.strip().splitlines()
                    test_lines = [line for line in lines if line and not line.startswith("collected")]
                    result.total_cases = len(test_lines)
                    for line in proc.stderr.splitlines():
                        if "FAILED" in line:
                            result.failed += 1
                        elif "PASSED" in line:
                            result.passed += 1
            except Exception:
                pass

            try:
                coverage_path = os.path.join(self.root_path, ".coverage")
                if os.path.exists(coverage_path):
                    import coverage

                    cov = coverage.Coverage(data_file=coverage_path)
                    cov.load()
                    percent = cov.report(show_missing=False, ignore_errors=True)
                    if percent is not None:
                        result.coverage_percent = round(percent, 2)
            except Exception:
                try:
                    htmlcov_index = os.path.join(self.root_path, "htmlcov", "index.html")
                    if os.path.exists(htmlcov_index):
                        with open(htmlcov_index, "r", encoding="utf-8") as f:
                            content = f.read()
                            import re

                            match = re.search(r'(\d+\.?\d*)%', content)
                            if match:
                                result.coverage_percent = float(match.group(1))
                except Exception:
                    pass

            try:
                cache_dir = os.path.join(self.root_path, ".pytest_cache", "v", "cache")
                lastfailed_path = os.path.join(cache_dir, "lastfailed")
                if os.path.exists(lastfailed_path):
                    import json

                    with open(lastfailed_path, "r", encoding="utf-8") as f:
                        try:
                            failures = json.load(f)
                            for test_id in list(failures.keys())[:10]:
                                result.recent_failures.append({"test_id": test_id})
                        except Exception:
                            pass
            except Exception:
                pass

        return result

    def _scan_build(self) -> BuildState:
        """扫描构建状态。

        检测：
        - 构建系统（pyproject.toml / setup.py / package.json）
        - 最近构建状态（检查 dist/、build/ 目录时间戳）
        - 构建警告数（从最近构建日志）

        Returns:
            BuildState 数据类（已在 _types.py 定义）
        """
        result = BuildState()

        try:
            pyproject_path = os.path.join(self.root_path, "pyproject.toml")
            if os.path.exists(pyproject_path):
                with open(pyproject_path, "rb") as f:
                    try:
                        config = tomllib.load(f)
                        if "build-system" in config:
                            result.build_system = "pyproject"
                    except Exception:
                        pass

            if not result.build_system and os.path.exists(os.path.join(self.root_path, "setup.py")):
                result.build_system = "setup.py"

            if not result.build_system and os.path.exists(os.path.join(self.root_path, "package.json")):
                package_path = os.path.join(self.root_path, "package.json")
                with open(package_path, "r", encoding="utf-8") as f:
                    import json

                    try:
                        config = json.load(f)
                        if "scripts" in config and "build" in config["scripts"]:
                            result.build_system = "package.json"
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            last_build_time = 0.0
            build_dirs = ["dist", "build", "target"]
            for dir_name in build_dirs:
                dir_path = os.path.join(self.root_path, dir_name)
                if os.path.isdir(dir_path):
                    mtime = os.path.getmtime(dir_path)
                    if mtime > last_build_time:
                        last_build_time = mtime

            if last_build_time > 0:
                result.last_build_at = last_build_time
                result.last_build_status = "success"
        except Exception:
            pass

        try:
            build_log_path = os.path.join(self.root_path, "build.log")
            if os.path.exists(build_log_path):
                with open(build_log_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    result.warnings = content.count("WARNING")
        except Exception:
            pass

        return result

    def _scan_dependencies(self) -> DependencyReport:
        """扫描项目依赖（最多检查 max_deps 个的版本差异）。"""
        result = DependencyReport()
        direct_deps: Dict[str, Dict[str, Any]] = {}

        try:
            pyproject_path = os.path.join(self.root_path, "pyproject.toml")
            if os.path.exists(pyproject_path):
                with open(pyproject_path, "rb") as f:
                    try:
                        config = tomllib.load(f)
                        project = config.get("project", {})
                        deps = project.get("dependencies", [])
                        for dep in deps:
                            name, version = self._parse_dep_line(dep)
                            direct_deps[name] = {"name": name, "version": version, "latest": None}
                        optional_deps = project.get("optional-dependencies", {})
                        for group_deps in optional_deps.values():
                            for dep in group_deps:
                                name, version = self._parse_dep_line(dep)
                                if name not in direct_deps:
                                    direct_deps[name] = {"name": name, "version": version, "latest": None}
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            req_path = os.path.join(self.root_path, "requirements.txt")
            if os.path.exists(req_path):
                with open(req_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        name, version = self._parse_dep_line(line)
                        if name not in direct_deps:
                            direct_deps[name] = {"name": name, "version": version, "latest": None}
        except Exception:
            pass

        try:
            package_path = os.path.join(self.root_path, "package.json")
            if os.path.exists(package_path):
                with open(package_path, "r", encoding="utf-8") as f:
                    import json

                    try:
                        config = json.load(f)
                        for dep_type in ["dependencies", "devDependencies"]:
                            deps = config.get(dep_type, {})
                            for name, version in deps.items():
                                if name not in direct_deps:
                                    direct_deps[name] = {"name": name, "version": version, "latest": None}
                    except Exception:
                        pass
        except Exception:
            pass

        max_deps = 10  # 限制 pip show 调用次数, 避免 pip show 爆炸
        try:
            for i, (name, dep_info) in enumerate(direct_deps.items()):
                if i >= max_deps:
                    break
                installed_version = self._get_installed_version(name)
                if installed_version:
                    dep_info["latest"] = installed_version
                    declared_version = dep_info.get("version", "")
                    if declared_version and installed_version != declared_version:
                        if not (declared_version.startswith(">=") or declared_version.startswith("<=") or
                                declared_version.startswith(">") or declared_version.startswith("<") or
                                declared_version.startswith("~") or declared_version.startswith("^")):
                            result.outdated.append(dep_info)

                dangerous_keywords = ["pyyaml", "jinja2", "flask", "django", "requests"]
                if any(kw in name.lower() for kw in dangerous_keywords):
                    result.vulnerabilities.append({
                        "name": name,
                        "severity": "medium",
                        "reason": f"Known common vulnerability target: {name}"
                    })
        except Exception:
            pass

        result.direct = list(direct_deps.values())
        result.total = len(result.direct)

        return result

    def _parse_dep_line(self, line: str) -> tuple[str, str]:
        """解析依赖声明行。返回 (name, version)"""
        import re

        line = line.strip()
        if not line:
            return "", ""

        line = line.split("[")[0].split("#")[0].strip()

        match = re.match(r'^([a-zA-Z0-9_-]+)(.*)$', line)
        if not match:
            return "", ""

        name = match.group(1)
        rest = match.group(2).strip()

        version = ""
        for op in ["==", ">=", "<=", ">", "<", "~=", "~", "^"]:
            if op in rest:
                version = rest
                break

        return name, version

    def _get_installed_version(self, pkg_name: str) -> Optional[str]:
        """快速获取已安装包版本（使用 importlib.metadata, 避免 pip show 子进程）。"""
        try:
            from importlib.metadata import version as _ver
            return _ver(pkg_name)
        except Exception:
            pass
        try:
            node_modules_path = os.path.join(self.root_path, "node_modules", pkg_name, "package.json")
            if os.path.exists(node_modules_path):
                with open(node_modules_path, "r", encoding="utf-8") as f:
                    import json

                    config = json.load(f)
                    return config.get("version")
        except Exception:
            pass

        return None

    def stats(self) -> Dict[str, Any]:
        """返回感知器统计：扫描次数、缓存命中率等。"""
        return {
            "scan_count": self._scan_count,
            "cache_hit_count": self._cache_hit_count,
            "cache_miss_count": self._cache_miss_count,
            "last_scan_at": self._cache_time,
            "root_path": self.root_path,
        }