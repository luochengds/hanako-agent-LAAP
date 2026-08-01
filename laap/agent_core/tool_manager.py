"""LAAP Tool Manager — 统一工具入口 (V2)

修复:
  - list_tools 重复定义 bug (后者覆盖前者, 导致 get_openai_tools 失效)
  - 现保留 list_tools() → List[Tool], 新增 list_tool_names() → List[str]

扩展 (多 backend 路由):
  - register_all_backends() 依次注册: Hermes → agent_core/tools → laap/tools → MCP
  - 支持 backend adapter 协议 (任何带 register_into(tm) 方法的对象都可作 backend)

Tool dataclass 增强:
  - 新增 metadata: Dict 字段 (与 laap/tools/base.Tool 兼容)
"""
from __future__ import annotations
import time, json, logging, inspect, threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("agent_core.tools")


@dataclass
class ToolResult:
    """工具调用结果 — 与 hermes_tool_bridge.ToolResult 完全兼容。"""
    success: bool = True
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    data: Any = None


@dataclass
class Tool:
    """统一工具定义 — OpenAI Function Calling 兼容 + metadata 扩展。

    字段兼容性:
      - 与 laap.agent_core.hermes_tool_bridge.Tool 完全兼容
      - 与 laap.tools.base.Tool 兼容 (新增 metadata 字段)
    """
    name: str = ""
    description: str = ""
    parameters: Dict = field(default_factory=dict)
    handler: Optional[Callable] = None
    enabled: bool = True
    category: str = "general"
    metadata: Dict = field(default_factory=dict)  # 新增: source/toolset/requires_env 等

    def __getitem__(self, key):
        """Dict-like access for test compatibility"""
        return getattr(self, key)

    def __contains__(self, key):
        """Dict-like 'in' check for test compatibility"""
        return hasattr(self, key)

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "category": self.category,
            "metadata": self.metadata,
        }


class _ToolList(list):
    """Tool 列表 — 兼容 ``"name" in tool_list`` 旧式字符串查找。

    ``list_tools()`` 返回本子类实例，既保留 ``List[Tool]`` 语义，
    又让旧测试 ``"a" in tm.list_tools()`` 按工具名命中。
    """

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return any(getattr(t, "name", None) == item for t in self)
        return super().__contains__(item)


class ToolManager:
    """统一工具管理器 — 唯一对外入口, 支持多 backend 路由。

    Backend 优先级 (后注册者覆盖同名):
      1. Hermes (73 工具, 通过 HermesToolBridge.register_into)
      2. agent_core/tools (30 工具, 通过 register_all)
      3. laap/tools (18 工具, 通过 AoRegistry.register_into)
      4. MCP (6 内置 server, 通过 MCPBridge.discover_tools)
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._history: List[Dict] = []
        self._lock = threading.RLock()
        self._backends: List[Any] = []  # 已注册的 backend adapter 列表

    # ── 注册 / 注销 ──────────────────────────────────────────────

    def register(self, tool: Tool, override: bool = False):
        """注册工具。

        Args:
            tool: Tool 对象
            override: True 时覆盖同名工具; False 时同名工具跳过并 log warning
        """
        with self._lock:
            if tool.name in self._tools and not override:
                logger.debug(
                    f"Tool '{tool.name}' already registered, skipping "
                    f"(use override=True to replace)"
                )
                return
            self._tools[tool.name] = tool
            logger.debug(f"Tool registered: {tool.name} [{tool.category}]")

    def register_fn(self, name: str, description: str = "",
                    parameters: Dict = None, category: str = "general"):
        """装饰器方式注册工具 — 自动从函数签名推断 schema。"""
        def decorator(func):
            sig = inspect.signature(func)
            if not parameters:
                params = {"type": "object", "properties": {}, "required": []}
                for p_name, p_param in sig.parameters.items():
                    if p_name == 'self':
                        continue
                    param_type = "string"
                    if p_param.annotation != inspect.Parameter.empty:
                        type_map = {str: "string", int: "integer", float: "number",
                                    bool: "boolean", list: "array", dict: "object"}
                        param_type = type_map.get(p_param.annotation, "string")
                    params["properties"][p_name] = {"type": param_type, "description": ""}
                    if p_param.default == inspect.Parameter.empty:
                        params["required"].append(p_name)
            else:
                params = parameters

            tool = Tool(name=name or func.__name__,
                        description=description or func.__doc__ or "",
                        parameters=params, handler=func, category=category)
            self.register(tool)
            return func
        return decorator

    def register_tool(self, name: str, handler: Callable, description: str = "",
                      parameters: Dict = None, category: str = "general"):
        """Register a tool (compatibility API)"""
        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")
        tool = Tool(name=name, description=description,
                    parameters=parameters or {"type": "object", "properties": {}},
                    handler=handler, category=category)
        self.register(tool)
        return tool

    def unregister(self, name: str):
        with self._lock:
            self._tools.pop(name, None)

    def unregister_tool(self, name: str):
        """Unregister a tool (compatibility API)"""
        self.unregister(name)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    # ── 列表查询 (修复 list_tools 重复定义 bug) ──────────────────

    def list_tools(self, category: str = "") -> List[Tool]:
        """列出 Tool 对象 (按 category 过滤, 仅 enabled)。"""
        with self._lock:
            if category:
                return _ToolList([t for t in self._tools.values()
                        if t.category == category and t.enabled])
            return _ToolList([t for t in self._tools.values() if t.enabled])

    def list_tool_names(self, category: str = "") -> List[str]:
        """列出工具名称 (兼容 API, 返回 List[str])。"""
        with self._lock:
            if category:
                return [t.name for t in self._tools.values()
                        if t.category == category and t.enabled]
            return [t.name for t in self._tools.values() if t.enabled]

    @property
    def registry(self) -> Dict[str, Tool]:
        """Expose registry for test compatibility"""
        return self._tools

    @property
    def count(self) -> int:
        """工具数量 (HermesToolBridge 兼容)。"""
        return len(self._tools)

    # ── 调用 ─────────────────────────────────────────────────────

    def execute_tool(self, name: str, arguments: Dict = None) -> Any:
        """Execute a tool and return result data (compatibility API)"""
        result = self.call(name, arguments)
        if result.success:
            return result.data or result.output
        if "not found" in result.error.lower():
            raise KeyError(result.error)
        raise RuntimeError(result.error)

    def call(self, name: str, arguments: Dict = None) -> ToolResult:
        """调用工具并返回 ToolResult。"""
        start = time.time()
        tool = self.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Tool '{name}' not found")
        if not tool.handler:
            return ToolResult(success=False, error=f"Tool '{name}' has no handler")

        try:
            args = arguments or {}
            # 自动适配 Hermes-style (args 单参 dict) vs LAAP-style (**kwargs)
            sig = inspect.signature(tool.handler)
            params = list(sig.parameters.keys())
            if len(params) == 1 and params[0] in ("args", "kwargs", "input", "data"):
                result = tool.handler(args)
            else:
                result = tool.handler(**args)

            elapsed = (time.time() - start) * 1000
            output = str(result) if result is not None else ""
            tr = ToolResult(success=True, output=output,
                            duration_ms=round(elapsed, 2), data=result)

            with self._lock:
                self._history.append({
                    "tool": name, "args": args,
                    "result": output[:200], "duration_ms": tr.duration_ms,
                    "success": True,
                })
                if len(self._history) > 1000:
                    self._history = self._history[-1000:]
            return tr
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            tr = ToolResult(success=False, error=str(e),
                            duration_ms=round(elapsed, 2))
            with self._lock:
                self._history.append({
                    "tool": name, "args": args,
                    "result": str(e)[:200], "duration_ms": tr.duration_ms,
                    "success": False,
                })
            return tr

    # ── OpenAI / Anthropic 格式导出 ──────────────────────────────

    def get_openai_tools(self) -> List[dict]:
        """导出 OpenAI Function Calling 格式。"""
        return [t.to_openai_format() for t in self.list_tools()]

    def get_stats(self) -> dict:
        total = len(self._history)
        success = sum(1 for h in self._history if h["success"])
        return {
            "total_calls": total,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "tools": len(self._tools),
            "history": total,
            "backends": len(self._backends),
        }

    # ════════════════════════════════════════════════════════════════
    # 多 Backend 路由 (V2 新增)
    # ════════════════════════════════════════════════════════════════

    def register_backend(self, backend: Any):
        """注册一个 backend adapter。

        Backend adapter 必须实现 `register_into(tm: ToolManager)` 方法。
        例如 HermesToolBridge / AoRegistry / MCPBridge 都可作为 backend。
        """
        if not hasattr(backend, "register_into"):
            raise ValueError(
                f"Backend {type(backend).__name__} must implement "
                f"register_into(tm: ToolManager) method"
            )
        self._backends.append(backend)
        backend.register_into(self)
        logger.info(
            f"Backend registered: {type(backend).__name__} "
            f"(total tools: {self.count})"
        )

    def register_all_backends(self, include_hermes: bool = True,
                              include_agent_core: bool = True,
                              include_laap_tools: bool = True,
                              include_mcp: bool = False) -> dict:
        """依次注册所有可用 backend。

        优先级 (后注册者覆盖同名):
          1. Hermes (73 工具)
          2. agent_core/tools (30 工具)
          3. laap/tools (18 工具)
          4. MCP (6 内置 server, 默认关闭因依赖 npx/uvx)

        Args:
            include_hermes: 是否注册 Hermes backend
            include_agent_core: 是否注册 agent_core/tools
            include_laap_tools: 是否注册 laap/tools
            include_mcp: 是否注册 MCP backend (默认关闭)

        Returns:
            各 backend 注册状态 dict
        """
        results = {"backends": [], "total_tools": 0}

        # 1. Hermes backend
        if include_hermes:
            try:
                from laap.agent_core.hermes_tool_bridge import HermesToolBridge
                bridge = HermesToolBridge.get_instance()
                self.register_backend(bridge)
                results["backends"].append({
                    "name": "HermesToolBridge",
                    "status": "ok",
                    "tools": bridge.count,
                })
            except Exception as e:
                logger.warning(f"Hermes backend 注册失败: {e}")
                results["backends"].append({
                    "name": "HermesToolBridge",
                    "status": f"failed: {e}",
                    "tools": 0,
                })

        # 2. agent_core/tools backend
        if include_agent_core:
            try:
                from laap.agent_core.tools import register_all
                before = self.count
                register_all(self)
                added = self.count - before
                results["backends"].append({
                    "name": "agent_core/tools",
                    "status": "ok",
                    "tools": added,
                })
            except Exception as e:
                logger.warning(f"agent_core/tools backend 注册失败: {e}")
                results["backends"].append({
                    "name": "agent_core/tools",
                    "status": f"failed: {e}",
                    "tools": 0,
                })

        # 3. laap/tools backend (AoRegistry)
        if include_laap_tools:
            try:
                from laap.tools.registry import ao
                before = self.count
                # AoRegistry 作为 backend adapter
                self.register_backend(_AoRegistryBackend(ao))
                added = self.count - before
                results["backends"].append({
                    "name": "laap/tools (AoRegistry)",
                    "status": "ok",
                    "tools": added,
                })
            except Exception as e:
                logger.warning(f"laap/tools backend 注册失败: {e}")
                results["backends"].append({
                    "name": "laap/tools (AoRegistry)",
                    "status": f"failed: {e}",
                    "tools": 0,
                })

        # 4. MCP backend (默认关闭, 因依赖 npx/uvx)
        if include_mcp:
            try:
                from laap.agent_core.mcp_bridge import create_mcp_bridge
                before = self.count
                create_mcp_bridge(self)
                added = self.count - before
                results["backends"].append({
                    "name": "MCP",
                    "status": "ok",
                    "tools": added,
                })
            except Exception as e:
                logger.warning(f"MCP backend 注册失败: {e}")
                results["backends"].append({
                    "name": "MCP",
                    "status": f"failed: {e}",
                    "tools": 0,
                })

        results["total_tools"] = self.count
        return results

    def get_backend_status(self) -> List[dict]:
        """获取所有已注册 backend 的状态。"""
        return [{"name": type(b).__name__, "type": str(type(b))}
                for b in self._backends]


# ══════════════════════════════════════════════════════════════════
# Backend Adapter — 把 AoRegistry (laap/tools) 适配为 ToolManager backend
# ══════════════════════════════════════════════════════════════════

class _AoRegistryBackend:
    """适配器: 把 laap.tools.registry.AoRegistry 适配为 ToolManager backend。

    AoRegistry 是 Hermes 风格的注册中心 (单例 ao), 有自己的 ToolEntry。
    本适配器把 AoRegistry 中所有工具包装成 ToolManager.Tool 并注册。
    """

    def __init__(self, ao_registry):
        self.ao = ao_registry

    def register_into(self, tm: ToolManager):
        """把 AoRegistry 中所有工具注册到 ToolManager。"""
        try:
            # AoRegistry 的 API: get_all_tool_names() + get_entry(name)
            tool_names = self.ao.get_all_tool_names()
        except AttributeError:
            # 兼容旧 API
            try:
                tool_names = list(self.ao._tools.keys())
            except AttributeError:
                logger.warning("AoRegistry 没有可用的工具列表 API")
                return

        for name in tool_names:
            try:
                entry = self.ao.get_entry(name)
                if entry is None:
                    continue
                # 跳过已注册的 (Hermes backend 已注册大部分)
                if tm.get(name) is not None:
                    continue
                # 包装为 ToolManager.Tool
                parameters = getattr(entry, "parameters", None) or \
                             getattr(entry, "input_schema", None) or \
                             {"type": "object", "properties": {}}
                description = getattr(entry, "description", "") or \
                              getattr(entry, "desc", "")
                handler = getattr(entry, "handler", None) or \
                          getattr(entry, "fn", None)
                category = getattr(entry, "category", "laap_tools")
                tm.register(Tool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    handler=lambda args, h=handler: (
                        h(args) if isinstance(args, dict) and
                        len(inspect.signature(h).parameters) == 1
                        else h(**(args or {}))
                    ) if h else None,
                    category=category,
                    metadata={"source": "laap.tools.AoRegistry", "toolset": category},
                ), override=False)
            except Exception as e:
                logger.debug(f"Skip laap tool '{name}': {e}")


# ══════════════════════════════════════════════════════════════════
# 便捷工厂函数
# ══════════════════════════════════════════════════════════════════

def create_tool_manager(register_backends: bool = True,
                        **kwargs) -> ToolManager:
    """创建 ToolManager 并可选注册所有 backend。

    Args:
        register_backends: True 时自动注册所有 backend (Hermes + agent_core + laap_tools)
        **kwargs: 透传给 register_all_backends()

    Returns:
        配置好的 ToolManager
    """
    tm = ToolManager()
    if register_backends:
        tm.register_all_backends(**kwargs)
    return tm


__all__ = [
    "Tool", "ToolResult", "ToolManager",
    "create_tool_manager",
]
