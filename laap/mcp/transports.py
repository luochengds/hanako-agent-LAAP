"""LAAP MCP — Transports for the minimal MCP stack."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Dict, Optional

from laap.mcp.base import MCPMessage, MCPTransport

logger = logging.getLogger("laap.mcp.transports")


class InMemoryTransport(MCPTransport):
    """Bidirectional in-memory transport for testing.

    Pairs are created with :meth:`create_pair`.  Each endpoint has a send
    queue that feeds the peer's receive queue.
    """

    def __init__(self, send_queue: asyncio.Queue, receive_queue: asyncio.Queue) -> None:
        self._send = send_queue
        self._recv = receive_queue
        self._closed = False

    async def send(self, message: MCPMessage) -> None:
        if self._closed:
            raise ConnectionResetError("transport closed")
        await self._send.put(message)

    async def receive(self) -> Optional[MCPMessage]:
        if self._closed:
            return None
        try:
            return await self._recv.get()
        except asyncio.CancelledError:
            return None

    async def close(self) -> None:
        self._closed = True

    @classmethod
    def create_pair(cls) -> tuple["InMemoryTransport", "InMemoryTransport"]:
        """Return a connected pair of transports."""
        a_to_b: asyncio.Queue = asyncio.Queue()
        b_to_a: asyncio.Queue = asyncio.Queue()
        return cls(a_to_b, b_to_a), cls(b_to_a, a_to_b)


class StdioTransport(MCPTransport):
    """stdio transport that wraps a subprocess stdin/stdout.

    The protocol sends newline-delimited JSON messages.
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._closed = False
        self._stdin = process.stdin
        self._stdout = process.stdout
        if self._stdin is None or self._stdout is None:
            raise ValueError("process must capture stdin/stdout")

    async def send(self, message: MCPMessage) -> None:
        if self._closed or self._process.poll() is not None:
            raise ConnectionResetError("subprocess is not running")
        line = message.to_json() + "\n"
        self._stdin.write(line.encode("utf-8"))
        self._stdin.flush()

    async def receive(self) -> Optional[MCPMessage]:
        if self._closed or self._process.poll() is not None:
            return None
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, self._stdout.readline)
        if not raw:
            return None
        try:
            return MCPMessage.from_json(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Malformed MCP message: %s", exc)
            return None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
        except Exception as exc:
            logger.debug("StdioTransport close error: %s", exc)

    @classmethod
    async def spawn(
        cls,
        command: str,
        args: Optional[list] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> "StdioTransport":
        """Spawn *command* and return a transport connected to its stdio."""
        process = subprocess.Popen(
            [command, *(args or [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            text=False,
            bufsize=1,
        )
        return cls(process)


class SSETransport(MCPTransport):
    """SSE transport skeleton using ``httpx``.

    This is a minimal implementation suitable for tests and simple servers.
    It posts JSON-RPC requests to ``endpoint_url`` and streams SSE events from
    ``sse_url``.  Full bidirectional SSE requires a server-side message
    endpoint; this transport assumes responses are returned inline or via the
    SSE stream.
    """

    def __init__(
        self,
        sse_url: str,
        endpoint_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._sse_url = sse_url
        self._endpoint_url = endpoint_url or sse_url
        self._headers = headers or {}
        self._closed = True
        self._client: Optional[Any] = None
        self._response: Optional[Any] = None
        self._pending: asyncio.Queue = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None

    async def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("SSETransport requires httpx") from exc

        self._client = httpx.AsyncClient(headers=self._headers, timeout=30.0)
        self._closed = False
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            import httpx
        except ImportError:
            return
        try:
            async with self._client.stream("GET", self._sse_url, timeout=None) as response:
                self._response = response
                async for line in response.aiter_lines():
                    if self._closed:
                        break
                    line = line.strip()
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        try:
                            msg = MCPMessage.from_json(payload)
                            await self._pending.put(msg)
                        except json.JSONDecodeError:
                            logger.debug("SSE non-JSON data: %s", payload)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("SSE read loop ended: %s", exc)

    async def send(self, message: MCPMessage) -> None:
        await self._ensure_client()
        try:
            import httpx
        except ImportError as exc:
            raise ImportError("SSETransport requires httpx") from exc
        resp = await self._client.post(
            self._endpoint_url,
            json=message.to_dict(),
        )
        resp.raise_for_status()

    async def receive(self) -> Optional[MCPMessage]:
        await self._ensure_client()
        if self._closed:
            return None
        try:
            return await asyncio.wait_for(self._pending.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None

    async def close(self) -> None:
        self._closed = True
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._client is not None:
            await self._client.aclose()
            self._client = None
