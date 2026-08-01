"""laap launch 子命令 — 启动 LAAP 全量个体。"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """注册 launch 子命令的参数解析器。

    Args:
        subparsers: 父 parser 的 subparsers action
    """
    parser = subparsers.add_parser(
        "launch",
        help="Launch LAAP full entity (FastAPI + MCP + CognitiveBus)",
        description="Start LAAP as a full digital lifeform entity with all services in one process.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8000,
        help="HTTP API port (default: 8000)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=8766,
        help="MCP SSE port (default: 8766)",
    )
    parser.add_argument(
        "--bus-port",
        type=int,
        default=11550,
        help="CognitiveBus TCP port (default: 11550)",
    )
    parser.add_argument(
        "--no-bus",
        action="store_true",
        help="Do not start CognitiveBus",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Do not start MCP Server",
    )
    parser.add_argument(
        "--mcp-transport",
        choices=["sse", "stdio"],
        default="sse",
        help="MCP transport mode (default: sse)",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """启动 LAAP 全量个体。

    Args:
        args: 已解析的命令行参数
    """
    from laap.launcher import launch_full_entity

    launch_full_entity(
        host=args.host,
        http_port=args.http_port,
        mcp_port=args.mcp_port,
        bus_port=args.bus_port,
        no_bus=args.no_bus,
        no_mcp=args.no_mcp,
        mcp_transport=args.mcp_transport,
    )


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_parser(subparsers)
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(0)
