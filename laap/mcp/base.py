"""LAAP MCP — Minimal JSON-RPC message definitions and transport interface.

This module defines the lightweight MCP protocol used by LAAP's built-in
client/server stack.  It intentionally avoids the official ``mcp`` SDK so the
stack stays dependency-free.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MCPMessage:
    """A JSON-RPC 2.0-like message.

    Requests carry ``method`` and ``params``; responses carry ``result`` or
    ``error``.  Notifications omit ``id``.
    """

    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

    def is_request(self) -> bool:
        return self.method is not None

    def is_response(self) -> bool:
        return self.result is not None or self.error is not None

    def is_notification(self) -> bool:
        return self.method is not None and self.id is None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            data["id"] = self.id
        if self.method is not None:
            data["method"] = self.method
        if self.params is not None:
            data["params"] = self.params
        if self.result is not None:
            data["result"] = self.result
        if self.error is not None:
            data["error"] = self.error
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPMessage":
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method"),
            params=data.get("params"),
            result=data.get("result"),
            error=data.get("error"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "MCPMessage":
        return cls.from_dict(json.loads(raw))


@dataclass
class MCPRequest(MCPMessage):
    """Convenience dataclass for outbound requests."""

    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResponse(MCPMessage):
    """Convenience dataclass for outbound responses."""

    result: Any = None
    error: Optional[Dict[str, Any]] = None


class MCPTransport(ABC):
    """Abstract transport for MCP messages."""

    @abstractmethod
    async def send(self, message: MCPMessage) -> None:
        """Send *message* to the peer."""
        raise NotImplementedError

    @abstractmethod
    async def receive(self) -> Optional[MCPMessage]:
        """Receive the next message from the peer, or ``None`` if closed."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release transport resources.  Subclasses may override."""
        pass
