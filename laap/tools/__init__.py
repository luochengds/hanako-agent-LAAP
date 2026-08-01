"""LAAP - Native tool layer."""

# Import the unified registry first so that its auto-discovery runs before any
# submodule that depends on it is loaded, avoiding partial-module cycles.
from laap.tools.tool_registry import (
    discover_actors,
    get_tool,
    get_tool_schema,
    list_tools,
    register_tool,
)

from laap.tools.base import Tool, ToolResult, infer_json_schema
from laap.tools.registry import AoRegistry, ToolRegistry, ao as registry

from laap.tools.actors import (
    BCIAdapterActor,
    BrowserActor,
    CodeRunnerActor,
    FileSystemActor,
    SearchActor,
    TerminalActor,
    register_tool_actors,
)
from laap.tools.bci_adapter import BCIMockStream, BCIAdapterTool
from laap.tools.code_runner import CodeRunnerTool
from laap.tools.filesystem import FileSystemTool
from laap.tools.search import SearchTool
from laap.tools.terminal import TerminalTool

# Importing these modules ensures their top-level functions are registered in
# the unified global registry.  Modules with ``register_all`` delegate to
# ``ToolRegistry``; the remaining modules are auto-inspected by
# ``tool_registry.discover_and_register()`` which is executed on first import.
from laap.tools import (
    browser_auto,
    code_runner,
    delegate,
    filesystem,
    kanban,
    memory_tool,
    shell,
    terminal,
    vision,
    web,
)

__all__ = [
    "AoRegistry",
    "BCIMockStream",
    "BCIAdapterActor",
    "BCIAdapterTool",
    "BrowserActor",
    "CodeRunnerActor",
    "CodeRunnerTool",
    "FileSystemActor",
    "FileSystemTool",
    "SearchActor",
    "SearchTool",
    "TerminalActor",
    "TerminalTool",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "discover_actors",
    "get_tool",
    "get_tool_schema",
    "infer_json_schema",
    "list_tools",
    "register_tool",
    "register_tool_actors",
    "registry",
]
