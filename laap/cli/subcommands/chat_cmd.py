"""LAAP chat subcommand — Hermes-style interactive CLI.

Provides ``build_parser`` and ``run`` so ``laap/cli/main.py`` can dispatch
to the new Hermes-style REPL.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the ``chat`` subcommand parser."""
    parser = subparsers.add_parser(
        "chat",
        help="Start Hermes-style interactive chat CLI",
        description="Start the Hermes-style interactive REPL for LAAP.",
    )
    parser.add_argument(
        "--session",
        "-s",
        default="",
        help="Session id to resume (default: create a new session)",
    )
    parser.add_argument(
        "--progress",
        "-p",
        choices=["off", "new", "all", "verbose"],
        default="new",
        help="Tool progress display mode (default: new)",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Skip the welcome banner",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    """Launch the Hermes-style chat CLI."""
    try:
        from laap.cli.hermes_cli import HermesStyleCLI
    except ImportError as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to load Hermes CLI: {exc}")
        return 1

    session_id: Optional[str] = getattr(args, "session", None) or None
    progress_mode: str = getattr(args, "progress", "new")
    no_banner: bool = getattr(args, "no_banner", False)

    cli = HermesStyleCLI(session_id=session_id, progress_mode=progress_mode)
    if no_banner:
        # Replace the public method with a no-op for this invocation.
        cli.print_banner = lambda: None  # type: ignore[method-assign]
    return cli.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_parser(sub)
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    sys.exit(run(args))
