"""
Tool Search — Progressive Tool Disclosure (Hermes-compatible)

When many tools are available (MCP/plugin tools), they may exceed the context budget.
Tool search provides bridge tools that let the agent discover tools on-demand:
  tool_search      — Search available tools by keyword
  tool_describe    — Get full schema of a specific tool

Inspired by Hermes agent/tool_dispatch_helpers.py and tools/tool_search.py
"""

from __future__ import annotations
import json, logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.tools.tool_search")

# Global tool registry reference (set by agent on init)
_tool_registry: Optional[Dict[str, Any]] = None


def set_tool_registry(registry: Dict[str, Any]):
    """Set the global tool registry reference."""
    global _tool_registry
    _tool_registry = registry


def tool_search(query: str = "", category: str = "") -> str:
    """Search available tools by name, description keyword, or category.

    Returns a list of matching tool names and descriptions.
    """
    try:
        if _tool_registry is None:
            return json.dumps({"error": "Tool registry not initialized", "tools": []})

        matches = []
        query_lower = query.lower() if query else ""

        for name, tool in _tool_registry.items():
            desc = getattr(tool, 'description', str(tool)) if not isinstance(tool, dict) else tool.get('description', '')
            cat = getattr(tool, 'category', '') if not isinstance(tool, dict) else tool.get('category', '')
            desc_str = str(desc).lower()

            # Filter by category if specified
            if category and cat != category:
                continue

            # Filter by query if specified
            if query_lower and query_lower not in name.lower() and query_lower not in desc_str:
                continue

            matches.append({
                "name": name,
                "description": str(desc)[:120],
                "category": cat,
            })

        return json.dumps({
            "query": query,
            "category": category,
            "total": len(matches),
            "tools": sorted(matches, key=lambda x: x["name"]),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "tools": []})


def tool_describe(name: str) -> str:
    """Get full schema/parameters of a specific tool."""
    try:
        if _tool_registry is None:
            return json.dumps({"error": "Tool registry not initialized"})

        tool = _tool_registry.get(name)
        if tool is None:
            return json.dumps({"error": f"Tool '{name}' not found",
                               "available": list(_tool_registry.keys())[:10]})

        # Handle different tool object types
        if isinstance(tool, dict):
            return json.dumps(tool, ensure_ascii=False)
        else:
            return json.dumps({
                "name": getattr(tool, 'name', name),
                "description": getattr(tool, 'description', ''),
                "parameters": getattr(tool, 'parameters', {}),
                "category": getattr(tool, 'category', ''),
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOL_DEFS = [
    {"name": "tool_search",
     "fn": lambda **kw: tool_search(kw.get("query", ""), kw.get("category", "")),
     "desc": "Search available tools by keyword or category",
     "params": {"query": {"type": "string"}, "category": {"type": "string"}}},
    {"name": "tool_describe",
     "fn": lambda **kw: tool_describe(kw.get("name", "")),
     "desc": "Get full schema/parameters of a specific tool",
     "params": {"name": {"type": "string"}}, "req": ["name"]},
]
