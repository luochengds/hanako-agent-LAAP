"""LAAP — Model Context Protocol (MCP)

Two stacks coexist in this package:

* ``LAAPMCPServer`` / ``MCPClientManager`` / ``MCPClientConnection`` — the
  original FastMCP/official-SDK based implementation (optional dependency on
  the ``mcp`` package).
* ``MCPServer`` / ``MCPClient`` / ``MCPConfig`` — the lightweight built-in
  JSON-RPC stack with no extra dependencies.
"""

from laap.mcp.server import LAAPMCPServer, MCPServer
from laap.mcp.client import MCPClient, MCPClientConnection, MCPClientManager, MCPToolDef
from laap.mcp.config import MCPConfig, add_server, remove_server, list_servers, load_config
from laap.mcp.lifecycle import MCPLifecycleManager, MCPServerConfig, MCPServerInstance, ServerState
from laap.mcp.oauth import oauth_flow, get_token, has_token, remove_token
from laap.mcp.session_registry import MCPSessionRegistry, get_registry

__all__ = [
    "LAAPMCPServer",
    "MCPServer",
    "MCPClient",
    "MCPClientConnection",
    "MCPClientManager",
    "MCPToolDef",
    "MCPConfig",
    "MCPLifecycleManager",
    "MCPServerConfig",
    "MCPServerInstance",
    "ServerState",
    "MCPSessionRegistry",
    "get_registry",
    "add_server",
    "remove_server",
    "list_servers",
    "load_config",
    "oauth_flow",
    "get_token",
    "has_token",
    "remove_token",
]
