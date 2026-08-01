"""LAAP — Native filesystem tools."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from laap.tools.base import ToolResult


PathLike = Union[str, os.PathLike[str]]


class FileSystemTool:
    """Static filesystem helpers returning ``ToolResult``."""

    @staticmethod
    def read_file(path: PathLike) -> ToolResult:
        """Read text from *path*; gracefully handle missing files."""
        target = Path(path)
        try:
            content = target.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(target.resolve()), "size": len(content)},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"File not found: {target}",
                metadata={"path": str(target)},
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"path": str(target)},
            )

    @staticmethod
    def write_file(path: PathLike, content: str) -> ToolResult:
        """Write *content* to *path*, creating parent directories as needed."""
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"Wrote {target}",
                metadata={"path": str(target.resolve()), "bytes": target.stat().st_size},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"path": str(target)},
            )

    @staticmethod
    def list_dir(path: PathLike) -> ToolResult:
        """List entries in *path*."""
        target = Path(path)
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"{'[DIR] ' if entry.is_dir() else '[FILE]'} {entry.name}" for entry in entries]
            return ToolResult(
                success=True,
                output="\n".join(lines),
                metadata={"path": str(target.resolve()), "count": len(entries)},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {target}",
                metadata={"path": str(target)},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                metadata={"path": str(target)},
            )
