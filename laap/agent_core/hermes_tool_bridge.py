"""
HermesToolBridge — LAAP Agent 与 Hermes 工具引擎的内核级桥接

不是 subprocess 调用，不是 sys.path 黑客，
而是让 LAAP 的 Agent 直接使用 Hermes 的 ToolRegistry 作为唯一工具注册中心。

Architecture:
  LAAP Agent (agent.py)
      │
      ▼
  HermesToolBridge (this file)   ← 实现 ToolManager 兼容接口
      │
      ├── tools/registry.py      ← Hermes ToolRegistry 单例 (50+ 工具)
      ├── model_tools.py         ← get_tool_definitions + 发现引擎
      ├── toolsets.py            ← 28 个预定义工具集
      └── tools/*.py             ← 96 个自注册工具文件
           ↑
      LAAP 特有工具 (cortex, cognitive_executor 等)
      注册到同一注册中心

Interface:
  完全兼容 laap.agent_core.tool_manager.ToolManager:
    - get_openai_tools() -> List[dict]
    - call(name, args) -> ToolResult
    - register(tool)
    - list_tools(category) -> List[str]
    - get(name) -> Optional[Tool]
    - execute_tool(name, args) -> Any
    - get_stats() -> dict
"""

from __future__ import annotations
import os
import sys
import json
import time
import logging
import inspect
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from laap.config.paths import get_hermes_root, get_laap_root

logger = logging.getLogger("agent_core.hermes_bridge")


def _resolve_hermes_home() -> str:
    """返回 Hermes 根目录字符串；未找到时给出明确提示并返回空字符串。"""
    root = get_hermes_root()
    if root is not None:
        return str(root)
    logger.warning(
        "HermesToolBridge: HERMES_ROOT not set and no Hermes installation found. "
        "Set HERMES_ROOT environment variable to enable Hermes tool integration."
    )
    return ""


def _resolve_laap_home() -> str:
    """返回 LAAP 根目录字符串。"""
    return str(get_laap_root())

_HERMES_HOME = _resolve_hermes_home()

# ── LAAP ToolManager 兼容的数据类型 ─────────────────────────────────
class ToolResult:
    """与 laap.agent_core.tool_manager.ToolResult 完全兼容"""
    __slots__ = ("success", "output", "error", "duration_ms", "data")
    def __init__(self, success: bool = True, output: str = "",
                 error: str = "", duration_ms: float = 0.0, data: Any = None):
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms
        self.data = data

    def __repr__(self):
        status = "OK" if self.success else f"ERR:{self.error[:40]}"
        return f"<ToolResult {status} {self.duration_ms:.0f}ms>"


class Tool:
    """与 laap.agent_core.tool_manager.Tool 完全兼容"""
    def __init__(self, name: str = "", description: str = "",
                 parameters: dict = None, handler: Callable = None,
                 enabled: bool = True, category: str = "general"):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.handler = handler
        self.enabled = enabled
        self.category = category

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
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


# ══════════════════════════════════════════════════════════════════
# 核心桥接器
# ══════════════════════════════════════════════════════════════════

class HermesToolBridge:
    """
    让 LAAP 的 Agent 直接使用 Hermes 工具引擎的包装器。

    使用方法:
        bridge = HermesToolBridge()
        bridge.call("web_search", {"query": "hello"})
        tools = bridge.get_openai_tools()  # ← 50+ 工具定义
    """

    _global_instance = None
    _global_lock = threading.Lock()

    def __init__(self, enabled_toolsets: Optional[List[str]] = None,
                 disabled_toolsets: Optional[List[str]] = None,
                 hermes_home: Optional[str] = None):
        self._hermes_home = hermes_home or _resolve_hermes_home()
        self._setup_completed = False
        self._hermes_registry = None
        self._hermes_toolsets = None
        self._hermes_model_tools = None

        # 工具集配置
        self._enabled_toolsets = enabled_toolsets or ["hermes-cli"]
        self._disabled_toolsets = disabled_toolsets or []

        # 调用历史 (ToolManager 兼容)
        self._history: List[dict] = []
        self._lock = threading.RLock()

        # LAAP 特有工具名集合 (用于 list_tools 过滤)
        self._laap_tool_names: set = set()

        # 初始化 Hermes 引擎
        self._init_hermes()

    # ── 初始化 ───────────────────────────────────────────────────

    def _setup_paths(self):
        """确保 Hermes 和 LAAP 都在 sys.path 中"""
        for p in [self._hermes_home, _resolve_laap_home()]:
            if p and p not in sys.path:
                sys.path.insert(0, p)

    def _init_hermes(self):
        """
        初始化 Hermes 工具引擎:
        1. 设置路径
        2. 导入 model_tools (触发 discover_builtin_tools → 96 个工具文件自注册)
        3. 获取 registry 引用
        """
        if self._setup_completed:
            return

        self._setup_paths()

        try:
            # 导入 model_tools — 模块级副作用: 触发 discover_builtin_tools()
            # 这会 import 所有 tools/*.py，每个文件调用 registry.register()
            import model_tools as mt
            self._hermes_model_tools = mt

            # 从 model_tools 获取 registry 引用
            from tools.registry import registry as hermes_registry
            self._hermes_registry = hermes_registry

            # 加载 toolsets
            import toolsets as ts
            self._hermes_toolsets = ts

            # 注册 LAAP 特有工具到 Hermes 注册中心
            self._register_laap_specific_tools()

            self._setup_completed = True
            logger.info(
                f"HermesToolBridge: {len(self._hermes_registry.get_all_tool_names())} "
                f"tools from {len(self._hermes_registry.get_registered_toolset_names())} "
                f"toolsets ready"
            )
        except Exception as e:
            logger.error(f"HermesToolBridge init failed: {e}", exc_info=True)
            raise

    # ── LAAP 特有工具注册 ──────────────────────────────────────

    def _register_laap_specific_tools(self):
        """
        将 LAAP 特有的工具注册到 Hermes 注册中心。

        这些是 Hermes 没有、LAAP 独有的工具:
        - cortex, cognitive_executor, distributed_cortex 等
        """
        if not self._hermes_registry:
            return

        # LAAP 工具描述
        laap_tools = [
            {
                "name": "think",
                "description": "内部思考: 在行动前分析问题、推理因果、制定策略。用中文思考。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "thought": {"type": "string", "description": "思考内容"}
                    },
                    "required": ["thought"]
                },
                "toolset": "laap",
                "emoji": "🧠",
            },
            {
                "name": "system_info",
                "description": "获取系统信息: CPU、内存、磁盘、进程等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["all", "cpu", "memory", "disk", "process"],
                            "description": "信息类别"
                        }
                    }
                },
                "toolset": "laap",
                "emoji": "💻",
            },
        ]

        for tdef in laap_tools:
            name = tdef["name"]
            toolset = tdef.pop("toolset", "laap")
            emoji = tdef.pop("emoji", "")

            # 不覆盖 Hermes 已有工具
            if self._hermes_registry.get_entry(name):
                continue

            self._hermes_registry.register(
                name=name,
                toolset=toolset,
                schema=tdef,
                handler=self._make_laap_handler(name),
                description=tdef.get("description", ""),
                emoji=emoji,
            )
            self._laap_tool_names.add(name)

        logger.info(f"Registered {len(laap_tools)} LAAP-specific tools")

    def _make_laap_handler(self, name: str) -> Callable:
        """创建 LAAP 特有工具的处理函数"""
        handlers = {
            "think": lambda args: json.dumps({
                "thought": args.get("thought", ""),
                "status": "processed"
            }, ensure_ascii=False),
            "system_info": lambda args: self._get_system_info(args),
        }
        handler = handlers.get(name)
        if handler:
            return handler
        return lambda args: json.dumps({"error": f"LAAP tool {name} not implemented"})

    def _get_system_info(self, args: dict) -> str:
        """获取系统信息"""
        import platform
        cat = args.get("category", "all")
        info = {"platform": platform.platform(), "python": sys.version.split()[0]}
        if cat in ("all", "cpu"):
            info["cpu"] = platform.processor() or "unknown"
        if cat in ("all", "memory"):
            try:
                import psutil
                mem = psutil.virtual_memory()
                info["memory"] = f"{mem.used//1024//1024}MB/{mem.total//1024//1024}MB"
            except ImportError:
                pass  # 可选模块，降级处理
        return json.dumps(info, ensure_ascii=False)

    # ── ToolManager 兼容接口 ───────────────────────────────────

    def get_openai_tools(self) -> List[dict]:
        """
        获取 OpenAI 格式的工具定义列表。

        Returns:
            OpenAI function-calling 格式的工具列表 (50+ 个工具)
        """
        if not self._hermes_model_tools:
            return []

        try:
            return self._hermes_model_tools.get_tool_definitions(
                enabled_toolsets=self._enabled_toolsets,
                disabled_toolsets=self._disabled_toolsets,
                quiet_mode=True,
            )
        except Exception as e:
            logger.warning(f"get_tool_definitions failed: {e}")
            return []

    def call(self, name: str, arguments: dict = None) -> ToolResult:
        """
        调用一个工具，返回 LAAP 兼容的 ToolResult。

        Args:
            name: 工具名
            arguments: 参数字典

        Returns:
            ToolResult (与 LAAP ToolManager.call 格式一致)
        """
        start = time.time()
        args = arguments or {}

        if not self._hermes_registry:
            return ToolResult(success=False, error="Hermes registry not initialized")

        try:
            # 使用 Hermes 注册中心的 dispatch
            result_str = self._hermes_registry.dispatch(name, args)

            elapsed = (time.time() - start) * 1000

            # 解析结果
            tr = ToolResult(
                success=True,
                output=str(result_str),
                duration_ms=round(elapsed, 2),
                data=result_str,
            )

            with self._lock:
                self._history.append({
                    "tool": name, "args": args,
                    "result": str(result_str)[:200],
                    "duration_ms": tr.duration_ms, "success": True,
                })
                if len(self._history) > 1000:
                    self._history = self._history[-1000:]

            return tr

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            tr = ToolResult(success=False, error=str(e), duration_ms=round(elapsed, 2))
            with self._lock:
                self._history.append({
                    "tool": name, "args": args,
                    "result": str(e)[:200],
                    "duration_ms": tr.duration_ms, "success": False,
                })
            return tr

    def register(self, tool) -> bool:
        """
        注册一个 LAAP 工具到 Hermes 注册中心。

        Args:
            tool: Tool 对象 (laap.agent_core.tool_manager.Tool)

        Returns:
            是否注册成功
        """
        if not self._hermes_registry:
            return False

        name = tool.name if hasattr(tool, 'name') else getattr(tool, 'name', str(tool))
        description = getattr(tool, 'description', '')
        parameters = getattr(tool, 'parameters', {"type": "object", "properties": {}})
        handler = getattr(tool, 'handler', None)
        category = getattr(tool, 'category', 'general')

        if not handler:
            logger.warning(f"Tool {name} has no handler, skipping")
            return False

        # 包装 handler — LAAP 的 handler 是 **kwargs，Hermes 是 single args dict
        def hermes_handler(args: dict) -> str:
            try:
                result = handler(**args)
                if not isinstance(result, str):
                    return json.dumps(result, ensure_ascii=False, default=str)
                return result
            except Exception as e:
                return json.dumps({"error": f"{type(e).__name__}: {e}"})

        schema = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }

        try:
            self._hermes_registry.register(
                name=name,
                toolset=f"laap-{category}",
                schema=schema,
                handler=hermes_handler,
                description=description,
                override=True,
            )
            self._laap_tool_names.add(name)
            logger.debug(f"Registered LAAP tool -> Hermes registry: {name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to register tool {name}: {e}")
            return False

    def unregister(self, name: str):
        """从注册中心移除一个工具"""
        if self._hermes_registry:
            self._hermes_registry.deregister(name)
            self._laap_tool_names.discard(name)

    def get(self, name: str) -> Optional[Tool]:
        """
        获取一个工具 (返回 LAAP 兼容的 Tool 对象)

        Args:
            name: 工具名

        Returns:
            Tool 对象，或 None
        """
        if not self._hermes_registry:
            return None

        entry = self._hermes_registry.get_entry(name)
        if not entry:
            return None

        return Tool(
            name=entry.name,
            description=entry.description or "",
            parameters=entry.schema.get("parameters", {"type": "object", "properties": {}}),
            category=entry.toolset or "general",
        )

    def list_tools(self, category: str = "") -> List[str]:
        """
        列出所有工具名称。

        Args:
            category: 按类别过滤 (仅对 LAAP 工具生效)

        Returns:
            工具名列表
        """
        if not self._hermes_registry:
            return []

        all_names = self._hermes_registry.get_all_tool_names()
        if category:
            # 过滤 LAAP 类别
            if category == "hermes":
                return [n for n in all_names if n not in self._laap_tool_names]
            elif category == "laap":
                return [n for n in all_names if n in self._laap_tool_names]
            else:
                # 按 toolset 过滤
                return [
                    n for n in all_names
                    if self._hermes_registry.get_toolset_for_tool(n) == category
                    or (n in self._laap_tool_names
                        and self.get(n) is not None
                        and self.get(n).category == category)
                ]
        return all_names

    def execute_tool(self, name: str, arguments: dict = None) -> Any:
        """
        执行工具并返回数据 (ToolManager.execute_tool 兼容)

        Args:
            name: 工具名
            arguments: 参数

        Returns:
            工具返回的数据

        Raises:
            KeyError: 工具不存在
            RuntimeError: 执行失败
        """
        result = self.call(name, arguments)
        if result.success:
            return result.data or result.output
        if "not found" in result.error.lower():
            raise KeyError(result.error)
        raise RuntimeError(result.error)

    # ── 统计 / 状态 ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取工具系统统计"""
        total = len(self._history)
        success = sum(1 for h in self._history if h.get("success", False))
        tool_count = len(self._hermes_registry.get_all_tool_names()) if self._hermes_registry else 0
        return {
            "total_calls": total,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "tools": tool_count,
            "history": total,
            "toolset": self._enabled_toolsets,
        }

    @property
    def registry(self) -> dict:
        """暴露底层注册表 (兼容 test 代码)"""
        if self._hermes_registry:
            return {name: True for name in self._hermes_registry.get_all_tool_names()}
        return {}

    @property
    def count(self) -> int:
        """已注册工具数"""
        return len(self._hermes_registry.get_all_tool_names()) if self._hermes_registry else 0

    # ── 工具集管理 ────────────────────────────────────────────

    def set_toolsets(self, enabled: Optional[List[str]] = None,
                     disabled: Optional[List[str]] = None):
        """设置启用的工具集"""
        if enabled is not None:
            self._enabled_toolsets = enabled
        if disabled is not None:
            self._disabled_toolsets = disabled

    def get_available_toolsets(self) -> Dict[str, dict]:
        """获取所有工具集的可用性信息"""
        if not self._hermes_registry:
            return {}
        return self._hermes_registry.get_available_toolsets()

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        """获取工具所属的工具集"""
        if not self._hermes_registry:
            return None
        return self._hermes_registry.get_toolset_for_tool(name)

    # ── 单例 ──────────────────────────────────────────────────

    @classmethod
    def get_instance(cls, enabled_toolsets: Optional[List[str]] = None,
                     disabled_toolsets: Optional[List[str]] = None,
                     hermes_home: str = _HERMES_HOME) -> "HermesToolBridge":
        """获取全局单例"""
        if cls._global_instance is None:
            with cls._global_lock:
                if cls._global_instance is None:
                    cls._global_instance = cls(
                        enabled_toolsets=enabled_toolsets,
                        disabled_toolsets=disabled_toolsets,
                        hermes_home=hermes_home,
                    )
        elif enabled_toolsets is not None or disabled_toolsets is not None:
            # 更新工具集配置
            cls._global_instance.set_toolsets(
                enabled=enabled_toolsets,
                disabled=disabled_toolsets,
            )
        return cls._global_instance

    @classmethod
    def reset_instance(cls):
        """重置单例 (主要用于测试)"""
        with cls._global_lock:
            cls._global_instance = None

    # ════════════════════════════════════════════════════════════════
    # Backend Adapter 协议 (V2 — 支持统一 ToolManager)
    # ══════════════════════════════════════════════════════════════════

    def register_into(self, tm) -> int:
        """把所有 Hermes 工具批量注册到统一 ToolManager。

        作为 laap.agent_core.tool_manager.ToolManager 的 backend adapter。
        每个 Hermes 工具包装为 tm.Tool, handler 委托给 Hermes registry.dispatch。

        Args:
            tm: laap.agent_core.tool_manager.ToolManager 实例

        Returns:
            注册成功的工具数量
        """
        from laap.agent_core.tool_manager import Tool as TMTool
        try:
            tool_names = self.list_tools()
        except Exception as e:
            logger.warning(f"HermesToolBridge.register_into: list_tools failed: {e}")
            return 0

        registered = 0
        for name in tool_names:
            try:
                # 获取工具元数据
                entry = None
                try:
                    hermes_reg = self._hermes_registry
                    entry = hermes_reg.get_entry(name) if hermes_reg else None
                except Exception:
                    pass

                # 构造 parameters
                parameters = {"type": "object", "properties": {}}
                description = name
                if entry is not None:
                    parameters = getattr(entry, "parameters", None) or \
                                 getattr(entry, "input_schema", None) or \
                                 {"type": "object", "properties": {}}
                    description = getattr(entry, "description", "") or \
                                  getattr(entry, "desc", "") or name

                # handler 委托给 Hermes registry.dispatch
                def _make_handler(tool_name, bridge):
                    def handler(**kwargs):
                        return bridge.call(tool_name, kwargs or {})
                    return handler

                tm_tool = TMTool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    handler=_make_handler(name, self),
                    category="hermes",
                    metadata={"source": "hermes", "bridge": "HermesToolBridge"},
                )
                tm.register(tm_tool, override=True)
                registered += 1
            except Exception as e:
                logger.debug(f"register_into: skip '{name}': {e}")

        logger.info(
            f"HermesToolBridge.register_into: {registered}/{len(tool_names)} "
            f"tools registered to ToolManager"
        )
        return registered


# ══════════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════════

def create_bridge(enabled_toolsets: Optional[List[str]] = None,
                  disabled_toolsets: Optional[List[str]] = None) -> HermesToolBridge:
    """
    创建或获取 HermesToolBridge 实例。

    LAAP Agent 使用此函数替代 ToolManager():
        bridge = create_bridge(["hermes-cli"])
        tools = bridge.get_openai_tools()  # 50+ 个工具
    """
    return HermesToolBridge.get_instance(
        enabled_toolsets=enabled_toolsets,
        disabled_toolsets=disabled_toolsets,
    )


def quick_test():
    """快速验证桥接是否正常工作"""
    bridge = create_bridge()
    logger.info(f"Tools: {bridge.count}")
    logger.info(f"Toolset: {bridge._enabled_toolsets}")
    names = bridge.list_tools()
    logger.info(f"Tool names ({len(names)}): {', '.join(names[:15])}...")
    if "web_search" in names:
        result = bridge.call("web_search", {"query": "LAAP AGI"})
        logger.info(f"web_search result: success={result.success}, len={len(result.output)}")
    logger.info(f"Stats: {bridge.get_stats()}")
    return bridge


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    quick_test()
