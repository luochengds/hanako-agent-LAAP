"""LAAP — CLI Command System with Tab Completion"""
from __future__ import annotations
import re
from typing import Dict, List, Optional

COMMAND_REGISTRY = [
    {"name": "help", "aliases": ["h", "?"], "desc": "Show help", "category": "Info"},
    {"name": "exit", "aliases": ["quit", "bye"], "desc": "Exit LAAP", "category": "Exit"},
    {"name": "status", "aliases": ["stats", "info"], "desc": "Agent status", "category": "Session"},
    {"name": "new", "aliases": ["reset", "clear"], "desc": "New session", "category": "Session"},
    {"name": "history", "aliases": ["hist"], "desc": "Show session history", "category": "Session"},
    {"name": "save", "aliases": [], "desc": "Save session", "category": "Session"},
    {"name": "load", "aliases": [], "desc": "Load session", "category": "Session"},
    {"name": "sessions", "aliases": ["snapshots"], "desc": "List saved sessions", "category": "Session"},
    {"name": "resume", "aliases": [], "desc": "Resume a session", "category": "Session"},
    {"name": "branch", "aliases": ["fork"], "desc": "Branch current session", "category": "Session"},
    {"name": "memory", "aliases": ["mem"], "desc": "Memory management", "category": "Session"},
    {"name": "recall", "aliases": ["remember"], "desc": "Recall memories", "category": "Session"},
    {"name": "forget", "aliases": ["delete"], "desc": "Delete memory", "category": "Session"},
    {"name": "config", "aliases": ["cfg"], "desc": "Configuration", "category": "Configuration"},
    {"name": "model", "aliases": ["provider"], "desc": "Switch model", "category": "Configuration"},
    {"name": "models", "aliases": ["available_models"], "desc": "List models", "category": "Configuration"},
    {"name": "skills", "aliases": ["skill"], "desc": "List skills", "category": "Tools & Skills"},
    {"name": "tools", "aliases": ["tool"], "desc": "List tools", "category": "Tools & Skills"},
]

COMMANDS = {cmd["name"]: cmd for cmd in COMMAND_REGISTRY}
COMMANDS_BY_CATEGORY: Dict[str, List[dict]] = {}
for cmd in COMMAND_REGISTRY:
    COMMANDS_BY_CATEGORY.setdefault(cmd["category"], []).append(cmd)

def resolve(name: str) -> Optional[str]:
    n = name.lower().strip()
    for cmd in COMMAND_REGISTRY:
        if cmd["name"] == n or n in cmd.get("aliases", []):
            return cmd["name"]
    return None

def complete(partial: str) -> List[str]:
    p = partial.lower()
    results = []
    for cmd in COMMAND_REGISTRY:
        if cmd["name"].startswith(p):
            results.append(cmd["name"])
        for a in cmd.get("aliases", []):
            if a.startswith(p):
                results.append(cmd["name"])
    return sorted(set(results))

# Backward compatibility aliases
COMMAND_REGISTRY = [{"name": c["name"], "aliases": c.get("aliases", []),
                     "desc": c["desc"], "category": c.get("category", "General")} 
                    for c in COMMANDS.values()]
by_category: Dict[str, List[dict]] = {}
for cmd in COMMAND_REGISTRY:
    by_category.setdefault(cmd.get("category", "General"), []).append(cmd)

def help_text(args=None) -> str:
    lines = []
    for cat, cmds in COMMANDS_BY_CATEGORY.items():
        lines.append(f"\n  [{cat}]")
        for c in cmds:
            aliases = f" ({', '.join(c['aliases'])})" if c.get('aliases') else ""
            lines.append(f"    /{c['name']}{aliases}  — {c['desc']}")
    return "\n".join(lines)


def print_capabilities() -> None:
    """Print a formatted table of current LAAP capabilities."""
    from laap.body.capabilities import CapabilitiesReporter

    print(CapabilitiesReporter().to_table())


def handle_capabilities(argv: Optional[List[str]] = None) -> bool:
    """If *argv* contains ``--capabilities``, print them and return True."""
    import sys

    if argv is None:
        argv = sys.argv
    if "--capabilities" not in argv:
        return False
    print_capabilities()
    return True