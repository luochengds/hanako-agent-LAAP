"""
LAAP - Task Engine with golden dragon progress indicators.
"""
from rich.text import Text
from rich.style import Style
from laap.ui.dragon_art import GOLD, GOLD_BRIGHT, GOLD_DIM, GOLD_LIGHT, CRIMSON
from laap.ui.dragon_anim import SPIN_CHARS, SPIN_COLORS

class Task:
    """A single task with life-cycle tracking."""
    PENDING = 0
    RUNNING = 1
    DONE = 2
    FAILED = 3
    _STATUS_NAMES = {0:"PENDING",1:"RUNNING",2:"DONE",3:"FAILED"}

    def __init__(self, name: str, icon: str = ""):
        self.name = name
        self.icon = icon or "\u2699"
        self.status = self.PENDING
        self.duration = 0.0
        self._spinner = 0
        self.steps: list[str] = []

    def start(self):
        self.status = self.RUNNING
        self._spinner = 0
        self.steps = []

    def complete(self, dur: float = 0):
        self.status = self.DONE; self.duration = dur

    def fail(self, msg: str = ""):
        self.status = self.FAILED
        if msg: self.steps.append(msg)

    def add_step(self, s: str):
        self.steps.append(s)

    def spin(self):
        self._spinner = (self._spinner + 1) % len(SPIN_CHARS)
        return SPIN_CHARS[self._spinner]

    def spin_color(self):
        return SPIN_COLORS[self._spinner]

    def render(self, width: int = 40) -> Text:
        r = Text()
        if self.status == self.PENDING:
            r.append("  \u25cb ", style=Style(color=GOLD_DIM))
            r.append(self.name, style=Style(color=GOLD_DIM))
        elif self.status == self.RUNNING:
            s = self.spin()
            c = self.spin_color()
            r.append(f"  {s} ", style=Style(color=c, bold=True))
            r.append(self.name, style=Style(color=GOLD_BRIGHT, bold=True))
            if self.steps:
                r.append(f" {self.steps[-1][:width-20]}", style=Style(color="#888888", italic=True))
        elif self.status == self.DONE:
            r.append("  \u2713 ", style=Style(color="#00D68F"))
            r.append(self.name, style=Style(color="#AAAAAA"))
            if self.duration:
                r.append(f" ({self.duration:.2f}s)", style=Style(color="#555555"))
        else:
            r.append("  \u2717 ", style=Style(color=CRIMSON))
            r.append(self.name, style=Style(color=CRIMSON))
        return r

class TaskEngine:
    """Manages concurrent tasks with animated progress."""

    def __init__(self):
        self.tasks: list[Task] = []
        self._id_counter = 0

    def add(self, name: str, icon: str = "") -> Task:
        t = Task(name, icon)
        self.tasks.append(t)
        return t

    def start(self, name: str) -> Task:
        """Add and immediately start a task."""
        t = self.add(name)
        t.start()
        return t

    def running_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == Task.RUNNING)

    def done_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == Task.DONE)

    def all_done(self) -> bool:
        return self.running_count() == 0 and self.done_count() > 0

    def render(self) -> Text:
        r = Text()
        for t in self.tasks:
            r.append_text(t.render())
            r.append("\n")
        return r

    def clear_done(self):
        self.tasks = [t for t in self.tasks if t.status == Task.RUNNING]

    def clear(self):
        self.tasks.clear()