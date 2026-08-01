"""LAAP — Native terminal/shell tool with sandboxing."""
from __future__ import annotations

import subprocess
from typing import Optional

from laap.agent_core.tools.approval_tool import check_all_command_guards, ApprovalContext
from laap.tools.base import ToolResult


class TerminalTool:
    """Run shell commands safely."""

    @staticmethod
    def _is_dangerous(cmd: str) -> tuple[bool, Optional[str]]:
        """Delegate to the unified approval/gating system."""
        result = check_all_command_guards(cmd, ApprovalContext())
        if not result["approved"]:
            return True, result["message"]
        return False, None

    @staticmethod
    def run_command(
        cmd: str,
        timeout: int = 30,
        cwd: Optional[str] = None,
        sandbox: bool = True,
    ) -> ToolResult:
        """Execute *cmd* in a subprocess.

        When *sandbox* is enabled, commands matching a dangerous pattern are
        rejected before execution.
        """
        if sandbox:
            dangerous, reason = TerminalTool._is_dangerous(cmd)
            if dangerous:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Blocked by sandbox: {reason}",
                    metadata={"command": cmd, "sandbox": True},
                )

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
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
                    "sandbox": sandbox,
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
