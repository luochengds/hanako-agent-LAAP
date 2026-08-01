"""
LAAP — 夜间认知周期调度器 (Nightly Cognitive Cycle)

把巩固、反思、遗忘三个引擎编排为"睡眠期转写"流程，
模拟人类睡眠时的记忆加工：海马体重放 → 皮层整合 → 突触修剪。

周期（默认每天一次）：
    1. 巩固  — 强化重要记忆、归纳情景→语义
    2. 反思  — Truth Grounding 校验事实一致性、Error Reflection 复盘
    3. 遗忘  — 遗忘引擎扫描，降级/归档低激活记忆

每个阶段的结果都写入审计日志——完整可追溯。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.memory.nightly_cycle")


class NightlyCycleScheduler:
    """夜间认知周期调度器。"""

    def __init__(
        self,
        consolidation_fn: Callable[[List[Dict[str, Any]], bool], Any],
        reflection_fn: Optional[Callable[[], Any]] = None,
        forgetting_fn: Optional[Callable[[], Any]] = None,
        self_review_fn: Optional[Callable[[], Any]] = None,
        memory_loader: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        memory_saver: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        log_path: Optional[Path] = None,
        interval_seconds: float = 86400.0,
        enabled_stages: Optional[List[str]] = None,
    ) -> None:
        """
        consolidation_fn(memories, apply) -> report
        reflection_fn() -> report          （可空）
        forgetting_fn() -> audit           （可空）
        self_review_fn() -> report         （可空，夜间自我审视）
        """
        self.consolidation_fn = consolidation_fn
        self.reflection_fn = reflection_fn
        self.forgetting_fn = forgetting_fn
        self.self_review_fn = self_review_fn
        self.memory_loader = memory_loader
        self.memory_saver = memory_saver
        self.log_path = log_path
        self.interval_seconds = interval_seconds
        self.enabled_stages = enabled_stages or ["consolidation", "reflection", "forgetting", "self_review"]
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_cycle: Optional[Dict[str, Any]] = None

    def run_once(self) -> Dict[str, Any]:
        """执行一轮完整夜间周期。"""
        report: Dict[str, Any] = {
            "timestamp": time.time(),
            "stages": {},
        }

        # 1. 巩固（加载记忆 → 强化/归纳 → 保存）
        if "consolidation" in self.enabled_stages and self.consolidation_fn:
            if self.memory_loader:
                memories = self.memory_loader()
                result = self.consolidation_fn(memories, apply=True)
                if self.memory_saver:
                    self.memory_saver(memories)
                report["stages"]["consolidation"] = {
                    "strengthened": getattr(result, "strengthened", None),
                    "induced": getattr(result, "induced", None),
                    "protected": getattr(result, "protected", None),
                }
            else:
                result = self.consolidation_fn([], apply=False)
                report["stages"]["consolidation"] = {"note": "no loader, dry run"}

        # 2. 反思（事实校验 / 错误复盘）
        if "reflection" in self.enabled_stages and self.reflection_fn:
            try:
                ref_result = self.reflection_fn()
                report["stages"]["reflection"] = {"ok": True, "result": str(ref_result)[:200]}
            except Exception as e:
                logger.error("Reflection stage failed: %s", e)
                report["stages"]["reflection"] = {"ok": False, "error": str(e)}

        # 3. 遗忘（降级/归档）
        if "forgetting" in self.enabled_stages and self.forgetting_fn:
            try:
                audit = self.forgetting_fn()
                report["stages"]["forgetting"] = {
                    "scanned": getattr(audit, "scanned", None),
                    "archived": getattr(audit, "archived", None),
                    "dormant": getattr(audit, "demoted_to_dormant", None),
                }
            except Exception as e:
                logger.error("Forgetting stage failed: %s", e)
                report["stages"]["forgetting"] = {"ok": False, "error": str(e)}

        # 4. 自我审视（夜间巡检：清点身体、检查生命体征）
        if "self_review" in self.enabled_stages and self.self_review_fn:
            try:
                review = self.self_review_fn()
                report["stages"]["self_review"] = {
                    "ok": True,
                    "summary": (review or {}).get("summary", {}),
                    "issues": len((review or {}).get("issues", [])),
                }
            except Exception as e:
                logger.error("Self-review stage failed: %s", e)
                report["stages"]["self_review"] = {"ok": False, "error": str(e)}

        self.last_cycle = report
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(report, ensure_ascii=False) + "\n")
            except OSError as e:
                logger.warning("Failed to write cycle log: %s", e)
        logger.info("Nightly cycle done: %s", list(report["stages"].keys()))
        return report

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="laap-nightly")
        self._thread.start()
        logger.info("Nightly cycle scheduler started (interval=%.0fs)", self.interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Nightly cycle scheduler stopped")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as e:
                logger.error("Nightly cycle failed: %s", e)
            self._stop_event.wait(self.interval_seconds)
