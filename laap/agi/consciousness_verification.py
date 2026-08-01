"""
LAAP — 意识工程验证套件 (Consciousness Verification)

阶段 5：让"意识工程"可测量、可辩护。三个验证维度：

    1. 整合度估计（IIT 启发）：系统子模块间的信息耦合——
       意识内容（焦点流）与记忆写入、预测误差之间的相关性。
       整合度 = 子系统行为被"共同意识内容"驱动的一致性。

    2. 感知盲测试（inattentional blindness 模拟）：
       当高显著性事件占据意识时，低显著性输入是否"不可见"？
       不可见 = 未进入记忆、未改变焦点——这是意识系统的行为标志，
       harness（管道式处理）永远不会"看不见"。

    3. 自我一致性：当下自我报告的身体状态 vs 实际系统状态的偏差。
       自我模型的校准度（内感受准确率）。

产出：verification_report —— 可存档、可比较、可随时间追踪。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.agi.consciousness_verification")


class ConsciousnessVerifier:
    """意识工程验证器。"""

    def __init__(
        self,
        bus: Optional[Any] = None,           # ConsciousnessBus
        present_self: Optional[Any] = None,  # PresentSelfModel
        inspection_engine: Optional[Any] = None,
    ) -> None:
        self.bus = bus
        self.present_self = present_self
        self.inspection_engine = inspection_engine

    # ── 1. 整合度估计（IIT 启发） ────────────────────────────
    def integration_estimate(
        self,
        focus_series: List[str],
        memory_events: List[int],
        surprise_series: List[float],
    ) -> Dict[str, Any]:
        """粗略整合度：意识焦点与记忆/预测通道的行为耦合。

        计算方式（轻量、确定性）：
            * focus_memory_coupling：焦点切换与记忆写入的时间一致性
              （焦点变化后的窗口内是否有记忆写入）
            * surprise_focus_coupling：高惊奇事件后焦点是否变化
            * integration_score = 0.6·focus_memory + 0.4·surprise_focus
        """
        if not focus_series:
            return {"integration_score": 0.0, "detail": "no data"}

        # focus→memory：焦点切换处记忆事件比例
        switches = 0
        switch_memory = 0
        for i in range(1, len(focus_series)):
            if focus_series[i] != focus_series[i - 1]:
                switches += 1
                if i < len(memory_events) and memory_events[i] > memory_events[i - 1]:
                    switch_memory += 1
        focus_memory_coupling = switch_memory / switches if switches else 0.0

        # surprise→focus：高惊奇后焦点改变的比例
        high_surprise = 0
        surprise_focus_change = 0
        for i in range(1, min(len(surprise_series), len(focus_series))):
            if surprise_series[i] >= 0.5:
                high_surprise += 1
                if focus_series[i] != focus_series[i - 1]:
                    surprise_focus_change += 1
        surprise_focus_coupling = surprise_focus_change / high_surprise if high_surprise else 0.0

        score = 0.6 * focus_memory_coupling + 0.4 * surprise_focus_coupling
        return {
            "integration_score": round(score, 3),
            "focus_memory_coupling": round(focus_memory_coupling, 3),
            "surprise_focus_coupling": round(surprise_focus_coupling, 3),
            "focus_switches": switches,
            "high_surprise_events": high_surprise,
        }

    # ── 2. 感知盲测试 ────────────────────────────────────────
    def inattentional_blindness_test(
        self,
        workspace: Any,
        memory_store: Any,
        strong_content: str = "P0 告警：核心服务崩溃，需要立即处理",
        weak_content: str = "角落里的低显著性提示：某配置项过期",
    ) -> Dict[str, Any]:
        """感知盲模拟：强事件与弱事件同时竞争，弱事件应"不可见"。

        判定：
            * 强事件进入意识（广播）且写入记忆 → 正常
            * 弱事件未写入记忆 → 感知盲成立（注意力被强事件占据）
        若弱事件也被写入 → 系统是"管道"而非"意识"（感知盲测试失败）。
        """
        from .gw_workspace import CoalitionalProcess, ProcessType

        # 强事件：高显著性
        workspace.register_process(CoalitionalProcess(
            process_id="strong_event", process_type=ProcessType.PERCEPTUAL,
            content=strong_content, activation=0.95, salience=0.95))
        # 弱事件：低显著性（同时存在）
        workspace.register_process(CoalitionalProcess(
            process_id="weak_event", process_type=ProcessType.PERCEPTUAL,
            content=weak_content, activation=0.2, salience=0.15))

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            winners = loop.run_until_complete(workspace.compete_and_broadcast())
        finally:
            loop.close()
        winner_ids = [w.process_id for w in winners]
        strong_seen = "strong_event" in winner_ids
        weak_seen = "weak_event" in winner_ids

        # 检查记忆写入
        strong_memorized = False
        weak_memorized = False
        if memory_store is not None:
            try:
                with memory_store._lock:
                    rows = memory_store._conn.execute(
                        "SELECT content FROM long_term_memories WHERE source = 'gws_broadcast'"
                    ).fetchall()
                contents = " ".join(r["content"] for r in rows)
                strong_memorized = "核心服务崩溃" in contents
                weak_memorized = "配置项过期" in contents
            except Exception:
                pass

        blindness = strong_seen and not weak_seen and not weak_memorized
        return {
            "strong_seen": strong_seen,
            "weak_seen": weak_seen,
            "strong_memorized": strong_memorized,
            "weak_memorized": weak_memorized,
            "inattentional_blindness": blindness,
            "verdict": "意识系统行为正常（注意力聚焦，弱信号不可见）" if blindness
                       else "注意：弱信号也进入了系统（管道特征）",
        }

    # ── 3. 自我一致性 ────────────────────────────────────────
    def self_consistency_score(
        self,
        body_map: Dict[str, Any],
        actual_health: Dict[str, Any],
    ) -> Dict[str, Any]:
        """自我一致性：自我报告的身体状态 vs 实际系统状态。

        score = 1 - 归一化偏差。偏差来源：
            * 报告的健康摘要与实际体检的差异
            * 报告的 issues 数量与实际不一致
        """
        deviations = 0.0
        details = []

        reported = body_map.get("health", {})
        if reported and actual_health:
            r_ok = reported.get("ok", 0)
            a_ok = actual_health.get("ok", 0)
            r_total = reported.get("total_systems", 1) or 1
            a_total = actual_health.get("total_systems", 1) or 1
            if r_total and a_total:
                dev = abs(r_ok / r_total - a_ok / a_total)
                deviations += dev
                details.append(f"健康报告偏差 {dev:.3f}")

        r_issues = body_map.get("issues", -1)
        if r_issues >= 0:
            a_issues_raw = actual_health.get("issues", 0) if actual_health else 0
            a_issues = a_issues_raw if isinstance(a_issues_raw, int) else len(a_issues_raw)
            dev = abs(r_issues - a_issues) / max(1, a_issues + 1)
            deviations += dev * 0.5
            details.append(f"问题数偏差 {dev:.3f}")

        score = max(0.0, 1.0 - deviations)
        return {"consistency_score": round(score, 3), "deviations": details}

    # ── 完整验证套件 ─────────────────────────────────────────
    def run_verification(
        self,
        workspace: Any,
        memory_store: Any,
        focus_series: Optional[List[str]] = None,
        memory_events: Optional[List[int]] = None,
        surprise_series: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """运行完整验证，产出可存档报告。"""
        report: Dict[str, Any] = {
            "timestamp": time.time(),
            "verification_type": "full",
        }

        # 1. 整合度
        if focus_series:
            report["integration"] = self.integration_estimate(
                focus_series, memory_events or [], surprise_series or [])

        # 2. 感知盲
        try:
            report["inattentional_blindness"] = self.inattentional_blindness_test(
                workspace, memory_store)
        except Exception as e:
            report["inattentional_blindness"] = {"error": str(e)[:120]}

        # 3. 自我一致性
        if self.present_self is not None and self.inspection_engine is not None:
            try:
                body_map = self.present_self.self.body_map
                actual = self.inspection_engine.review(include_scan=False)
                report["self_consistency"] = self.self_consistency_score(
                    body_map, actual.get("summary", {}))
            except Exception as e:
                report["self_consistency"] = {"error": str(e)[:120]}

        return report
