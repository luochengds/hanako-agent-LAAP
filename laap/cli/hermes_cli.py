"""Hermes-style LAAP CLI foundation.

A minimal, self-contained REPL frontend that captures core Hermes design patterns:
- prompt_toolkit-based input with history/completion (falls back to input())
- rich.console.Console for structured output
- central slash-command registry built on laap.cli.commands
- session persistence via laap.store.session_manager
- configurable tool-progress display
- streaming response placeholder
- inline approval callback for dangerous commands
"""

from __future__ import annotations

import argparse
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from laap.cli.commands import resolve, help_text, COMMAND_REGISTRY
from laap.store.session_manager import SessionManager, FileSessionStore, SessionRecord

# prompt_toolkit is optional; prompt-toolkit>=3.0.0 is declared in pyproject.toml.
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import FuzzyWordCompleter
    from prompt_toolkit.styles import Style as PTKStyle

    HAS_PROMPT_TOOLKIT = True
except Exception:  # pragma: no cover - defensive import
    HAS_PROMPT_TOOLKIT = False

HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".laap")
HISTORY_FILE = os.path.join(HISTORY_DIR, "hermes_cli_history")

TOOL_PROGRESS_MODES = ("off", "new", "all", "verbose")
APPROVAL_CHOICES = ("y", "n", "once", "session", "always")


def _ensure_history_dir() -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)


@dataclass
class HermesMessage:
    role: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_record(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class HermesStyleCLI:
    """Minimal Hermes-style REPL for LAAP.

    Parameters:
        session_id: Optional explicit session id. If not provided, a new id is generated.
        console: Optional rich Console instance.
        session_manager: Optional SessionManager instance.
        progress_mode: Tool progress display mode — one of ``off/new/all/verbose``.
        input_fn: Optional replacement for ``input()`` used in fallback/approval prompts.
        output_fn: Optional replacement for stdout printing.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        console: Optional[Console] = None,
        session_manager: Optional[SessionManager] = None,
        progress_mode: str = "new",
        input_fn: Optional[Callable[[str], str]] = None,
        output_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.session_id = session_id or f"hermes_{uuid.uuid4().hex[:12]}"
        self.console = console or Console(stderr=False)
        self.session_manager = session_manager or SessionManager(FileSessionStore())
        self.progress_mode = progress_mode if progress_mode in TOOL_PROGRESS_MODES else "new"
        self.input_fn = input_fn or input
        self.output_fn = output_fn or (lambda text: self.console.print(text))

        self.messages: List[HermesMessage] = []
        self.running = True
        self._session_approved_tools: set = set()
        self._globally_approved_tools: set = set()

        # prompt_toolkit session (lazy)
        self._pt_session: Optional[Any] = None
        self._setup_prompt_toolkit()
        self._ensure_session()

    # ── Public API ──

    @property
    def approved_tools(self) -> set:
        """Set of tool names currently approved for this session."""
        return self._session_approved_tools | self._globally_approved_tools

    def run(self) -> int:
        """Run the REPL until /exit. Returns exit code."""
        self.print_banner()
        while self.running:
            try:
                line = self.read_line()
            except (EOFError, KeyboardInterrupt):
                self.log_info("Session ended by user.")
                break
            if line is None:
                continue
            self.dispatch(line)
        self.close_session()
        return 0

    def dispatch(self, line: str) -> None:
        """Dispatch a single REPL line."""
        line = line.strip()
        if not line:
            return

        if line.startswith("/"):
            self._handle_slash(line)
            return

        self._handle_chat(line)

    def read_line(self) -> Optional[str]:
        """Read one line of user input."""
        prompt = self._build_prompt()
        if self._pt_session is not None:
            try:
                return self._pt_session.prompt(prompt).strip()
            except Exception as exc:  # pragma: no cover
                logger.debug(f"[WARN] prompt_toolkit failed, falling back: {exc}")
        try:
            return self.input_fn(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise

    def handle_approval(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        dangerous_score: float = 0.0,
    ) -> Tuple[bool, str]:
        """Approval callback for dangerous tool invocations.

        Returns a tuple of (allowed, decision) where decision is one of
        ``y/n/once/session/always``.
        """
        if tool_name in self._globally_approved_tools:
            return True, "always"
        if tool_name in self._session_approved_tools:
            return True, "session"

        if self.progress_mode == "off":
            return False, "n"

        args_text = " ".join(f"{k}={v}" for k, v in arguments.items())
        self.console.print(
            Panel(
                f"Tool: [bold]{tool_name}[/bold]\nArgs: {args_text}\nRisk score: {dangerous_score:.2f}",
                title="[yellow]Approval Required[/yellow]",
                border_style="yellow",
            )
        )
        choice = self._prompt_approval(tool_name)
        if choice == "y":
            return True, "y"
        if choice == "once":
            return True, "once"
        if choice == "session":
            self._session_approved_tools.add(tool_name)
            return True, "session"
        if choice == "always":
            self._globally_approved_tools.add(tool_name)
            return True, "always"
        return False, "n"

    def stream_response(self, text: str) -> str:
        """Placeholder for streaming response support.

        Subclasses can override this to wire in a real LLM. The default returns
        a deterministic echo so the REPL remains usable out of the box.
        """
        self.console.print(f"[dim]Ao is thinking about:[/dim] {text}")
        return f"Echo: {text}"

    def save_session(self, name: Optional[str] = None) -> str:
        """Persist current messages to the session store."""
        name = name or self.session_id
        session = self.session_manager.get(name)
        if session is None:
            session = self.session_manager.create(name)
        record = self._session_record(name)
        self.session_manager.store.save(record, [m.to_record() for m in self.messages])
        return name

    def load_session(self, name: str) -> bool:
        """Load messages from a persisted session."""
        session = self.session_manager.get(name)
        if session is None:
            return False
        messages = self.session_manager.recover(name) or []
        self.messages = [self._message_from_record(m) for m in messages]
        self.session_id = name
        return True

    def list_sessions(self) -> List[SessionRecord]:
        return self.session_manager.store.list_sessions()

    def print_banner(self) -> None:
        title = Text("LAAP Hermes CLI", style="bold bright_yellow")
        subtitle = Text("Lifeform Autonomous Adaptive Protocol", style="dim")
        self.console.print(Panel(f"{title}\n{subtitle}", border_style="yellow"))
        self.console.print(f"[dim]Session:[/dim] {self.session_id}")
        self.console.print(f"[dim]Type /help for commands, /exit to quit.[/dim]\n")

    def log(self, level: str, message: str) -> None:
        """Structured log with labels [OK], [ERROR], [WARN], [INFO]."""
        labels = {
            "ok": "[green][OK][/green]",
            "error": "[red][ERROR][/red]",
            "warn": "[yellow][WARN][/yellow]",
            "info": "[blue][INFO][/blue]",
        }
        self.console.print(f"{labels.get(level.lower(), level)} {message}")

    def log_ok(self, message: str) -> None:
        self.log("ok", message)

    def log_error(self, message: str) -> None:
        self.log("error", message)

    def log_warn(self, message: str) -> None:
        self.log("warn", message)

    def log_info(self, message: str) -> None:
        self.log("info", message)

    # ── Internals ──

    def _setup_prompt_toolkit(self) -> None:
        if not HAS_PROMPT_TOOLKIT:
            return
        _ensure_history_dir()
        commands = ["/" + cmd["name"] for cmd in COMMAND_REGISTRY]
        aliases = []
        for cmd in COMMAND_REGISTRY:
            aliases.extend(f"/{a}" for a in cmd.get("aliases", []))
        completer = FuzzyWordCompleter(sorted(set(commands + aliases)))
        style = PTKStyle.from_dict(
            {
                "prompt": "ansibrightyellow bold",
                "completions.completion": "bg:#1a1a2e #ffd700",
                "completions.completion.current": "bg:#ffd700 #1a1a2e bold",
            }
        )
        try:
            self._pt_session = PromptSession(
                history=FileHistory(HISTORY_FILE),
                completer=completer,
                style=style,
                complete_while_typing=True,
                vi_mode=False,
                enable_history_search=True,
            )
        except Exception as exc:  # pragma: no cover - e.g. no real TTY
            logger.debug(f"[WARN] Failed to initialise prompt_toolkit: {exc}")

    def _ensure_session(self) -> None:
        if self.session_manager.get(self.session_id) is None:
            self.session_manager.create(self.session_id)

    def _build_prompt(self) -> str:
        return "◆ Ao > "

    def _handle_slash(self, line: str) -> None:
        body = line[1:].strip()
        if not body:
            return
        parts = body.split(maxsplit=1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        resolved = resolve(name)
        handler_name = f"_cmd_{resolved or name}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            self.log_warn(f"Unknown command: /{name}  (try /help)")
            return
        try:
            handler(args)
        except Exception as exc:  # pragma: no cover
            self.log_error(f"Command /{name} failed: {exc}")

    def _handle_chat(self, line: str) -> None:
        self.messages.append(HermesMessage(role="user", content=line))
        if self.progress_mode != "off":
            self.console.print("[dim]Ao is thinking...[/dim]")
        try:
            response = self.stream_response(line)
        except Exception as exc:  # pragma: no cover
            self.log_error(f"Response failed: {exc}")
            response = ""
        if response:
            self.messages.append(HermesMessage(role="assistant", content=response))
            self.console.print(f"[bold bright_yellow]Ao:[/bold bright_yellow] {response}")
        self._maybe_auto_save()

    def _maybe_auto_save(self) -> None:
        """Lightweight autosave every 10 turns."""
        if len(self.messages) % 10 == 0:
            try:
                self.save_session()
            except Exception as exc:  # pragma: no cover
                logger.debug(f"[WARN] Autosave failed: {exc}")

    def _prompt_approval(self, tool_name: str) -> str:
        prompt = f"Approve {tool_name}? [y/N/once/session/always]: "
        try:
            raw = self.input_fn(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "n"
        if raw in ("yes", "y"):
            return "y"
        if raw in APPROVAL_CHOICES:
            return raw
        return "n"

    def _session_record(self, name: str) -> SessionRecord:
        existing = self.session_manager.get(name)
        if existing:
            existing.turn_count = len([m for m in self.messages if m.role == "user"])
            existing.updated_at = time.time()
            return existing
        return SessionRecord(session_id=name)

    @staticmethod
    def _message_from_record(record: Dict[str, Any]) -> HermesMessage:
        return HermesMessage(
            role=record.get("role", "unknown"),
            content=record.get("content", ""),
            metadata=record.get("metadata", {}),
            timestamp=record.get("timestamp", time.time()),
        )

    def close_session(self) -> None:
        try:
            self.save_session()
            self.session_manager.close(self.session_id)
        except Exception as exc:  # pragma: no cover
            logger.debug(f"[WARN] close_session failed: {exc}")

    # ── Slash command handlers ──

    def _cmd_help(self, args: str) -> None:
        if args:
            resolved = resolve(args)
            if resolved:
                self.console.print(f"[bold]/{resolved}[/bold]: help topic")
            else:
                self.log_warn(f"Unknown command topic: {args}")
            return
        self.console.print(help_text())

    def _cmd_new(self, args: str) -> None:
        self.session_manager.close(self.session_id)
        self.session_id = f"hermes_{uuid.uuid4().hex[:12]}"
        self.messages.clear()
        self._ensure_session()
        self.log_ok(f"New session started: {self.session_id}")

    def _cmd_history(self, args: str) -> None:
        if not self.messages:
            self.log_info("No messages in this session yet.")
            return
        for m in self.messages:
            role_color = "bright_yellow" if m.role == "assistant" else "white"
            self.console.print(f"[{role_color}]{m.role}:[/{role_color}] {m.content[:200]}")

    def _cmd_save(self, args: str) -> None:
        name = args.strip() or self.session_id
        try:
            self.save_session(name)
            self.log_ok(f"Session saved as '{name}'")
        except Exception as exc:  # pragma: no cover
            self.log_error(f"Save failed: {exc}")

    def _cmd_load(self, args: str) -> None:
        name = args.strip()
        if not name:
            self.log_warn("Usage: /load <session_name>")
            return
        if self.load_session(name):
            self.log_ok(f"Loaded session '{name}' ({len(self.messages)} messages)")
        else:
            self.log_error(f"Session '{name}' not found")

    def _cmd_sessions(self, args: str) -> None:
        sessions = self.list_sessions()
        if not sessions:
            self.log_info("No saved sessions.")
            return
        self.console.print("[bold]Saved sessions[/bold]")
        for s in sessions[:20]:
            updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.updated_at))
            self.console.print(f"  {s.session_id:<30s} turns={s.turn_count:<4d} {updated}")

    def _cmd_resume(self, args: str) -> None:
        name = args.strip()
        if not name:
            sessions = self.list_sessions()
            if not sessions:
                self.log_warn("No sessions to resume.")
                return
            name = sessions[0].session_id
        if self.load_session(name):
            self.log_ok(f"Resumed session '{name}'")
        else:
            self.log_error(f"Could not resume '{name}'")

    def _cmd_branch(self, args: str) -> None:
        parent_id = self.session_id
        new_id = f"hermes_{uuid.uuid4().hex[:12]}"
        old_messages = list(self.messages)
        self.session_manager.create(new_id, parent_id=parent_id)
        self.session_id = new_id
        self.messages = list(old_messages)
        self.save_session()
        self.log_ok(f"Branched to new session '{new_id}' from '{parent_id}'")

    def _cmd_tools(self, args: str) -> None:
        self.console.print("[bold]Available tools[/bold]")
        self.console.print("  Tool progress mode: [cyan]{}[/cyan]".format(self.progress_mode))
        self.console.print("  No tools registered in foundation mode.")

    def _cmd_models(self, args: str) -> None:
        self.console.print("[bold]Models[/bold]")
        self.console.print("  Foundation mode: configure a model via /config or environment variables.")

    def _cmd_config(self, args: str) -> None:
        if args:
            if args in TOOL_PROGRESS_MODES:
                self.progress_mode = args
                self.log_ok(f"Tool progress mode set to '{args}'")
            else:
                self.log_warn(f"Unknown config value: {args}")
            return
        self.console.print("[bold]Configuration[/bold]")
        self.console.print(f"  Session: {self.session_id}")
        self.console.print(f"  Progress mode: {self.progress_mode}")
        self.console.print("  Set progress mode with: /config <off|new|all|verbose>")

    def _cmd_exit(self, args: str) -> None:
        self.log_info("Ao returns to the void...")
        self.running = False

    # Backwards-compatible aliases
    _cmd_clear = _cmd_new
    _cmd_quit = _cmd_exit
    _cmd_bye = _cmd_exit


def run_hermes_cli(
    args: Optional[argparse.Namespace] = None,
    session_id: Optional[str] = None,
) -> int:
    """Programmatic entry point used by subcommands and tests."""
    progress_mode = getattr(args, "progress", "new") if args else "new"
    cli = HermesStyleCLI(session_id=session_id, progress_mode=progress_mode)
    return cli.run()
