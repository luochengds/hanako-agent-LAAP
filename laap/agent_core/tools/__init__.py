"""LAAP Agent Tools — 扩展工具集

Exports:
- Synchronous tools (file, system, media, computer use)
- Async browser tools wrapped with run_sync
- convenience: get_all_tool_defs(), register_all()
"""
from __future__ import annotations
import asyncio, json, logging
from typing import Any, Callable

logger = logging.getLogger("laap.tools")

# ── Async→Sync wrapper ──


def run_sync(async_fn: Callable, *args, **kw) -> str:
    """Run an async browser function synchronously and return JSON string.

    Creates a fresh event loop for each call (without polluting the thread's
    current loop) so that pytest-asyncio tests are not affected by leftover
    running loops.
    """
    try:
        # If a loop is already running in this thread, run the coroutine in a
        # separate thread to avoid "cannot run from a running loop" errors.
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, async_fn(*args, **kw))
            result = future.result(timeout=30)
    except RuntimeError:
        # No running loop — safe to create one with asyncio.run.
        result = asyncio.run(async_fn(*args, **kw))
    try:
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"run_sync error in {async_fn.__name__}: {e}")
        return json.dumps({"error": str(e)})


# ── Import all tool modules ──

from laap.agent_core.tools import file_tools, system_tools, media_tools
from laap.agent_core.tools import code_tools, data_tools, web_tools
from laap.agent_core.tools import computer_use_tool, cua_driver_tools
from laap.agent_core.tools import vision_tool, skill_tools, tool_search


def get_all_tool_defs() -> list[dict]:
    """Aggregate all TOOL_DEFS from every tool module (~55+ tools)."""
    defs = []
    for mod in [file_tools, system_tools, media_tools, code_tools,
                data_tools, web_tools, computer_use_tool, vision_tool,
                skill_tools, tool_search, cua_driver_tools]:
        if hasattr(mod, "TOOL_DEFS"):
            defs.extend(mod.TOOL_DEFS)
    # Add async browser tools wrapped with run_sync
    _add_browser_tool_defs(defs)
    # Add essential CRUD tools (compatibility aliases not in any TOOL_DEFS)
    _add_essential_tool_defs(defs)
    return defs


def _result(value) -> str:
    """Normalize a tool result to JSON string (handles both dict and str)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _add_essential_tool_defs(defs: list[dict]):
    """Add essential tools that LLMs commonly call (read_file, write_file, etc.)."""
    import laap.agent_core.tools.file_tools as ft
    import laap.agent_core.tools.system_tools as st
    import laap.agent_core.tools.media_tools as mt
    import time as _time

    essentials = [
        {"name": "read_file",
         "fn": lambda **kw: _result(ft.read_file(kw.get("path", "."), int(kw.get("limit", 500)), int(kw.get("offset", 1)))),
         "desc": "Read file contents with optional offset/limit",
         "params": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
         "req": ["path"]},
        {"name": "write_file",
         "fn": lambda **kw: _result(ft.write_file(kw.get("path", ""), kw.get("content", ""))),
         "desc": "Write content to a file (creates directories if needed)",
         "params": {"path": {"type": "string"}, "content": {"type": "string"}},
         "req": ["path", "content"]},
        {"name": "list_files",
         "fn": lambda **kw: _result(ft.list_directory(kw.get("path", "."))),
         "desc": "List files and directories in a folder",
         "params": {"path": {"type": "string"}}},
        {"name": "execute_command",
         "fn": lambda **kw: _result(st.execute_command(kw.get("command", ""), int(kw.get("timeout", 30)))),
         "desc": "Run a shell command and get output",
         "params": {"command": {"type": "string"}, "timeout": {"type": "integer"}},
         "req": ["command"]},
        {"name": "web_search",
         "fn": lambda **kw: _result(mt.search_web(kw.get("query", ""), int(kw.get("max_results", 5)))),
         "desc": "Search the web for information",
         "params": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
         "req": ["query"]},
        {"name": "get_time",
         "fn": lambda **kw: json.dumps({"time": _time.strftime("%Y-%m-%d %H:%M:%S")}),
         "desc": "Get current date and time",
         "params": {}},
        {"name": "get_system_info",
         "fn": lambda **kw: _result(st.get_system_info()),
         "desc": "Get system/platform information",
         "params": {}},
        {"name": "think",
         "fn": lambda **kw: json.dumps({"thought": kw.get("thought", ""), "status": "recorded"}),
         "desc": "Record internal reasoning step by step",
         "params": {"thought": {"type": "string"}},
         "req": ["thought"]},
        {"name": "finish",
         "fn": lambda **kw: json.dumps({"result": kw.get("result", ""), "summary": kw.get("summary", ""), "status": "complete"}),
         "desc": "Signal task completion with final result and optional summary",
         "params": {"result": {"type": "string"}, "summary": {"type": "string"}},
         "req": ["result"]},
    ]
    defs.extend(essentials)


def _add_browser_tool_defs(defs: list[dict]):
    """Add Playwright browser tools with sync wrappers."""
    import laap.agent_core.tools.computer_use_tool as cu
    browser_tools = [
        {"name": "browser_navigate",
         "fn": lambda **kw: run_sync(cu.browser_navigate, kw.get("url", "")),
         "desc": "Navigate Playwright browser to a URL",
         "params": {"url": {"type": "string"}}, "req": ["url"]},
        {"name": "browser_snapshot",
         "fn": lambda **kw: run_sync(cu.browser_snapshot),
         "desc": "Get current page title/URL/text snapshot",
         "params": {}},
        {"name": "browser_screenshot",
         "fn": lambda **kw: run_sync(cu.browser_screenshot),
         "desc": "Capture browser viewport as base64 PNG",
         "params": {}},
        {"name": "browser_click",
         "fn": lambda **kw: run_sync(cu.browser_click, kw.get("selector", "")),
         "desc": "Click element by CSS selector in browser",
         "params": {"selector": {"type": "string"}}, "req": ["selector"]},
        {"name": "browser_type",
         "fn": lambda **kw: run_sync(cu.browser_type, kw.get("selector", ""), kw.get("text", "")),
         "desc": "Type text into element by CSS selector",
         "params": {"selector": {"type": "string"}, "text": {"type": "string"}}, "req": ["selector", "text"]},
        {"name": "browser_scroll",
         "fn": lambda **kw: run_sync(cu.browser_scroll, int(kw.get("dx", 0)), int(kw.get("dy", 300))),
         "desc": "Scroll browser page",
         "params": {"dx": {"type": "integer"}, "dy": {"type": "integer"}}},
        {"name": "browser_extract_links",
         "fn": lambda **kw: run_sync(cu.browser_extract_links),
         "desc": "Extract all links from current page",
         "params": {}},
        {"name": "browser_back",
         "fn": lambda **kw: run_sync(cu.browser_back),
         "desc": "Navigate browser back",
         "params": {}},
    ]
    defs.extend(browser_tools)


def register_all(tool_manager):
    """Register all tools from all modules into a ToolManager."""
    from laap.agent_core.tool_manager import Tool
    count = 0
    for td in get_all_tool_defs():
        params = {"type": "object",
                  "properties": td.get("params", {}),
                  "required": td.get("req", [])}
        try:
            tool_manager.register(Tool(
                name=td["name"],
                description=td.get("desc", ""),
                parameters=params,
                category=td.get("category", "general"),
                handler=td.get("fn"),
            ))
            count += 1
        except Exception as e:
            logger.warning(f"Failed to register {td['name']}: {e}")
    logger.info(f"Registered {count} tools")
    return count