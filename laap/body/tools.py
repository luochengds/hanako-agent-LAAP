"""LAAP Body layer — public unified tool registry API."""

from __future__ import annotations

from laap.tools.tool_registry import (
    discover_actors,
    discover_and_register,
    get_tool,
    get_tool_schema,
    list_tools,
    register_tool,
)

__all__ = [
    "get_tool",
    "list_tools",
    "get_tool_schema",
    "register_tool",
    "discover_actors",
]

# Ensure the global registry is populated when the public body API is imported.
# This re-runs discovery safely if another test/component has cleared the registry.
discover_and_register()
