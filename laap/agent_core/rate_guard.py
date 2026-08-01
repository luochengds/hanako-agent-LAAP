"""RateGuard — 速率保护"""
import time, threading
from typing import Dict, List, Optional

class RateGuard:
    def __init__(self, max_per_minute: int = 30):
        self.max_per_minute = max_per_minute
        self._calls: List[float] = []
        self._lock = threading.RLock()
    def check(self) -> bool:
        now = time.time()
        with self._lock:
            self._calls = [t for t in self._calls if now - t < 60]
            if len(self._calls) >= self.max_per_minute:
                return False
            self._calls.append(now)
            return True
    def wait_time(self) -> float:
        with self._lock:
            if len(self._calls) < self.max_per_minute:
                return 0
            return 60 - (time.time() - self._calls[0])
