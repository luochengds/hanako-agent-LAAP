"""LAAP Orchestration — Task Scheduler (M6 E2).

Priority-boosted task scheduler with PSI urgency and deadline proximity
scoring. Supports preemption for higher-priority tasks.

Scheduling score:
    score = priority * 0.5 + psi_urgency * 0.3 + deadline_proximity * 0.2
    deadline_proximity = 1.0 - min(1.0, max(0.0, (deadline - now) / 3600))

A higher score means the task should run sooner. ``priority`` dominates
(50% weight), ``psi_urgency`` contributes emotional/need pressure (30%),
and ``deadline_proximity`` boosts tasks whose deadline is within the
next hour (20%).
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    """A schedulable task.

    Attributes:
        id: Unique task identifier.
        name: Human-readable task name.
        priority: 1-10, 10 = highest.
        deadline: Unix timestamp (seconds since epoch).
        psi_urgency: 0.0-1.0, PSI-theory urgency signal.
        payload: Arbitrary task payload.
    """

    id: str
    name: str
    priority: int  # 1-10, 10 = highest
    deadline: float  # unix timestamp
    psi_urgency: float  # 0-1
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.priority <= 10:
            raise ValueError(f"priority must be 1-10, got {self.priority}")
        if not 0.0 <= self.psi_urgency <= 1.0:
            raise ValueError(f"psi_urgency must be 0-1, got {self.psi_urgency}")


class TaskScheduler:
    """Priority queue scheduler with PSI urgency and deadline proximity.

    The scheduler maintains a max-heap keyed by scheduling score. Scores
    are computed at ``submit()`` time; for long-lived queues call
    ``list_pending()`` to view tasks re-scored against the current time.
    """

    # Score weights (must sum to 1.0)
    W_PRIORITY: float = 0.5
    W_PSI_URGENCY: float = 0.3
    W_DEADLINE: float = 0.2
    # Deadline proximity window (seconds) — 1 hour
    DEADLINE_WINDOW_S: float = 3600.0

    def __init__(self) -> None:
        # Heap of (-score, counter, task) for max-heap behaviour via min-heap.
        self._heap: List[tuple[float, int, Task]] = []
        self._counter: itertools.count = itertools.count()

    def _score(self, task: Task) -> float:
        """Compute the scheduling score for ``task`` at the current time."""
        now = time.time()
        remaining = max(0.0, task.deadline - now)
        deadline_proximity = 1.0 - min(1.0, remaining / self.DEADLINE_WINDOW_S)
        return (
            task.priority * self.W_PRIORITY
            + task.psi_urgency * self.W_PSI_URGENCY
            + deadline_proximity * self.W_DEADLINE
        )

    def submit(self, task: Task) -> str:
        """Submit a task to the queue.

        Returns:
            The task id.
        """
        score = self._score(task)
        heapq.heappush(self._heap, (-score, next(self._counter), task))
        return task.id

    def next(self) -> Optional[Task]:
        """Pop and return the highest-scoring task, or ``None`` if empty."""
        if not self._heap:
            return None
        _, _, task = heapq.heappop(self._heap)
        return task

    def peek(self) -> Optional[Task]:
        """Return the highest-scoring task without removing it."""
        if not self._heap:
            return None
        return self._heap[0][2]

    def preempt(self, new_task: Task) -> Optional[Task]:
        """Attempt to preempt the next-to-run task with ``new_task``.

        If the queue is non-empty and ``new_task`` outscores the current
        top of the queue, the top is removed and returned, and
        ``new_task`` is submitted in its place. Otherwise ``new_task``
        is simply submitted.

        Returns:
            The preempted task if preemption occurred, else ``None``.
        """
        if not self._heap:
            self.submit(new_task)
            return None
        top = self._heap[0][2]
        if self._score(new_task) > self._score(top):
            _, _, popped = heapq.heappop(self._heap)
            self.submit(new_task)
            return popped
        self.submit(new_task)
        return None

    def size(self) -> int:
        """Return the number of pending tasks in the queue."""
        return len(self._heap)

    def list_pending(self) -> List[Task]:
        """Return pending tasks sorted by descending scheduling score.

        Scores are re-computed against the current time so that
        deadline-driven ordering stays accurate.
        """
        scored = [(self._score(t), t) for _, _, t in self._heap]
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored]
