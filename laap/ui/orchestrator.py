"""LAAP - Multi-Agent Orchestration System"""
import time, random, threading
from rich.text import Text
from rich.style import Style
from laap.ui.dragon_art import GOLD, GOLD_BRIGHT, GOLD_DIM, GOLD_LIGHT, CRIMSON
NL = chr(10)

class AgentNode:
    """A single agent in the orchestration tree."""
    IDLE = 0; WORKING = 1; DONE = 2; ERROR = 3
    _NAMES = {0:"IDLE",1:"WORKING",2:"DONE",3:"ERROR"}

    def __init__(self, name: str, role: str = "", parent=None):
        self.name = name
        self.role = role
        self.status = self.IDLE
        self.tokens_used = 0
        self.start_time = 0.0
        self.elapsed = 0.0
        self.task = ""
        self.progress = 0.0  # 0.0 - 1.0
        self.parent = parent
        self.children: list["AgentNode"] = []
        self._spin = 0

    def start(self, task: str = ""):
        self.status = self.WORKING
        self.start_time = time.time()
        self.task = task
        self.progress = 0.0

    def update(self, progress: float = None, tokens: int = 0):
        if progress is not None: self.progress = min(progress, 1.0)
        self.tokens_used += tokens
        self.elapsed = time.time() - self.start_time

    def complete(self, tokens: int = 0):
        self.status = self.DONE
        self.progress = 1.0
        self.tokens_used += tokens
        self.elapsed = time.time() - self.start_time

    def fail(self):
        self.status = self.ERROR
        self.elapsed = time.time() - self.start_time

    def add_child(self, name: str, role: str = "") -> "AgentNode":
        child = AgentNode(name, role, parent=self)
        self.children.append(child)
        return child

    def spin_char(self):
        chars = ["\u25d0","\u25d3","\u25d1","\u25d2"]
        self._spin = (self._spin + 1) % len(chars)
        return chars[self._spin]

    def render(self, indent: int = 0, max_depth: int = 3) -> Text:
        r = Text()
        prefix = "  " * indent
        if self.status == self.IDLE:
            r.append(prefix+"  "+chr(0x25CB)+" ", style=Style(color=GOLD_DIM))
            r.append(self.name, style=Style(color=GOLD_DIM))
        elif self.status == self.WORKING:
            s = self.spin_char()
            r.append(prefix+"  "+s+" ", style=Style(color=GOLD_BRIGHT,bold=True))
            r.append(self.name, style=Style(color=GOLD_BRIGHT,bold=True))
            if self.task: r.append(": "+self.task[:30], style=Style(color=GOLD_LIGHT,italic=True))
            bar = self._progress_bar()
            if bar: r.append(" "+bar, style=Style(color="#888888"))
            r.append(f" [{self.elapsed:.1f}s]", style=Style(color="#555555"))
        elif self.status == self.DONE:
            r.append(prefix+"  "+chr(0x2713)+" ", style=Style(color="#00D68F"))
            r.append(self.name, style=Style(color="#AAAAAA"))
            if self.elapsed: r.append(f" [{self.elapsed:.1f}s]", style=Style(color="#555555"))
            if self.tokens_used: r.append(f" t{self.tokens_used}", style=Style(color="#555555"))
        else:
            r.append(prefix+"  "+chr(0x2717)+" ", style=Style(color=CRIMSON))
            r.append(self.name, style=Style(color=CRIMSON))
        r.append(NL)
        if indent < max_depth:
            for child in self.children:
                r.append_text(child.render(indent+1, max_depth))
        return r

    def _progress_bar(self, width: int = 12) -> str:
        if self.progress <= 0: return ""
        filled = int(self.progress * width)
        empty = width - filled
        bar = chr(0x2588)*filled + chr(0x2591)*empty
        return f"[{bar}] {int(self.progress*100)}%"

    def all_tokens(self) -> int:
        t = self.tokens_used
        for c in self.children: t += c.all_tokens()
        return t


class AgentOrchestrator:
    """Manage a tree of agents with coordinated execution."""

    def __init__(self):
        self.root = AgentNode("Ao","Coordinator")
        self.current = self.root
        self._session_tokens = 0
        self._session_start = time.time()

    def add_agent(self, name: str, role: str = "") -> AgentNode:
        return self.root.add_child(name, role)

    def start_task(self, agent: AgentNode, task: str):
        agent.start(task)

    def _update_parent_progress(self, node: AgentNode):
        if not node.parent: return
        children = [c for c in node.parent.children if c.status != AgentNode.IDLE]
        if children:
            node.parent.progress = sum(c.progress for c in children) / len(children)
        self._update_parent_progress(node.parent)

    def complete_task(self, agent: AgentNode, tokens: int = 0):
        agent.complete(tokens)
        self._session_tokens += tokens
        self._update_parent_progress(agent)

    def render_tree(self) -> Text:
        r = Text()
        # Root
        r.append_text(self.root.render(0, 3))
        # Session stats
        elapsed = time.time() - self._session_start
        r.append(Text(f"\n {chr(0x2699)} Session: {elapsed:.0f}s  Tokens: {self._session_tokens}", style=Style(color="#555555")))
        return r

    def reset(self):
        self.root = AgentNode("Ao","Coordinator")
        self._session_start = time.time()
        self._session_tokens = 0

    def running_count(self) -> int:
        def _count(n): return (1 if n.status==AgentNode.WORKING else 0) + sum(_count(c) for c in n.children)
        return _count(self.root)

    def total_tokens(self) -> int:
        def _sum(n): return n.tokens_used + sum(_sum(c) for c in n.children)
        return _sum(self.root)