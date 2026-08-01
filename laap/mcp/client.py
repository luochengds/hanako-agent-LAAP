"""LAAP MCP — Client"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from laap.mcp.base import MCPMessage, MCPRequest, MCPResponse
from laap.mcp.transports import InMemoryTransport, StdioTransport

logger = logging.getLogger("laap.mcp.client")

@dataclass
class MCPToolDef:
    server_name: str
    name: str
    description: str = ""
    input_schema: Dict = field(default_factory=dict)

class MCPClientConnection:
    def __init__(self, name: str, command: str = "",
                 args: Optional[List[str]] = None,
                 url: str = "",
                 env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.url = url
        self.env = env or {}
        self._session = None
        self._read = None
        self._write = None
        self._tools: List[MCPToolDef] = []
        self._connected = False

    async def connect(self) -> bool:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.sse import sse_client
            if self.url:
                self._read, self._write = await sse_client(self.url)
            else:
                params = StdioServerParameters(
                    command=self.command, args=self.args,
                    env={**os.environ, **self.env},
                )
                self._read, self._write = await stdio_client(params)
            self._session = await ClientSession(self._read, self._write)
            await self._session.initialize()
            result = await self._session.list_tools()
            self._tools = [
                MCPToolDef(server_name=self.name, name=t.name,
                          description=t.description or "",
                          input_schema=t.inputSchema or {})
                for t in result.tools
            ]
            self._connected = True
            logger.info(f"MCP: {self.name} connected ({len(self._tools)} tools)")
            return True
        except Exception as e:
            logger.error(f"MCP: connect {self.name} failed: {e}")
            return False

    async def call_tool(self, tool_name: str, arguments: Dict) -> str:
        if not self._session or not self._connected:
            return json.dumps({"error": "Not connected"})
        try:
            result = await self._session.call_tool(tool_name, arguments)
            texts = []
            for content in (result.content or []):
                if hasattr(content, 'text'):
                    texts.append(content.text)
                elif isinstance(content, dict):
                    texts.append(content.get('text', str(content)))
            return "\n".join(texts) if texts else "(no output)"
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def disconnect(self):
        self._connected = False
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        logger.info(f"MCP: {self.name} disconnected")

    @property
    def tools(self) -> List[MCPToolDef]:
        return list(self._tools)

    @property
    def connected(self) -> bool:
        return self._connected

class MCPClientManager:
    def __init__(self):
        self._connections: Dict[str, MCPClientConnection] = {}

    def add_stdio(self, name: str, command: str, args=None, env=None):
        self._connections[name] = MCPClientConnection(
            name=name, command=command, args=args or [], env=env or {})

    def add_sse(self, name: str, url: str):
        self._connections[name] = MCPClientConnection(name=name, url=url)

    async def connect_one(self, name: str) -> bool:
        """Connect a single named server."""
        conn = self._connections.get(name)
        if not conn:
            logger.error("MCP: no connection named '%s'", name)
            return False
        return await conn.connect()

    async def connect_all(self) -> List[str]:
        ok_list = []
        for name, conn in self._connections.items():
            if await conn.connect():
                ok_list.append(name)
        return ok_list

    def get_connection(self, name: str) -> Optional[MCPClientConnection]:
        return self._connections.get(name)

    def get_all_tools(self) -> List[MCPToolDef]:
        tools = []
        for c in self._connections.values():
            if c.connected:
                tools.extend(c.tools)
        return tools

    async def call_tool(self, server: str, tool: str, args: Dict) -> str:
        conn = self._connections.get(server)
        if not conn:
            return json.dumps({"error": f"Server {server} not found"})
        return await conn.call_tool(tool, args)

    async def disconnect_all(self):
        for c in self._connections.values():
            await c.disconnect()

    def remove(self, name: str) -> bool:
        conn = self._connections.pop(name, None)
        if conn:
            import asyncio
            asyncio.create_task(conn.disconnect())
            return True
        return False


class MCPClient:
    """Minimal JSON-RPC MCP client.

    The client talks to a server over *transport*.  It supports
    ``initialize``, ``list_tools`` and ``call_tool``.  For stdio servers it
    can spawn the subprocess via :meth:`from_stdio`.
    """

    def __init__(self, transport: Any) -> None:
        self.transport = transport
        self._closed = False
        self._tools: List[Dict[str, Any]] = []

    @classmethod
    def from_stdio(
        cls,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> "MCPClient":
        """Spawn an MCP server and return a client connected to its stdio."""
        transport = asyncio.run(StdioTransport.spawn(command, args, env, cwd))
        return cls(transport)

    async def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> MCPResponse:
        if self._closed:
            raise ConnectionResetError("client is closed")
        req = MCPRequest(id=str(uuid.uuid4()), method=method, params=params or {})
        await self.transport.send(req)
        while True:
            message = await self.transport.receive()
            if message is None:
                raise ConnectionResetError("transport closed")
            if message.id != req.id:
                continue
            return MCPResponse(
                id=message.id,
                result=message.result,
                error=message.error,
            )

    async def initialize(self) -> Dict[str, Any]:
        """Send the ``initialize`` handshake and return server info."""
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "laap-mcp-client", "version": "0.1.0"},
            },
        )
        if result.error:
            raise RuntimeError(result.error.get("message", "initialize failed"))
        return result.result or {}

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return tool schemas advertised by the server."""
        result = await self._request("tools/list", {})
        if result.error:
            raise RuntimeError(result.error.get("message", "tools/list failed"))
        tools = (result.result or {}).get("tools", [])
        self._tools = tools
        return tools

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invoke *name* with *arguments* and return the raw result dict."""
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if result.error:
            raise RuntimeError(result.error.get("message", "tools/call failed"))
        return result.result or {}

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return list(self._tools)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self.transport.close()
