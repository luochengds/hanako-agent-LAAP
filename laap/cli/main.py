"""LAAP CLI Main Entry — Enhanced

扩展CLI入口，增加wizard/dashboard/server子命令，
支持--json输出模式、颜色输出、自动补全提示。
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import argparse
import os
import sys
from pathlib import Path

try:
    from laap.cli.skins.dragon import GOLD, GOLD_BRIGHT, GOLD_DIM, RESET, BOLD
except ImportError:
    GOLD = GOLD_BRIGHT = GOLD_DIM = RESET = BOLD = ""

COMMANDS = {
    "agent":     {"help": "Interactive agent session",         "module": "agent_cmd"},
    "chat":      {"help": "Single-turn chat",                  "module": "chat_cmd"},
    "tools":     {"help": "Tool management",                   "module": "tools_cmd"},
    "platform":  {"help": "Platform management",               "module": "platform_cmd"},
    "plugin":    {"help": "Plugin management",                 "module": "plugin_cmd"},
    "memory":    {"help": "Memory management",                 "module": "memory_cmd"},
    "skill":     {"help": "Skill management",                  "module": "skill_cmd"},
    "system":    {"help": "System information",                "module": "system_cmd"},
    "config":    {"help": "Configuration management",          "module": "config_cmd"},
    "server":    {"help": "Start SSE server",                  "module": "server_cmd"},
    "wizard":    {"help": "Run setup wizard",                  "module": "wizard_cmd"},
    "dashboard": {"help": "Show system dashboard",            "module": "dashboard_cmd"},
    "launch":    {"help": "Launch LAAP full entity",           "module": "launch_cmd"},
    "reach":     {"help": "Agent-Reach internet channels",     "module": "reach_cmd"},
}

_EPILOG = f"""
{GOLD_DIM}Additional options:{RESET}
  {GOLD}--json{RESET}        Output in JSON format (where supported)
  {GOLD}--no-color{RESET}    Disable colored output
  {GOLD}--help{RESET}        Show this help message

{GOLD_DIM}Examples:{RESET}
  {GOLD}laap wizard{RESET}             Run the setup wizard
  {GOLD}laap dashboard{RESET}          Show live dashboard
  {GOLD}laap agent{RESET}              Start interactive agent
  {GOLD}laap server --port 8080{RESET} Start SSE server on port 8080
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laap",
        description=f"{BOLD}LAAP{GOLD} — Lifeform Autonomous Adaptive Protocol CLI{RESET}",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-v", action="store_true",
                        help="Show version and exit")
    parser.add_argument("--capabilities", action="store_true",
                        help="List current LAAP capabilities and exit")
    parser.add_argument("--json", action="store_true",
                        help="Output in JSON format (where supported)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")
    sub = parser.add_subparsers(dest="command", metavar="{command}")
    for cmd_name, cmd_info in COMMANDS.items():
        if cmd_name in ("launch", "chat"):
            continue  # 使用自定义参数注册（见下方）
        p = sub.add_parser(cmd_name, help=cmd_info["help"],
                           add_help=False,
                           description=f"{cmd_info['help'].capitalize()}.")
        p.add_argument("action", nargs="?", default="start",
                       help=f"Action for {cmd_name} (default: start)")
        p.add_argument("args", nargs=argparse.REMAINDER,
                       help="Additional arguments")
    # chat 子命令使用 Hermes 风格 CLI 参数注册
    try:
        from laap.cli.subcommands import chat_cmd
        chat_cmd.build_parser(sub)
    except ImportError as e:
        logger.warning(f"Failed to load chat command: {e}")
    # launch 子命令使用自定义参数注册
    try:
        from laap.cli.subcommands import launch_cmd
        launch_cmd.add_parser(sub)
    except ImportError as e:
        logger.warning(f"Failed to load launch command: {e}")
    # 未指定子命令时默认进入 chat
    parser.set_defaults(command="chat")
    return parser


def _launch_tui() -> None:
    """Launch the full-screen LAAP TUI."""
    try:
        from laap.ui.tui import run_tui
        run_tui()
    except RuntimeError as exc:
        if "Textual is not installed" in str(exc):
            logger.error("Textual is not installed; cannot launch TUI.")
        else:
            logger.error(f"TUI launch failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"TUI launch failed: {exc}")
        sys.exit(1)


def main() -> None:
    parser = build_parser()

    json_output = False
    launch_tui = False
    force_cli = False
    filtered_argv = []
    i = 0
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--json":
            json_output = True
        elif arg == "--no-color":
            try:
                import laap.cli.skins.dragon as skin
                for attr in ("GOLD", "GOLD_BRIGHT", "GOLD_DIM", "RESET", "BOLD"):
                    setattr(skin, attr, "")
            except ImportError:
                pass  # 可选模块，降级处理
        elif arg == "--tui":
            launch_tui = True
        elif arg == "--cli":
            force_cli = True
        else:
            filtered_argv.append(arg)
        i += 1

    sys.argv = filtered_argv
    args = parser.parse_args()

    if args.version:
        logger.info(f"LAAP v1.0.0")
        logger.info(f"Python: {sys.version.split()[0]}")
        sys.exit(0)

    if args.capabilities:
        from laap.cli.commands import print_capabilities
        print_capabilities()
        sys.exit(0)

    # Global --tui flag overrides subcommand dispatch
    if launch_tui:
        _launch_tui()
        sys.exit(0)

    # Global --cli flag forces the chat REPL
    if force_cli:
        args.command = "chat"

    if not args.command:
        # Default fallback should not happen because parser defaults to chat,
        # but keep a safe help print here.
        parser.print_help()
        sys.exit(0)

    cmd_info = COMMANDS.get(args.command)
    if not cmd_info:
        logger.info(f"Unknown command: {args.command}")
        sys.exit(1)

    try:
        mod = __import__(
            f"laap.cli.subcommands.{cmd_info['module']}",
            fromlist=["run"],
        )
        if json_output:
            args.json = True
        mod.run(args)
    except ImportError as e:
        logger.error(f"Error loading command '{args.command}': {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error executing '{args.command}': {e}")
        if json_output:
            import json
            logger.error(json.dumps({"error": str(e), "command": args.command}))
        sys.exit(1)


def cli_entry() -> None:
    main()


if __name__ == "__main__":
    main()
