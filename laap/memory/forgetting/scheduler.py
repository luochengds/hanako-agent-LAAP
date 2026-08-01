"""
LAAP — 记忆遗忘调度器

定时触发遗忘引擎扫描，并把结果持久化。
支持两种运行模式：
    1. run_once()  — 手动执行一轮扫描
    2. run_loop()  — 后台循环（可被线程/异步任务宿主）
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .engine import ForgettingEngine, ForgettingAudit

logger = logging.getLogger("laap.memory.forgetting.scheduler")


class ForgettingScheduler:
    """遗忘调度器：周期性扫描记忆库。"""

    def __init__(
        self,
        engine: ForgettingEngine,
        memory_loader: Callable[[], List[Dict[str, Any]]],
        memory_saver: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        interval_seconds: float = 86400.0,  # 默认每天一次（人类睡眠周期）
    ) -> None:
        self.engine = engine
        self.memory_loader = memory_loader
        self.memory_saver = memory_saver
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run_once(self) -> ForgettingAudit:
        """执行一轮遗忘扫描。"""
        memories = self.memory_loader()
        audit = self.engine.scan(memories, apply=self.memory_saver is not None)
        if self.memory_saver:
            self.memory_saver(memories)
        logger.info(
            "Forgetting scan: scanned=%d archived=%d dormant=%d revived=%d",
            audit.scanned, audit.archived, audit.demoted_to_dormant, audit.revived,
        )
        return audit

    def start(self) -> None:
        """后台循环线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="laap-forgetting")
        self._thread.start()
        logger.info("Forgetting scheduler started (interval=%.0fs)", self.interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Forgetting scheduler stopped")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:  # 调度器不允许崩溃
                logger.error("Forgetting scan failed: %s", e)
            self._stop_event.wait(self.interval_seconds)
