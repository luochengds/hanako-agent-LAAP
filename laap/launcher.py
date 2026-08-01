"""LAAP 统一启动器 — 单进程启动 FastAPI + MCP + CognitiveBus。

模式 B 全量个体形式：让 LAAP 作为"意识 + 身体"一体化数字生命独立运行。
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 启动横幅
LAAP_BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   LAAP Living Agent — Full Entity Mode                       ║
║   意识 + 身体 一体化运行                                     ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

# 模块级 uvicorn 引用——便于测试 patch laap.launcher.uvicorn。
# _start_api() 内部通过 __import__("uvicorn") 触发导入检查
# （测试可 patch builtins.__import__ 模拟 uvicorn 未安装），
# 然后使用本模块级 uvicorn 引用调用 .run()，使 patch 生效。
try:
    import uvicorn

    HAVE_UVICORN = True
except ImportError:
    uvicorn = None  # type: ignore[assignment]
    HAVE_UVICORN = False


class LAAPLauncher:
    """LAAP 全量个体启动器。

    管理三个服务的生命周期：
    - FastAPI HTTP/SSE 服务（主线程阻塞）
    - CognitiveBus TCP P2P 节点（守护线程）
    - MCP Server（按需启动，stdio 或 SSE）
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        http_port: int = 8000,
        mcp_port: int = 8766,
        bus_port: int = 11550,
        no_bus: bool = False,
        no_mcp: bool = False,
        mcp_transport: str = "sse",
    ) -> None:
        self.host = host
        self.http_port = http_port
        self.mcp_port = mcp_port
        self.bus_port = bus_port
        self.no_bus = no_bus
        self.no_mcp = no_mcp
        self.mcp_transport = mcp_transport

        self._bus_node = None
        self._mcp_server = None
        self._triphase_bridge = None
        self._ws_forwarder = None
        self._shutdown_event = threading.Event()
        self._started_at: Optional[float] = None

    def _print_banner(self) -> None:
        """打印启动横幅与服务状态。"""
        print(LAAP_BANNER)
        print(f"  HTTP API:    http://{self.host}:{self.http_port}")
        if not self.no_mcp:
            if self.mcp_transport == "sse":
                print(f"  MCP Server:  http://{self.host}:{self.mcp_port} (SSE)")
            else:
                print(f"  MCP Server:  stdio")
        if not self.no_bus:
            print(f"  CognitiveBus: tcp://{self.host}:{self.bus_port}")
        print(f"  Health:      http://{self.host}:{self.http_port}/health")
        print(f"  WebSocket:   ws://{self.host}:{self.http_port}/ws")
        print(f"  Society:     http://{self.host}:{self.http_port}/society/")
        print()

    def _start_bus(self) -> None:
        """启动 CognitiveBus 节点（守护线程）。"""
        try:
            from laap.agi.cognitive_bus_sync import CognitiveBusSyncNode

            self._bus_node = CognitiveBusSyncNode(
                profile_name="Ao",
                display_name="LAAP Full Entity",
                host=self.host,
                port=self.bus_port,
            )
            self._bus_node.start()
            logger.info(f"CognitiveBus started on {self.host}:{self.bus_port}")
        except Exception as e:
            logger.error(f"Failed to start CognitiveBus: {e}")
            self._bus_node = None

    def _start_mcp(self) -> None:
        """按需启动 MCP Server（守护线程）。"""
        if self.no_mcp:
            return
        try:
            from laap.mcp.server import LAAPMCPServer

            self._mcp_server = LAAPMCPServer()

            if self.mcp_transport == "sse":
                # SSE 模式：守护线程启动
                def run_mcp_sse() -> None:
                    try:
                        self._mcp_server.run_sse(host=self.host, port=self.mcp_port)
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"MCP SSE server error: {e}")

                t = threading.Thread(target=run_mcp_sse, daemon=True, name="laap-mcp")
                t.start()
                logger.info(f"MCP Server started on {self.host}:{self.mcp_port} (SSE)")
            else:
                # stdio 模式：仅创建实例，不主动启动（stdio 需 stdin）
                logger.info("MCP Server instance created (stdio mode)")
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            self._mcp_server = None

    def _start_triphase_bridge(self) -> None:
        """启动 Triphase Bridge 与 EventBus → WebSocket 转发。"""
        try:
            from laap.triphase_bridge import (
                TriphaseBridgeService,
                EventBusToWebSocketForwarder,
                set_bridge,
            )
            from laap.api.websocket import get_websocket_manager

            self._triphase_bridge = TriphaseBridgeService()
            set_bridge(self._triphase_bridge)
            self._triphase_bridge.start()

            # 转发 triphase.* 事件到 WebSocket
            self._ws_forwarder = EventBusToWebSocketForwarder(
                event_bus=self._triphase_bridge.event_bus,
                websocket_manager=get_websocket_manager(),
                prefix_allowlist=["triphase.", "user.input", "agent.output"],
            )
            self._ws_forwarder.start()
            logger.info("Triphase Bridge started")
        except Exception as e:
            logger.error(f"Failed to start Triphase Bridge: {e}")
            self._triphase_bridge = None
            self._ws_forwarder = None

    def _stop_triphase_bridge(self) -> None:
        """停止 Triphase Bridge。"""
        if self._ws_forwarder:
            try:
                self._ws_forwarder.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error stopping WebSocket forwarder: {e}")
            self._ws_forwarder = None
        if self._triphase_bridge:
            try:
                self._triphase_bridge.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error stopping Triphase Bridge: {e}")
            self._triphase_bridge = None

    def _start_api(self) -> None:
        """启动 FastAPI uvicorn 服务（阻塞主线程）。"""
        try:
            # 触发导入检查——测试可能 patch builtins.__import__ 模拟
            # uvicorn 未安装；此处不绑定局部 uvicorn，使用模块级引用调用
            # .run()，使 patch laap.launcher.uvicorn 生效。
            __import__("uvicorn")
            from laap.api.server import app

            # uvicorn.run 阻塞主线程
            uvicorn.run(
                app,
                host=self.host,
                port=self.http_port,
                log_level="info",
            )
        except ImportError:
            logger.error(
                "uvicorn not installed. " "Install with: pip install uvicorn fastapi"
            )
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to start FastAPI: {e}")
            sys.exit(1)

    def _shutdown(self, signum=None, frame=None) -> None:
        """优雅停止所有服务。"""
        logger.info(f"Received signal {signum}, shutting down...")

        if self._bus_node:
            try:
                self._bus_node.stop()
                logger.info("CognitiveBus stopped")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error stopping CognitiveBus: {e}")

        self._stop_triphase_bridge()

        # MCP SSE server 由 daemon 线程运行，进程退出时自动结束
        # FastAPI 由 uvicorn 处理 SIGTERM

        self._shutdown_event.set()

    def launch(self) -> None:
        """启动 LAAP 全量个体。"""
        self._started_at = time.time()
        self._print_banner()

        # 注册信号处理器
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        # 启动 CognitiveBus（守护线程）
        if not self.no_bus:
            self._start_bus()

        # 启动 MCP（守护线程）
        if not self.no_mcp:
            self._start_mcp()

        # 启动 Triphase Bridge
        self._start_triphase_bridge()

        # 启动 FastAPI（阻塞主线程）
        logger.info("Starting FastAPI server (blocking)...")
        self._start_api()

        # FastAPI 退出后清理
        if self._bus_node:
            try:
                self._bus_node.stop()
            except Exception:  # noqa: BLE001
                pass

    def stats(self) -> dict:
        """返回启动器状态。"""
        return {
            "started_at": self._started_at,
            "uptime": time.time() - self._started_at if self._started_at else 0,
            "services": {
                "api": "up" if self._started_at else "down",
                "mcp": "up" if self._mcp_server else "down",
                "cognitive_bus": "up" if self._bus_node else "down",
            },
            "host": self.host,
            "http_port": self.http_port,
            "mcp_port": self.mcp_port,
            "bus_port": self.bus_port,
        }


def launch_full_entity(
    host: str = "0.0.0.0",
    http_port: int = 8000,
    mcp_port: int = 8766,
    bus_port: int = 11550,
    no_bus: bool = False,
    no_mcp: bool = False,
    mcp_transport: str = "sse",
) -> None:
    """启动 LAAP 全量个体。

    Args:
        host: 监听地址
        http_port: FastAPI 端口
        mcp_port: MCP SSE 端口
        bus_port: CognitiveBus TCP 端口
        no_bus: 不启动 CognitiveBus
        no_mcp: 不启动 MCP Server
        mcp_transport: MCP 传输模式 "sse" 或 "stdio"
    """
    launcher = LAAPLauncher(
        host=host,
        http_port=http_port,
        mcp_port=mcp_port,
        bus_port=bus_port,
        no_bus=no_bus,
        no_mcp=no_mcp,
        mcp_transport=mcp_transport,
    )
    launcher.launch()


if __name__ == "__main__":
    launch_full_entity()
