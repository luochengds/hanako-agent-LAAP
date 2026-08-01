"""LAAP-TOOL 工具协议

定义生命体调用工具的标准接口，兼容 MCP（Model Context Protocol）。
通过 adapt_mcp_tool 适配器可将标准 MCP 工具转换为 LAAP 工具。

References:
- LAAP2.0大版本升级方案 § LAAP-TOOL
- MCP 规范：https://modelcontextprotocol.io/
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ToolCategory(Enum):
    """工具类别"""
    FILESYSTEM = "filesystem"  # 文件系统操作
    NETWORK = "network"  # 网络访问
    CODE_EXECUTION = "code_execution"  # 代码执行
    LLM_INFERENCE = "llm_inference"  # LLM 推理
    DATABASE = "database"  # 数据库访问
    EXTERNAL_API = "external_api"  # 外部 API
    SANDBOXED = "sandboxed"  # 沙箱内安全操作


class PermissionLevel(Enum):
    """权限级别"""
    READ_ONLY = "read_only"  # 只读
    READ_WRITE = "read_write"  # 读写
    EXECUTE = "execute"  # 可执行
    PRIVILEGED = "privileged"  # 特权（需人类审批）


@dataclass
class ToolPermissions:
    """工具权限配置"""
    level: PermissionLevel
    allowed_zones: List[str] = field(default_factory=lambda: ["sandbox"])  # 允许调用的安全区
    rate_limit_per_min: Optional[int] = None  # 每分钟调用上限
    requires_approval: bool = False  # 是否需要人类审批
    audit_logging: bool = True  # 是否记录审计日志
    network_access: bool = False  # 是否允许网络访问
    filesystem_paths: List[str] = field(default_factory=list)  # 允许访问的文件系统路径


@dataclass
class LaapTool:
    """LAAP 工具描述符"""
    name: str
    description: str
    category: ToolCategory
    input_schema: Dict[str, Any]  # JSON Schema 描述输入
    output_schema: Dict[str, Any]  # JSON Schema 描述输出
    permissions: ToolPermissions
    implemented_by: Optional[str] = None  # 实现该工具的模块路径
    mcp_compatible: bool = False  # 是否兼容 MCP
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolInvocationResult:
    """工具调用结果"""
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time_sec: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    audit_record_id: Optional[str] = None  # 审计记录 ID


class ToolProtocol(ABC):
    """LAAP-TOOL 工具协议抽象基类

    定义工具注册、查询、调用的标准接口。
    通过 MCP 适配器可接入标准 MCP 工具生态。
    """

    @abstractmethod
    def register_tool(
        self, tool: LaapTool, handler: Optional[Callable] = None
    ) -> None:
        """注册工具

        Args:
            tool: 工具描述符
            handler: 可选的调用处理器（若为 None 则通过 implemented_by 反射调用）
        """
        ...

    @abstractmethod
    def unregister_tool(self, name: str) -> bool:
        """注销工具

        Args:
            name: 工具名称

        Returns:
            是否成功注销
        """
        ...

    @abstractmethod
    def invoke_tool(
        self,
        name: str,
        args: Dict[str, Any],
        invocation_context: Optional[Dict[str, Any]] = None,
    ) -> ToolInvocationResult:
        """调用工具

        在调用前校验权限、检查 rate limit、记录审计日志。

        Args:
            name: 工具名称
            args: 调用参数（符合 tool.input_schema）
            invocation_context: 可选的调用上下文（含 sandbox_id, zone 等）

        Returns:
            ToolInvocationResult 包含执行结果
        """
        ...

    @abstractmethod
    def list_tools(
        self,
        category: Optional[ToolCategory] = None,
        permissions_required: Optional[PermissionLevel] = None,
    ) -> List[LaapTool]:
        """列出可用工具

        Args:
            category: 可选的类别过滤
            permissions_required: 可选的权限级别过滤

        Returns:
            匹配的工具列表
        """
        ...

    @abstractmethod
    def adapt_mcp_tool(self, mcp_tool: Any) -> LaapTool:
        """将 MCP 工具适配为 LAAP 工具

        MCP 工具通常包含 name/description/inputSchema 等字段，
        本方法将其映射到 LaapTool 结构。

        Args:
            mcp_tool: MCP 工具对象（含 name, description, inputSchema 等字段）

        Returns:
            LaapTool 适配后的工具描述符
        """
        ...
