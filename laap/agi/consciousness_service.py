"""
LAAP — 意识工程运行时服务 (Consciousness Runtime Service)

把阶段 1-5 的意识工程模块接成真实可调用的 HTTP 服务，
供 Hanako / aris-engine 插件 / 定时任务调用。

端点：
    POST /consciousness/feed     喂入一个输入事件（对话/构建/告警）
    GET  /consciousness/state    当下自我快照（焦点/身体地图/自指）
    GET  /consciousness/stream   意识流（最近 N 帧整合帧）
    POST /consciousness/nightly  手动触发夜间周期
    GET  /self/review            自我审视报告
    GET  /self/rsi               自我审视 + RSI 建议
    GET  /verify                 意识工程验证套件
    GET  /memory/stats           记忆系统统计
    GET  /health                 服务健康检查

实现：纯标准库（http.server + json），无 FastAPI 依赖，
可独立启动：python -m laap.agi.consciousness_service --port 11522
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.agi.consciousness_service")

# ── 运行时单例：装配全部意识工程模块 ─────────────────────────
_RUNTIME: Dict[str, Any] = {}


def build_runtime(memory_db: Optional[Path] = None) -> Dict[str, Any]:
    """装配完整运行时：总线 + 预测器 + 当下自我 + 时间绑定 + 记忆 + 审视 + 验证。"""
    if _RUNTIME:
        return _RUNTIME

    from laap.agi.consciousness_bus import build_consciousness_bus
    from laap.agi.predictor import SurprisePredictor, InputEvent
    from laap.agi.present_self import attach_present_self
    from laap.agi.temporal_binding import attach_temporal_binding
    from laap.agi.consciousness_verification import ConsciousnessVerifier
    from laap.agi.gw_workspace import GlobalWorkspace
    from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory, attach_nightly_cycle
    from laap.self_inspection import SelfInspectionEngine
    from laap.self_inspection_rsi import RSIFeedbackBridge

    # 记忆库（默认 ~/.laap/long_term.db）
    db = memory_db or (Path.home() / ".laap" / "long_term.db")
    ltm = LifecycleAwareLongTermMemory(db)
    inspector = SelfInspectionEngine(memory_db=db)
    predictor = SurprisePredictor()
    gws = GlobalWorkspace(capacity=4, competition_threshold=0.55)

    # 意识总线（含记忆/内感受/帧订阅 + 预测器）
    bus = build_consciousness_bus(
        memory_store=ltm, inspection_engine=inspector,
        workspace=gws, predictor=predictor,
    )
    # 当下自我 + 时间绑定
    present_self = attach_present_self(
        bus, inspection_engine=inspector, memory_store=ltm, sample_interval=10)
    temporal = attach_temporal_binding(bus, window_seconds=3.0, predictor=predictor)
    # 验证器
    verifier = ConsciousnessVerifier(
        bus=bus, present_self=present_self["model"], inspection_engine=inspector)
    # RSI 桥
    rsi_bridge = RSIFeedbackBridge(inspection_engine=inspector, agent_name="aris")

    _RUNTIME.update({
        "ltm": ltm, "bus": bus, "predictor": predictor, "gws": gws,
        "present_self": present_self, "temporal": temporal,
        "verifier": verifier, "inspector": inspector, "rsi_bridge": rsi_bridge,
        "memory_db": str(db),
    })
    logger.info("Consciousness runtime built: db=%s", db)
    return _RUNTIME


def feed_event(event_type: str, content: str, source: str = "external") -> Dict[str, Any]:
    """喂入一个输入事件：预测器 → 惊奇 → 意识总线 → 记忆。

    这是移植的核心入口：Hanako 的每轮对话/系统事件都走这里。
    """
    rt = build_runtime()
    from laap.agi.predictor import InputEvent
    ev = InputEvent(event_type=event_type, content=content, source=source)
    surprise = rt["bus"].surprise_channel.feed(ev, workspace=rt["gws"])
    # 驱动一轮竞争-广播
    winners = rt["bus"].cycle()
    # 广播给订阅者（记忆/内感受/当下自我/时间绑定）
    frame = rt["temporal"].current()
    return {
        "event_type": event_type,
        "surprise": round(surprise, 3),
        "conscious_focus": [w.process_id for w in winners],
        "integrated_present": frame.to_dict() if frame else None,
        "timestamp": time.time(),
    }


def nightly_cycle() -> Dict[str, Any]:
    """手动触发夜间周期：巩固→反思→遗忘→自我审视→验证。"""
    rt = build_runtime()
    from laap.memory.lifecycle_integration import attach_nightly_cycle
    from laap.self_inspection_rsi import nightly_self_review_with_rsi

    cycle = attach_nightly_cycle(
        rt["ltm"],
        reflection_fn=lambda: {"ok": True},
        self_review_fn=lambda: nightly_self_review_with_rsi(memory_db=Path(rt["memory_db"])),
    )
    report = cycle.run_once()
    # 验证
    verify = rt["verifier"].run_verification(
        rt["gws"], rt["ltm"],
        focus_series=[f["focus"] for f in rt["present_self"]["model"].focus_history[-50:]],
        surprise_series=[h["surprise"] for h in list(rt["predictor"].surprise_history)[-50:]],
    )
    report["verification"] = verify
    return report


# ── HTTP 服务 ─────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _send(self, obj: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        rt = build_runtime()
        try:
            if path == "/health":
                self._send({"status": "ok", "timestamp": time.time()})
            elif path == "/consciousness/state":
                self._send({
                    "present_self": rt["present_self"]["model"].snapshot(),
                    "predictor": rt["predictor"].stats(),
                    "temporal": rt["temporal"].stats(),
                })
            elif path == "/consciousness/stream":
                self._send({"frames": rt["temporal"].stream(n=10)})
            elif path == "/self/review":
                report = rt["inspector"].review_nightly()
                self._send(report)
            elif path == "/self/rsi":
                report = rt["inspector"].review_nightly()
                suggestions = rt["rsi_bridge"].suggest_improvements(report)
                self._send({"review": report["summary"], "rsi": suggestions})
            elif path == "/verify":
                report = rt["verifier"].run_verification(
                    rt["gws"], rt["ltm"],
                    focus_series=[f["focus"] for f in rt["present_self"]["model"].focus_history[-50:]],
                    surprise_series=[h["surprise"] for h in list(rt["predictor"].surprise_history)[-50:]],
                )
                self._send(report)
            elif path == "/memory/stats":
                self._send({
                    "lifecycle": rt["ltm"].get_lifecycle_stats(),
                    "predictor": rt["predictor"].stats(),
                })
            elif path == "/consciousness/nightly":
                self._send(nightly_cycle())
            else:
                self._send({"error": f"unknown path: {path}"}, 404)
        except Exception as e:
            self._send({"error": str(e)}, 500)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        body = self._read_body()
        try:
            if path == "/consciousness/feed":
                result = feed_event(
                    event_type=body.get("event_type", "message"),
                    content=body.get("content", ""),
                    source=body.get("source", "external"),
                )
                self._send(result)
            elif path == "/consciousness/nightly":
                self._send(nightly_cycle())
            else:
                self._send({"error": f"unknown path: {path}"}, 404)
        except Exception as e:
            self._send({"error": str(e)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="LAAP Consciousness Runtime Service")
    parser.add_argument("--port", type=int, default=11522)
    parser.add_argument("--memory-db", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    build_runtime(Path(args.memory_db) if args.memory_db else None)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    logger.info("Consciousness runtime service on http://127.0.0.1:%d", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
