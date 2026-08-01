"""
LAAP — Production Shell Tools
Shell execution, python runner, git integration.
"""

from __future__ import annotations
import json, logging, os, shlex, subprocess
from pathlib import Path
from typing import Dict, List, Optional

from laap.shell.executor import shell
from laap.git.operations import git
from laap.tools.base import ToolResult
from laap.agent_core.tools.approval_tool import check_all_command_guards, ApprovalContext
from laap.tools.terminal import TerminalTool

logger = logging.getLogger("laap.tools.shell")


def _looks_like_path(token: str) -> bool:
    """Heuristic: does a shell token look like a file path?"""
    if not token:
        return False
    if token.startswith(("/", "\\", "~", ".")):
        return True
    if "/" in token or "\\" in token:
        return True
    return False


def _resolve_path_token(token: str, cwd: Optional[str]) -> Path:
    """Resolve a path token to an absolute path."""
    base = Path(cwd) if cwd else Path.cwd()
    if token.startswith("~"):
        token = os.path.expanduser(token)
    return (base / token).resolve()


def _check_path_constraints(
    cmd: str,
    cwd: Optional[str],
    allowed_paths: Optional[List[str]],
    blocked_paths: Optional[List[str]],
) -> tuple[bool, Optional[str]]:
    """Validate command/cwd against allowed and blocked path lists."""
    if cwd and allowed_paths:
        cwd_resolved = Path(cwd).resolve()
        if not any(
            cwd_resolved == allowed_resolved or allowed_resolved in cwd_resolved.parents
            for allowed_resolved in (Path(p).resolve() for p in allowed_paths)
        ):
            return False, f"cwd {cwd} is outside allowed paths"

    if allowed_paths or blocked_paths:
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()

        for token in tokens:
            if not _looks_like_path(token):
                continue
            resolved = _resolve_path_token(token, cwd)

            if blocked_paths:
                for blocked in blocked_paths:
                    blocked_resolved = Path(blocked).resolve()
                    try:
                        resolved.relative_to(blocked_resolved)
                        return False, f"path {token} matches blocked path {blocked}"
                    except ValueError:
                        pass

            if allowed_paths:
                in_allowed = False
                for allowed in allowed_paths:
                    allowed_resolved = Path(allowed).resolve()
                    try:
                        resolved.relative_to(allowed_resolved)
                        in_allowed = True
                        break
                    except ValueError:
                        pass
                if not in_allowed:
                    return False, f"path {token} is outside allowed paths"

    return True, None


def run_command(
    cmd: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 60,
    allowed_paths: Optional[List[str]] = None,
    blocked_paths: Optional[List[str]] = None,
    sandbox: bool = True,
) -> ToolResult:
    """Execute a shell command safely.

    Args:
        cmd: Shell command to execute.
        cwd: Working directory.
        env: Environment variables to overlay onto os.environ.
        timeout: Maximum execution time in seconds.
        allowed_paths: Optional list of paths the command may reference.
        blocked_paths: Optional list of paths the command must not reference.
        sandbox: If True, reject commands matching dangerous patterns.

    Returns:
        ToolResult with stdout/stderr and metadata.
    """
    if sandbox:
        guard = check_all_command_guards(cmd, ApprovalContext())
        if not guard["approved"]:
            return ToolResult(
                success=False,
                output="",
                error=f"Blocked by sandbox: {guard['message']}",
                metadata={"command": cmd, "sandbox": True, "pattern_key": guard.get("pattern_key", "")},
            )

    safe, error = _check_path_constraints(cmd, cwd, allowed_paths, blocked_paths)
    if not safe:
        return ToolResult(
            success=False,
            output="",
            error=f"Path check failed: {error}",
            metadata={"command": cmd, "cwd": cwd},
        )

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ToolResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            metadata={
                "command": cmd,
                "returncode": result.returncode,
                "cwd": cwd,
            },
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            output="",
            error=f"Command timed out after {timeout}s",
            metadata={"command": cmd, "timeout": timeout},
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            output="",
            error=str(exc),
            metadata={"command": cmd},
        )


def register_all(registry):
    """注册所有 Shell 工具 - 幂等安全"""
    _registered = getattr(registry, '_shell_tools_registered', False)
    if _registered:
        return
    registry._shell_tools_registered = True

    @registry.tool(name="run_command", category="shell",
                   description="Execute any shell command. Use for running tests, builds, git, npm/pip, etc.")
    def run_command(command: str, timeout: int = 60, workdir: str = "") -> str:
        """Run a shell command and return its output.

        Args:
            command: The shell command to execute
            timeout: Max execution time in seconds (default 60)
            workdir: Working directory (default: current)
        """
        result = shell.run(command, cwd=workdir or None, timeout=timeout)
        return json.dumps({
            "success": result["success"],
            "exit_code": result["exit_code"],
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
        }, ensure_ascii=False)

    @registry.tool(name="run_python", category="shell",
                   description="Execute Python code and return the output.")
    def run_python(code: str, timeout: int = 30) -> str:
        """Execute Python code snippet.

        Args:
            code: Python code to execute
            timeout: Max execution time in seconds
        """
        result = shell.run_python(code, timeout)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="run_script", category="shell",
                   description="Execute a local script file with optional arguments.")
    def run_script(script_path: str, args: str = "", timeout: int = 60) -> str:
        """Run a script file.

        Args:
            script_path: Path to the script
            args: Command-line arguments
            timeout: Max execution time
        """
        result = shell.run_script(script_path, args, timeout)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="git_status", category="git",
                   description="Show git status: branch, modified/untracked/staged files.")
    def git_status(path: str = ".") -> str:
        """Check git repository status.

        Args:
            path: Git repository path
        """
        result = git.status(path)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="git_diff", category="git",
                   description="Show git diff of uncommitted changes.")
    def git_diff(path: str = ".", staged: bool = False) -> str:
        """Show git diff.

        Args:
            path: Git repository path
            staged: Show staged changes only
        """
        result = git.diff(path, staged)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="git_log", category="git",
                   description="Show recent git commit history.")
    def git_log(path: str = ".", count: int = 10) -> str:
        """Show git log.

        Args:
            path: Git repository path
            count: Number of commits to show
        """
        result = git.log(path, count)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="git_commit", category="git",
                   description="Stage all changes and create a git commit.")
    def git_commit(message: str, path: str = ".", add_all: bool = True) -> str:
        """Create a git commit.

        Args:
            message: Commit message
            path: Git repository path
            add_all: Auto-stage all changes first
        """
        result = git.commit(message, path, add_all)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="git_branch", category="git",
                   description="List git branches or create a new branch.")
    def git_branch(name: str = "", path: str = ".") -> str:
        """Manage git branches.

        Args:
            name: Branch name (empty = list, non-empty = create & checkout)
            path: Git repository path
        """
        result = git.branch(name, path)
        return json.dumps(result, ensure_ascii=False)

    @registry.tool(name="shell_session", category="shell",
                   description="Create a persistent shell session for interactive commands.")
    def shell_session(action: str = "create", session_id: str = "",
                      command: str = "", cwd: str = "") -> str:
        """Manage persistent shell sessions.

        Args:
            action: create | write | read | close | list
            session_id: Session ID (for write/read/close)
            command: Command to write (for write action)
            cwd: Working directory (for create)
        """
        if action == "create":
            result = shell.create_session(cwd or None)
        elif action == "write":
            result = shell.write_session(session_id, command)
        elif action == "read":
            result = shell.read_session(session_id)
        elif action == "close":
            result = shell.close_session(session_id)
        elif action == "list":
            sessions = shell.list_sessions()
            return json.dumps({"success": True, "sessions": sessions})
        else:
            return json.dumps({"success": False, "error": f"Unknown action: {action}"})
        return json.dumps(result)
