"""Cron Scheduler — 定时任务调度器"""
from __future__ import annotations
import time, json, logging, threading, os, weakref
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, List, Optional

logger = logging.getLogger("agent_core.cron")

@dataclass
class CronJob:
    name: str = ""
    interval: int = 3600  # seconds
    handler: Optional[Callable] = None
    last_run: float = 0.0
    enabled: bool = True
    repeat: int = -1  # -1 = forever
    run_count: int = 0

class CronScheduler:
    # 所有活跃实例的弱引用集合，供测试 fixture 在测试结束后统一停止
    _instances: ClassVar["weakref.WeakSet"] = weakref.WeakSet()

    def __init__(self):
        self._jobs: Dict[str, CronJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # 停止信号 Event — 用于唤醒 time.sleep 并立即退出循环
        self._stop_event = threading.Event()
        # 工作线程列表（兼容多线程扩展场景与 stop() 的 join 遍历）
        self._threads: List[threading.Thread] = []
        self._instances.add(self)

    def every(self, name: str, interval: int, handler: Callable, repeat: int = -1):
        self._jobs[name] = CronJob(name=name, interval=interval, handler=handler, repeat=repeat)
        return self

    def minutes(self, name: str, n: int, handler: Callable):
        return self.every(name, n * 60, handler)

    def hours(self, name: str, n: int, handler: Callable):
        return self.every(name, n * 3600, handler)

    def at(self, name: str, cron_expr: str, handler: Callable):
        """Simple cron-like scheduling (minute hour day month weekday)"""
        parts = cron_expr.split()
        if len(parts) >= 2:
            interval = 3600  # default hourly
            if parts[0] == '*':
                interval = 60
            if parts[0] != '*' and parts[1] == '*':
                interval = int(parts[0]) * 60
            self.every(name, interval, handler)
        return self

    def start(self):
        if self._running:
            return
        self._running = True
        # 重置停止信号，支持 stop() 后再次 start() 而不阻塞
        self._stop_event.clear()
        # daemon=True 保证进程退出时不阻塞解释器退出
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._threads = [self._thread]
        self._thread.start()
        logger.info(f"Cron scheduler started with {len(self._jobs)} jobs")

    def stop(self, timeout: float = 5.0) -> bool:
        """停止所有定时任务线程，最多等待 timeout 秒。

        通过 ``_stop_event.set()`` 唤醒 ``_run_loop`` 中 ``wait(10)`` 的阻塞，
        然后 join 所有工作线程。保留 ``timeout`` 默认 5 秒以兼容旧调用方。

        Returns:
            True 表示所有工作线程均已退出；False 表示仍有线程存活。
        """
        self._running = False
        self._stop_event.set()
        # join 所有工作线程
        for t in getattr(self, "_threads", []):
            if t is not None and t.is_alive():
                t.join(timeout=timeout)
        all_stopped = not any(
            t is not None and t.is_alive()
            for t in getattr(self, "_threads", [])
        )
        logger.info("Cron scheduler stopped (all_stopped=%s)", all_stopped)
        return all_stopped

    @classmethod
    def stop_all(cls, timeout: float = 5.0) -> bool:
        """停止所有活跃的 CronScheduler 实例（供测试 fixture 调用）。

        Returns:
            True 表示所有实例的所有工作线程均已退出。
        """
        all_ok = True
        for inst in list(cls._instances):
            try:
                ok = inst.stop(timeout=timeout)
                if not ok:
                    all_ok = False
            except Exception as e:
                logger.warning("stop_all: 实例停止失败: %s", e)
                all_ok = False
        return all_ok

    def _run_loop(self):
        # 用 _stop_event.wait(10) 替代 time.sleep(10)：
        # 保留原 10 秒间隔的语义，但能被 stop() 通过 event.set() 唤醒立即退出
        while not self._stop_event.wait(10):
            if not self._running:
                break
            now = time.time()
            for job in list(self._jobs.values()):
                if not job.enabled:
                    continue
                if job.repeat != -1 and job.run_count >= job.repeat:
                    continue
                if now - job.last_run >= job.interval:
                    self._execute(job)

    def _execute(self, job: CronJob):
        try:
            job.last_run = time.time()
            job.run_count += 1
            if job.handler:
                job.handler()
            logger.info(f"Cron executed: {job.name}")
        except Exception as e:
            logger.error(f"Cron {job.name} failed: {e}")

    def remove(self, name: str):
        self._jobs.pop(name, None)

    def list_jobs(self) -> List[CronJob]:
        return list(self._jobs.values())

    def get_stats(self) -> dict:
        return {"jobs": len(self._jobs), "running": self._running}


# 向后兼容别名（spec 中提及的 CronManager 即此类）
CronManager = CronScheduler
