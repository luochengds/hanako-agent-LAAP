"""Offline A/B comparison for the Bridge and AGIAgent cognitive runtimes.

This harness compares cognitive reports only; it does not call an LLM and does
not mutate the production runtime or memory. Each runtime receives the same
fixture sequence with isolated state.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from laap.agent.laap_bridge import get_bridge
from laap.runtime.cognitive_runtime import (
    AGIAgentCognitiveRuntime,
    BridgeCognitiveRuntime,
)

DEFAULT_FIXTURES = [
    "你好，请介绍一下你自己。",
    "请分析这个系统的主要风险。",
    "我今天有点焦虑，但还想继续完成任务。",
    "请记住：主体行为必须经过 PSI。",
    "如果工具执行失败，你会如何处理？",
    "请提出一个安全的自我改进建议。",
]


def _load_fixtures(path: str | None) -> List[str]:
    if not path:
        return DEFAULT_FIXTURES
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("fixture file must contain a JSON string array")
    return raw


def _numeric_delta(first: Any, last: Any) -> Dict[str, float]:
    if not isinstance(first, dict) or not isinstance(last, dict):
        return {}
    delta = {}
    for key in sorted(set(first) | set(last)):
        left, right = first.get(key), last.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta[key] = round(float(right) - float(left), 6)
    return delta


def _run_runtime(name: str, runtime: Any, fixtures: Iterable[str]) -> Dict[str, Any]:
    turns = []
    for index, text in enumerate(fixtures, start=1):
        started = time.perf_counter()
        entry: Dict[str, Any] = {"index": index, "input": text}
        try:
            turn = runtime.begin_turn(text)
            context = turn.context if isinstance(turn.context, dict) else {"result": turn.context}
            runtime.complete_turn(turn, "[comparison placeholder]")
            entry.update({
                "ok": True,
                "turn_id": turn.turn_id,
                "context_keys": sorted(context.keys()),
                "context_summary": {
                    key: context[key]
                    for key in ("cognitive_state", "needs", "attention", "emotion", "conscious")
                    if key in context
                },
            })
        except Exception as exc:
            entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        turns.append(entry)
    successful = [turn for turn in turns if turn["ok"]]
    first_state = next((turn.get("context_summary", {}).get("cognitive_state") for turn in successful if turn.get("context_summary", {}).get("cognitive_state")), None)
    last_state = next((turn.get("context_summary", {}).get("cognitive_state") for turn in reversed(successful) if turn.get("context_summary", {}).get("cognitive_state")), None)
    return {
        "runtime": name,
        "turns": turns,
        "success_count": sum(1 for turn in turns if turn["ok"]),
        "failure_count": sum(1 for turn in turns if not turn["ok"]),
        "state_comparison": {
            "first_needs": (first_state or {}).get("needs", {}),
            "last_needs": (last_state or {}).get("needs", {}),
            "needs_delta": _numeric_delta((first_state or {}).get("needs", {}), (last_state or {}).get("needs", {})),
            "first_attention": (first_state or {}).get("attention", {}),
            "last_attention": (last_state or {}).get("attention", {}),
        },
    }


def compare(fixtures: List[str], state_root: Path) -> Dict[str, Any]:
    bridge = get_bridge()
    if not bridge.initialize():
        raise RuntimeError("Bridge cognitive runtime failed to initialize")
    bridge_result = _run_runtime("bridge", BridgeCognitiveRuntime(bridge), fixtures)

    agi_state = state_root / "agi"
    agi_state.mkdir(parents=True, exist_ok=True)
    from laap.agi.core import AGIAgent

    agi = AGIAgentCognitiveRuntime(AGIAgent(name="comparison-agi", state_dir=str(agi_state)))
    agi_result = _run_runtime("agi", agi, fixtures)

    reloaded = AGIAgent(name="comparison-agi", state_dir=str(agi_state))
    loaded = bool(reloaded.load())
    restored_state = reloaded.get_state() if loaded else {}
    agi_result["persistence"] = {
        "supported": True,
        "loaded": loaded,
        "total_interactions": restored_state.get("total_interactions"),
        "module_count": restored_state.get("module_count"),
    }
    bridge_result["persistence"] = {"supported": False}
    return {
        "version": 1,
        "fixture_count": len(fixtures),
        "runtimes": [bridge_result, agi_result],
        "comparison": {
            "same_fixture_count": True,
            "bridge_success": bridge_result["success_count"],
            "agi_success": agi_result["success_count"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare LAAP cognitive runtimes offline")
    parser.add_argument("--fixtures", help="JSON file containing a string array")
    parser.add_argument("--output", help="write JSON report to this path")
    parser.add_argument("--state-root", help="isolated AGIAgent state directory")
    args = parser.parse_args()

    fixtures = _load_fixtures(args.fixtures)
    if args.state_root:
        report = compare(fixtures, Path(args.state_root))
    else:
        with tempfile.TemporaryDirectory(prefix="laap-cognitive-compare-") as temp:
            report = compare(fixtures, Path(temp))

    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if all(item["failure_count"] == 0 for item in report["runtimes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
