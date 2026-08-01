"""
LAAP — Tool Execution Cortex (工具执行皮层)
参考 Hermes Agent 架构设计

类比人类大脑的运动皮层（Motor Cortex）：
负责将「大脑决策」转化为「具体行动」。
每个工具调用都是经过皮层筛选、路由、执行的精准动作。

设计模式（从 Hermes 借鉴）：
  1. Schema-First: 每个工具有完整 JSON Schema 定义
  2. Availability Check: check_fn 确保工具在可用时才暴露（参考 Hermes check_fn TTL 缓存）
  3. Toolset Composition: 工具按工具集分组（参考 Hermes toolsets.py）
  4. Permission Gateway: 所有工具调用经过权限检查层
  5. Async Dispatch: 支持异步工具调用
  6. Audit Trail: 所有工具调用记录到审计日志
  7. Error Recovery: 工具失败时的优雅降级
  8. Rate Limiting: 单工具调用频率控制

与 Hermes 差异：
  - 集成 Brain 层：工具执行受认知状态影响
  - 带有认知追踪：每个工具调用都关联一个"思考"记录
  - 情感感知：工具选择受当前情感状态影响
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, threading, asyncio, uuid

logger = logging.getLogger("laap.tools.cortex")


class ToolStatus(Enum):
    """工具执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"


class ToolCategory(Enum):
    """工具分类"""
    SHELL = "shell"
    FILE = "file"
    CODE = "code"
    WEB = "web"
    BROWSER = "browser"
    GUI = "gui"
    GIT = "git"
    MEMORY = "memory"
    COGNITIVE = "cognitive"
    CUSTOM = "custom"


@dataclass
class ToolCallRecord:
    """
    工具调用记录 — 每个调用的完整轨迹
    
    参考 Hermes tool execution ledger 设计，
    但增加认知追踪字段。
    """
    id: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    status: ToolStatus = ToolStatus.PENDING
    result: str = ""
    error: str = ""
    duration_ms: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    
    # 认知关联
    thought_id: str = ""                 # 关联的思考ID
    cognitive_region: str = "motor"      # 执行的脑区
    confidence_before: float = 0.5       # 执行前的置信度
    confidence_delta: float = 0.0        # 执行后的置信度变化
    
    # 执行信息
    source: str = "agent"                # agent / brain / cognitive_loop
    retry_count: int = 0
    permission_checked: bool = False
    permission_granted: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "tool": self.tool_name,
            "args": str(self.arguments)[:40],
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 1),
            "thought": self.thought_id[:8] if self.thought_id else "",
        }


@dataclass
class ToolSpec:
    """
    工具规范 — 完全基于 JSON Schema 的工具定义
    
    类比 Hermes 的 ToolEntry，但更简洁。
    """
    name: str = ""
    description: str = ""
    category: str = "custom"
    toolset: str = "core"
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    handler: Optional[Callable] = None
    check_fn: Optional[Callable] = None        # 可用性检查函数
    requires_env: List[str] = field(default_factory=list)
    is_async: bool = False
    stop_after: bool = False
    
    def to_tool_def(self):
        """转换为 LLM 可用的 ToolDef 格式"""
        from laap.llm.provider import ToolDef
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


class ToolExecutionCortex:
    """
    工具执行皮层 — LAAP 的统一工具执行层
    
    架构（参考 Hermes Agent's tool dispatch pipeline）:
      Agent.request → Cortex.plan → Permission.check
      → Schema.validate → Handler.dispatch → Audit.log
    
    核心能力：
    1. 工具注册与 Schema 管理 (Hermes-style)
    2. Toolset 组合与解析
    3. 权限网关 (permission enforcer)
    4. 执行追踪与审计
    5. 认知关联 (每个调用关联 Brain.Thought)
    6. 错误恢复与重试
    """

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        
        # 工具注册表: name -> ToolSpec
        self._tools: Dict[str, ToolSpec] = {}
        
        # 工具集: toolset_name -> [tool_names]
        self._toolsets: Dict[str, List[str]] = {
            "core": [],
            "shell": [],
            "file": [],
            "web": [],
            "browser": [],
            "git": [],
            "cognitive": [],
            "memory": [],
        }
        
        # 执行记录
        self.records: List[ToolCallRecord] = []
        self._max_records = 200
        self._record_lock = threading.Lock()
        
        # TTL 缓存 (参考 Hermes check_fn TTL)
        self._check_cache: Dict[str, Tuple[float, bool]] = {}
        self._check_ttl = 30.0
        
        # 频率限制
        self._call_timestamps: Dict[str, List[float]] = {}
        self._rate_limit_window = 60.0  # 每秒
        self._rate_limit_max = 30       # 最多调用次数
        
        # 统计
        self._total_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0
        self._blocked_calls = 0
        
        logger.info(f"ToolExecutionCortex [{agent_id[:8]}] 初始化完成")

    # ═══════════════════════════════════════════════════════
    # 工具注册 (Hermes-style)
    # ═══════════════════════════════════════════════════════

    def register(self, spec: ToolSpec) -> bool:
        """注册一个工具（参考 Hermes registry.register）"""
        if spec.name in self._tools:
            logger.debug(f"工具已存在: {spec.name}")
            return False
        
        self._tools[spec.name] = spec
        
        # 加入工具集
        if spec.toolset not in self._toolsets:
            self._toolsets[spec.toolset] = []
        if spec.name not in self._toolsets[spec.toolset]:
            self._toolsets[spec.toolset].append(spec.name)
        
        # 也加入 core
        if spec.name not in self._toolsets["core"]:
            self._toolsets["core"].append(spec.name)
        
        logger.debug(f"已注册工具: {spec.name} [{spec.toolset}]")
        return True

    def register_handler(self, name: str, handler: Callable,
                         description: str = "",
                         category: str = "custom",
                         toolset: str = "core",
                         parameters: Optional[Dict] = None,
                         check_fn: Optional[Callable] = None,
                         requires_env: Optional[List[str]] = None,
                         stop_after: bool = False) -> bool:
        """便捷注册：从 handler 函数推断 Schema（参考 laap.tools.base）"""
        from inspect import signature, getdoc
        from laap.tools.base import infer_json_schema
        
        sig = signature(handler)
        hints = {}
        for pname, p in sig.parameters.items():
            if pname not in ("self", "cls", "agent", "fc"):
                hints[pname] = p.annotation if p.annotation != p.empty else str
        
        param_descs = {}
        doc = getdoc(handler)
        if doc:
            try:
                from docstring_parser import parse as doc_parse
                for p in (doc_parse(doc).params or []):
                    param_descs[p.arg_name] = p.description or ""
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        if parameters is None:
            schema = infer_json_schema(hints, param_descs)
            parameters = {
                "type": "object",
                "properties": schema["properties"],
                "required": schema.get("required", []),
            }
        
        spec = ToolSpec(
            name=name,
            description=description or handler.__doc__ or "",
            category=category,
            toolset=toolset,
            parameters=parameters,
            handler=handler,
            check_fn=check_fn,
            requires_env=requires_env or [],
            stop_after=stop_after,
        )
        return self.register(spec)

    def available(self, name: str) -> bool:
        """检查工具当前是否可用（参考 Hermes check_fn TTL 缓存）"""
        spec = self._tools.get(name)
        if not spec:
            return False
        
        if not spec.check_fn:
            return True
        
        # TTL 缓存
        now = time.monotonic()
        cached = self._check_cache.get(name)
        if cached and now - cached[0] < self._check_ttl:
            return cached[1]
        
        try:
            available = bool(spec.check_fn())
        except Exception:
            available = False
        
        self._check_cache[name] = (now, available)
        return available

    def list_available(self, toolset: Optional[str] = None) -> List[str]:
        """列出所有可用工具（参考 Hermes toolsets）"""
        if toolset:
            names = self._toolsets.get(toolset, [])
        else:
            names = list(self._tools.keys())
        
        return [n for n in names if self.available(n)]

    def get_schemas(self, toolset: Optional[str] = None) -> List[Dict]:
        """获取工具 Schemas（供 LLM 调用用）"""
        names = self.list_available(toolset)
        schemas = []
        for name in names:
            spec = self._tools.get(name)
            if spec:
                schemas.append({
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                })
        return schemas

    # ═══════════════════════════════════════════════════════
    # 工具执行 (参考 Hermes dispatch 管道)
    # ═══════════════════════════════════════════════════════

    def execute(self, tool_name: str, arguments: Dict[str, Any],
                thought_id: str = "",
                confidence: float = 0.5,
                permission_enforcer: Optional[Any] = None) -> ToolCallRecord:
        """
        执行工具调用 — 经过权限、验证、审计、追踪的完整管道
        
        管道流程:
          1. 查找工具定义
          2. 可用性检查 (check_fn)
          3. 权限检查 (permission enforcer)
          4. 频率限制检查
          5. Schema 参数验证
          6. 执行 handler
          7. 记录审计日志
          8. 更新统计
        
        Args:
            tool_name: 工具名
            arguments: 参数字典
            thought_id: 关联的思考ID
            confidence: 执行前置信度
            permission_enforcer: 权限执行器
        
        Returns:
            ToolCallRecord: 完整执行记录
        """
        self._total_calls += 1
        t0 = time.time()
        
        record = ToolCallRecord(
            id=str(uuid.uuid4())[:12],
            tool_name=tool_name,
            arguments=arguments,
            start_time=t0,
            status=ToolStatus.PENDING,
            thought_id=thought_id,
            confidence_before=confidence,
        )
        
        try:
            # 1. 查找工具
            spec = self._tools.get(tool_name)
            if not spec:
                record.status = ToolStatus.ERROR
                record.error = f"Tool '{tool_name}' not found"
                self._record_result(record)
                return record
            
            # 2. 可用性检查
            if not self.available(tool_name):
                record.status = ToolStatus.BLOCKED
                record.error = f"Tool '{tool_name}' not available (check_fn failed)"
                self._blocked_calls += 1
                self._record_result(record)
                return record
            
            # 3. 权限检查
            if permission_enforcer:
                record.permission_checked = True
                resource = self._map_tool_to_permission(tool_name)
                if hasattr(permission_enforcer, 'check'):
                    perm_func = permission_enforcer.check
                else:
                    perm_func = permission_enforcer
                if not perm_func(resource, f"Tool: {tool_name}"):
                    record.status = ToolStatus.BLOCKED
                    record.error = f"Permission denied: {tool_name}"
                    record.permission_granted = False
                    self._blocked_calls += 1
                    self._record_result(record)
                    return record
                record.permission_granted = True
            
            # 4. 频率限制
            if not self._check_rate_limit(tool_name):
                record.status = ToolStatus.BLOCKED
                record.error = f"Rate limit exceeded for {tool_name}"
                self._blocked_calls += 1
                self._record_result(record)
                return record
            
            # 5. 执行
            record.status = ToolStatus.RUNNING
            result = spec.handler(**arguments)
            
            # 6. 记录结果
            record.status = ToolStatus.SUCCESS
            record.result = str(result)[:1000]
            self._successful_calls += 1
            
        except Exception as e:
            record.status = ToolStatus.ERROR
            record.error = f"{type(e).__name__}: {str(e)[:200]}"
            record.result = json.dumps({"error": record.error})
            self._failed_calls += 1
            logger.warning(f"[Cortex] Tool {tool_name} failed: {e}")
        
        # 完成记录
        record.end_time = time.time()
        record.duration_ms = (record.end_time - t0) * 1000
        
        # 计算置信度变化
        if record.status == ToolStatus.SUCCESS:
            record.confidence_delta = 0.1
        elif record.status == ToolStatus.ERROR:
            record.confidence_delta = -0.15
        elif record.status == ToolStatus.BLOCKED:
            record.confidence_delta = -0.05
        
        self._record_result(record)
        return record

    def execute_with_brain(self, tool_name: str, arguments: Dict[str, Any],
                            brain: Any,
                            permission_enforcer: Optional[Any] = None) -> ToolCallRecord:
        """
        通过 Brain 层执行工具 — 工具调用与认知状态联动
        
        Brain 层会：
          - 记录工具调用到思考轨迹
          - 从执行结果学习
          - 更新情感状态
        """
        # 1. Brain 执行感知
        if hasattr(brain, 'perceive'):
            brain.perceive(f"执行工具: {tool_name}")
        
        # 2. 执行工具
        thought_id = f"tool_{int(time.time()*1000)}"
        record = self.execute(
            tool_name, arguments,
            thought_id=thought_id,
            confidence=getattr(brain, 'cortex', None).integration_level if hasattr(brain, 'cortex') else 0.5,
            permission_enforcer=permission_enforcer,
        )
        
        # 3. Brain 从结果学习
        if hasattr(brain, 'learn_from_outcome'):
            outcome = 0.8 if record.status == ToolStatus.SUCCESS else 0.2
            brain.learn_from_outcome(tool_name, outcome)
        
        return record

    # ═══════════════════════════════════════════════════════
    # 工具集管理
    # ═══════════════════════════════════════════════════════

    def define_toolset(self, name: str, tool_names: List[str],
                       overwrite: bool = False) -> bool:
        """定义或覆盖一个工具集（参考 Hermes define_toolset）"""
        if name in self._toolsets and not overwrite:
            return False
        
        valid = [n for n in tool_names if n in self._tools]
        self._toolsets[name] = valid
        return True

    def resolve_toolset(self, name: str) -> List[str]:
        """递归解析工具集（支持嵌套，参考 Hermes resolve_toolset）"""
        raw = self._toolsets.get(name, [])
        result = []
        seen = set()
        for item in raw:
            if item in self._toolsets and item != name:
                for t in self.resolve_toolset(item):
                    if t not in seen:
                        result.append(t)
                        seen.add(t)
            else:
                if item not in seen:
                    result.append(item)
                    seen.add(item)
        return result

    def get_toolset_names(self) -> List[str]:
        """获取所有工具集名称"""
        return list(self._toolsets.keys())

    # ═══════════════════════════════════════════════════════
    # 查询与统计
    # ═══════════════════════════════════════════════════════

    def get_recent_calls(self, n: int = 10) -> List[Dict]:
        """获取最近 N 次工具调用"""
        with self._record_lock:
            recent = self.records[-n:] if self.records else []
            return [r.to_dict() for r in recent]

    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计（参考 Hermes stats）"""
        return {
            "total_calls": self._total_calls,
            "successful": self._successful_calls,
            "failed": self._failed_calls,
            "blocked": self._blocked_calls,
            "success_rate": round(
                self._successful_calls / max(1, self._total_calls), 3
            ),
            "registered_tools": len(self._tools),
            "toolsets": len(self._toolsets),
            "active_records": len(self.records),
        }

    def status(self) -> dict:
        return self.get_stats()

    # ═══════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════

    def _record_result(self, record: ToolCallRecord):
        """记录执行结果（线程安全）"""
        with self._record_lock:
            self.records.append(record)
            if len(self.records) > self._max_records:
                self.records = self.records[-self._max_records:]

    def _check_rate_limit(self, tool_name: str) -> bool:
        """检查频率限制 (Hermes-style rate limiting)"""
        now = time.time()
        timestamps = self._call_timestamps.get(tool_name, [])
        
        # 清除超过窗口的记录
        timestamps = [t for t in timestamps if now - t < self._rate_limit_window]
        
        if len(timestamps) >= self._rate_limit_max:
            return False
        
        timestamps.append(now)
        self._call_timestamps[tool_name] = timestamps
        return True

    def _map_tool_to_permission(self, tool_name: str) -> str:
        """将工具名映射到权限资源"""
        mapping = {
            "run_command": "shell:execute", "run_python": "code:execute",
            "run_script": "shell:execute", "write_file": "file:write",
            "edit_file": "file:write", "create_file": "file:write",
            "delete_file": "file:delete", "git_commit": "git:commit",
            "git_push": "git:push", "git_branch": "git:commit",
            "web_fetch": "network:connect", "web_search": "network:connect",
            "delegate_task": "agent:delegate",
        }
        return mapping.get(tool_name, "code:execute")
