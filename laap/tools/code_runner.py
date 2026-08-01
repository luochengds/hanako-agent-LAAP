"""LAAP — Native code execution tools."""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from laap.tools.base import ToolResult


class CodeRunnerTool:
    """Run Python snippets and pytest suites in isolated subprocesses."""

    @staticmethod
    def run_tests(target: str = ".", timeout: int = 120) -> ToolResult:
        """Run ``python -m pytest *target*``."""
        cmd = [sys.executable, "-m", "pytest", target]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.stderr else None,
                metadata={"returncode": result.returncode, "target": target},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Tests timed out after {timeout}s",
                metadata={"target": target, "timeout": timeout},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"target": target},
            )

    @staticmethod
    def run_python(code: str, timeout: int = 10) -> ToolResult:
        """Execute a Python code string in a fresh interpreter."""
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.stderr else None,
                metadata={"returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Code timed out after {timeout}s",
                metadata={"timeout": timeout},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )
