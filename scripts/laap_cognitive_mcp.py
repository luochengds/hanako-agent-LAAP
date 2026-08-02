#!/usr/bin/env python3
"""Launch the LAAP FastMCP server used by installer/launch.py.

The repository historically referenced this script from the installer while the
actual server implementation lived in ``laap.mcp.server``.  Keep this thin
entry point so the installer and manual launch use the same server.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# When launched by installer/launch.py, Python puts ``scripts/`` (not the
# repository root) on sys.path.  Add the package root explicitly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from laap.mcp.server import LAAPMCPServer


def main() -> int:
    parser = argparse.ArgumentParser(description="LAAP Cognitive MCP server")
    parser.add_argument("--sse", action="store_true", help="serve over SSE")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not args.sse:
        parser.error("the installer entry point requires --sse")

    logging.basicConfig(level=logging.INFO, format="[laap-mcp] %(message)s")
    server = LAAPMCPServer()
    server.run_sse(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
