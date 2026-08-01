"""Display — 终端显示引擎"""
from __future__ import annotations

import logging

import time, json, sys, shutil, logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.display")

class Colors:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    BLUE = "\033[94m"; MAGENTA = "\033[95m"; CYAN = "\033[96m"
    WHITE = "\033[97m"; GRAY = "\033[90m"

class Display:
    def __init__(self):
        self.width = shutil.get_terminal_size().columns
    
    def color(self, text: str, color: str) -> str:
        return f"{color}{text}{Colors.RESET}"
    
    def title(self, text: str):
        logger.info(f"\n{Colors.BOLD}{Colors.CYAN}{'='*self.width}{Colors.RESET}")
        logger.info(f" {Colors.BOLD}{text}{Colors.RESET}")
        logger.info(f"{Colors.CYAN}{'='*self.width}{Colors.RESET}")
    def section(self, text: str):
        logger.info(f"\n{Colors.BOLD}{Colors.YELLOW}▶ {text}{Colors.RESET}")
    def item(self, key: str, value: str, color: str = ""):
        c = color or Colors.WHITE
        logger.info(f"  {Colors.DIM}{key}:{Colors.RESET} {c}{value}{Colors.RESET}")
    def ok(self, text: str):
        logger.info(f"  {Colors.GREEN}✅ {text}{Colors.RESET}")
    def warn(self, text: str):
        logger.info(f"  {Colors.YELLOW}⚠️ {text}{Colors.RESET}")
    def error(self, text: str):
        logger.info(f"  {Colors.RED}❌ {text}{Colors.RESET}")
    def table(self, headers: List[str], rows: List[List[str]]):
        cols = len(headers)
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        logger.info(f"  {fmt.format(*headers)}")
        logger.info(f"  {'-'*sum(widths)}")
        for row in rows:
            logger.info(f"  {fmt.format(*[str(c) for c in row])}")
    def spinner(self, text: str = ""):
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while True:
            sys.stdout.write(f"\r{Colors.CYAN}{chars[i]}{Colors.RESET} {text}")
            sys.stdout.flush()
            i = (i + 1) % len(chars)
            yield
            time.sleep(0.1)
    
    def progress(self, current: int, total: int, prefix: str = "") -> str:
        bar_len = 20
        filled = int(bar_len * current / max(total, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        pct = current / max(total, 1) * 100
        return f"{prefix} [{Colors.GREEN}{bar}{Colors.RESET}] {pct:.0f}%"
    
    def token_usage(self, tokens_in: int, tokens_out: int, total: int = 128000):
        pct = (tokens_in + tokens_out) / max(total, 1) * 100
        color = Colors.GREEN if pct < 50 else Colors.YELLOW if pct < 80 else Colors.RED
        logger.info(f"  {Colors.DIM}Tokens:{Colors.RESET} {color}⬡{Colors.RESET} {tokens_in}→{tokens_out} ({pct:.0f}% of {total})")