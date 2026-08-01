"""LAAP package entry point — python -m laap.

Launches the full-screen Hermes-style TUI by default.  Pass ``--cli`` to force
the classic interactive REPL instead.  When stdout/stdin is not a TTY or Textual
is not installed, falls back to the REPL automatically.

No module-level side effects; all startup logic runs inside ``main()``.
"""

import argparse
import logging
import os
import sys

# Make the package importable when run directly from source.
_LAAP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LAAP_ROOT not in sys.path:
    sys.path.insert(0, _LAAP_ROOT)

from laap.cli.commands import handle_capabilities


def _configure_debug_logging() -> None:
    """Enable verbose debug logging for startup diagnostics."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    os.environ["LAAP_DEBUG"] = "1"


def _run_tui() -> int:
    """Launch the LAAP TUI, falling back to REPL on failure."""
    logger = logging.getLogger("laap.__main__")
    logger.debug("[DEBUG] Entering _run_tui")
    try:
        from laap.ui.tui import HAS_TEXTUAL, run_tui
        logger.debug("[DEBUG] Textual availability: HAS_TEXTUAL=%s", HAS_TEXTUAL)
        run_tui()
        return 0
    except RuntimeError as exc:
        if "Textual is not installed" in str(exc):
            print("[WARN] Textual not installed, falling back to REPL mode.", file=sys.stderr)
        else:
            print(f"[ERROR] TUI failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[ERROR] TUI failed: {exc}", file=sys.stderr)
    return _run_repl()


def _run_repl() -> int:
    """Launch the classic Hermes-style REPL."""
    from laap.cli.main import main as cli_main
    # Pass through to chat subcommand which launches the REPL
    sys.argv = [sys.argv[0], "chat"]
    cli_main()
    return 0


def main() -> int:
    """Entry point for ``python -m laap``."""
    if handle_capabilities():
        return 0

    parser = argparse.ArgumentParser(
        prog="python -m laap",
        description="LAAP — Lifeform Autonomous Adaptive Protocol",
        add_help=False,
    )
    parser.add_argument("--cli", action="store_true", help="Use classic REPL instead of TUI")
    parser.add_argument("--tui", action="store_true", help="Force full-screen TUI even when not a TTY")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging for startup diagnostics")
    parser.add_argument("-h", "--help", action="store_true", help="Show this help message")
    parser.add_argument("--capabilities", action="store_true", help="List capabilities and exit")
    args, remaining = parser.parse_known_args()

    if args.debug:
        _configure_debug_logging()

    if args.help:
        parser.print_help()
        print("\nAll other arguments are forwarded to the LAAP CLI.")
        return 0

    if args.cli:
        return _run_repl()

    if not args.tui and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("[WARN] Stdout/stdin not a TTY — using REPL mode instead of full-screen TUI.", file=sys.stderr)
        return _run_repl()

    return _run_tui()


if __name__ == "__main__":
    sys.exit(main())
