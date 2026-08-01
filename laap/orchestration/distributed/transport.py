"""Low-level asyncio transports for distributed ActorSystem communication."""

from __future__ import annotations

import abc
import asyncio
import os
import sys
from collections.abc import Callable, Coroutine

if sys.platform == "win32":
    import pywintypes  # type: ignore[import]
    import win32file  # type: ignore[import]
    import win32pipe  # type: ignore[import]


class Transport(abc.ABC):
    """Abstract transport layer for node-to-node messaging."""

    @abc.abstractmethod
    async def listen(
        self,
        host: str,
        port: int,
        on_message: Callable[[bytes], Coroutine[None, None, None]],
    ) -> None:
        """Start listening for incoming payloads on *host*:*port*."""
        raise NotImplementedError

    @abc.abstractmethod
    async def send(self, host: str, port: int, payload: bytes) -> None:
        """Send *payload* to *host*:*port*."""
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """Release all transport resources."""
        raise NotImplementedError


class TCPTransport(Transport):
    """Length-prefixed TCP transport."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None

    async def listen(
        self,
        host: str,
        port: int,
        on_message: Callable[[bytes], Coroutine[None, None, None]],
    ) -> None:
        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                raw_len = await reader.readexactly(4)
                length = int.from_bytes(raw_len, "big")
                payload = await reader.readexactly(length)
                await on_message(payload)
            except asyncio.IncompleteReadError:
                pass
            except Exception:
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        self._server = await asyncio.start_server(_handle, host, port)

    async def send(self, host: str, port: int, payload: bytes) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            length_bytes = len(payload).to_bytes(4, "big")
            writer.write(length_bytes + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class IPCTransport(Transport):
    """Inter-process transport.

    Uses Windows named pipes on Windows and Unix domain sockets elsewhere.
    The *host* and *port* parameters of ``listen``/``send`` are ignored;
    the endpoint is identified by ``name`` given at construction.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        if sys.platform == "win32":
            self._path = f"\\\\.\\pipe\\{name}"
        else:
            self._path = f"/tmp/laap_ipc_{name}.sock"
        self._server: asyncio.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def listen(
        self,
        host: str,
        port: int,
        on_message: Callable[[bytes], Coroutine[None, None, None]],
    ) -> None:
        if sys.platform == "win32":
            self._running = True
            self._task = asyncio.create_task(self._windows_listen_loop(on_message))
        else:
            if os.path.exists(self._path):
                os.unlink(self._path)

            async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    payload = await reader.read()
                    if payload:
                        await on_message(payload)
                except Exception:
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()

            self._server = await asyncio.start_unix_server(_handle, self._path)

    async def _windows_listen_loop(
        self,
        on_message: Callable[[bytes], Coroutine[None, None, None]],
    ) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                data = await loop.run_in_executor(None, self._windows_accept_one)
                if data:
                    await on_message(data)
            except asyncio.CancelledError:
                break
            except Exception:
                if self._running:
                    await asyncio.sleep(0.05)

    def _windows_accept_one(self) -> bytes:
        pipe = win32pipe.CreateNamedPipe(
            self._path,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65536,
            65536,
            0,
            None,
        )
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            chunks: list[bytes] = []
            while True:
                try:
                    _hr, data = win32file.ReadFile(pipe, 65536)
                    if not data:
                        break
                    chunks.append(data)
                except pywintypes.error as exc:  # type: ignore[name-defined]
                    if exc.winerror == 109:  # ERROR_BROKEN_PIPE
                        break
                    raise
            return b"".join(chunks)
        finally:
            win32file.CloseHandle(pipe)

    async def send(self, host: str, port: int, payload: bytes) -> None:
        if sys.platform == "win32":
            await asyncio.to_thread(self._windows_send, payload)
        else:
            reader, writer = await asyncio.open_unix_connection(self._path)
            try:
                writer.write(payload)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

    def _windows_send(self, payload: bytes) -> None:
        handle = win32file.CreateFile(
            self._path,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        try:
            if payload:
                win32file.WriteFile(handle, payload)
        finally:
            win32file.CloseHandle(handle)

    async def close(self) -> None:
        self._running = False
        if sys.platform == "win32":
            # Connect to the pipe without writing data so the accept loop can exit.
            try:
                await asyncio.to_thread(self._windows_send, b"")
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            if sys.platform != "win32" and os.path.exists(self._path):
                os.unlink(self._path)
