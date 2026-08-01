"""LAAP — Simple session memory tool backed by a JSON file."""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from laap.tools.base import ToolResult

logger = logging.getLogger("laap.tools.memory_tool")


def _get_storage_dir() -> Path:
    """Return the directory used for LAAP JSON storage."""
    path = Path(os.environ.get("LAAP_STORAGE_DIR", ".laap"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _memory_file() -> Path:
    return _get_storage_dir() / "memory.json"


def _load_memory() -> Dict[str, Any]:
    file_path = _memory_file()
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to load memory: {exc}")
        return {}


def _save_memory(data: Dict[str, Any]) -> None:
    file_path = _memory_file()
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def session_search(query: str, limit: int = 5) -> ToolResult:
    """Search memory entries whose key or value contains *query*."""
    try:
        memory = _load_memory()
        query_lower = query.lower()
        matches = []
        for key, value in memory.items():
            value_str = json.dumps(value, ensure_ascii=False)
            if query_lower in key.lower() or query_lower in value_str.lower():
                matches.append({"key": key, "value": value})
            if len(matches) >= limit:
                break

        return ToolResult(
            success=True,
            output=json.dumps(matches, ensure_ascii=False),
            metadata={"query": query, "limit": limit, "matches": len(matches)},
        )
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


def memory_read(key: str) -> ToolResult:
    """Read a single memory entry by key."""
    try:
        memory = _load_memory()
        if key not in memory:
            return ToolResult(
                success=False,
                output="",
                error=f"Key not found: {key}",
                metadata={"key": key},
            )
        return ToolResult(
            success=True,
            output=json.dumps(memory[key], ensure_ascii=False),
            metadata={"key": key},
        )
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


def memory_write(key: str, value: Any) -> ToolResult:
    """Write a value to memory under *key*."""
    try:
        memory = _load_memory()
        memory[key] = value
        _save_memory(memory)
        return ToolResult(
            success=True,
            output=json.dumps(value, ensure_ascii=False),
            metadata={"key": key},
        )
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))
