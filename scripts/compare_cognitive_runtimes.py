"""Offline A/B comparison for the Bridge and AGIAgent cognitive runtimes.

This harness compares cognitive reports only; it does not call an LLM and does
not mutate the production runtime or memory. Each runtime receives the same
fixture sequence with isolated state.
"""

from __future__ import annotations

import argparse
import json
import shutil
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


def _stable_state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    world = state.get("world_model", {}) or {}
    self_model = state.get("self_model", {}) or {}
    causal = state.get("causal", {}) or {}
    conscious = state.get("conscious", {}) or {}
    memory = state.get("unified_memory", {}) or {}
    bus = state.get("cognitive_bus", {}) or {}
    cognitive_state = dict(bus.get("state", {}) or {})
    cognitive_state.pop("timestamp", None)
    entities = world.get("entities", {}) or {}
    frames = conscious.get("frames", []) or []
    return {
        "total_interactions": state.get("total_interactions"),
        "world_entities": len(entities) if hasattr(entities, "__len__") else entities,
        "self_total_actions": self_model.get("total_actions"),
        "causal_total_learns": causal.get("total_learns"),
        "conscious_frames": len(frames) if hasattr(frames, "__len__") else frames,
        "episodic_memory_count": memory.get("episodic_memory_count"),
        "semantic_memory_count": memory.get("semantic_memory_count"),
        "cognitive_bus_cycles": bus.get("cycles"),
        "cognitive_state": cognitive_state,
    }


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
    memory_probe = "persistence probe unique memory marker"
    encoded_memory = agi.agent.unified_memory.encode_experience(memory_probe)
    concept_probe = "persistence_concept_marker"
    skill_probe = "persistence_skill_marker"
    agi.agent.unified_memory.encode_concept(
        concept_probe, "A concept used to verify semantic memory recovery"
    )
    agi.agent.unified_memory.encode_skill(
        skill_probe, "Persistence verification skill", ["load", "verify"],
        context_triggers=["persistence"],
    )
    agi.agent.save()

    final_state = agi.agent.get_state()
    reloaded = AGIAgent(name="comparison-agi", state_dir=str(agi_state))
    loaded = bool(reloaded.load())
    restored_state = reloaded.get_state() if loaded else {}
    restored_memory = reloaded.unified_memory.query("unique memory marker") if loaded else []
    memory_probe_restored = any(
        item.get("content") == memory_probe for item in restored_memory
    )
    semantic_probe_restored = concept_probe in reloaded.unified_memory.semantic_memory.concepts if loaded else False
    procedural_probe_restored = skill_probe in reloaded.unified_memory.procedural_memory.skills if loaded else False
    second_reload = AGIAgent(name="comparison-agi", state_dir=str(agi_state)) if loaded else None
    second_state = second_reload.get_state() if second_reload else {}
    second_summary = _stable_state_summary(second_state) if second_reload else {}
    compare_keys = ("total_interactions", "world_model", "self_model", "causal", "conscious", "unified_memory", "cognitive_bus")
    state_matches = {
        key: final_state.get(key) == restored_state.get(key)
        for key in compare_keys
        if key in final_state and key in restored_state
    }
    final_summary = _stable_state_summary(final_state)
    restored_summary = _stable_state_summary(restored_state)
    agi_result["persistence"] = {
        "supported": True,
        "loaded": loaded,
        "total_interactions": restored_state.get("total_interactions"),
        "state_matches": state_matches,
        "final_summary": final_summary,
        "restored_summary": restored_summary,
        "stable_summary_matches": final_summary == restored_summary,
        "memory_probe": {
            "episode_id": encoded_memory.get("episode_id"),
            "restored_query_match": memory_probe_restored,
            "semantic_probe_restored": semantic_probe_restored,
            "procedural_probe_restored": procedural_probe_restored,
            "restored_result_count": len(restored_memory),
            "second_reload_summary_matches": second_summary == _stable_state_summary(restored_state),
        },
    }
    edge_root = state_root / "edge_cases"
    edge_root.mkdir(parents=True, exist_ok=True)
    from laap.agi.core import AGIAgent as EdgeAgent
    duplicate_agent = EdgeAgent(name="duplicate-probe", state_dir=str(edge_root / "duplicate"))
    duplicate_text = "duplicate memory idempotence probe"
    duplicate_agent.unified_memory.encode_experience(duplicate_text)
    duplicate_agent.unified_memory.encode_experience(duplicate_text)
    duplicate_agent.save()
    duplicate_reload = EdgeAgent(name="duplicate-probe", state_dir=str(edge_root / "duplicate"))
    duplicate_count = sum(
        item.content == duplicate_text
        for item in duplicate_reload.unified_memory.episodic_memory.episodes
    )

    corrupt_dir = edge_root / "corrupt"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    (corrupt_dir / "agi_state.json").write_text("{not valid json", encoding="utf-8")
    corrupt_agent = EdgeAgent(name="corrupt-probe", state_dir=str(corrupt_dir))
    corrupt_load_result = bool(corrupt_agent.load())

    partial_results = {}
    complete_state = edge_root / "complete"
    complete_agent = EdgeAgent(name="partial-probe", state_dir=str(complete_state))
    complete_agent.unified_memory.encode_experience("partial recovery marker")
    complete_agent.save()
    for missing_name in ("world_model.json", "unified_memory.json", "cognitive_bus/cognitive_bus_state.json"):
        case_dir = edge_root / ("missing_" + missing_name.replace("/", "_"))
        shutil.copytree(complete_state, case_dir, dirs_exist_ok=True)
        (case_dir / missing_name).unlink(missing_ok=True)
        loaded_agent = EdgeAgent(name="partial-probe", state_dir=str(case_dir))
        partial_results[missing_name] = {
            "load_result": bool(loaded_agent.load()),
            "memory_count": loaded_agent.get_state().get("unified_memory", {}).get("episodic_memory_count"),
            "bus_cycles": loaded_agent.get_state().get("cognitive_bus", {}).get("cycles"),
            "world_entities": len(loaded_agent.world.entities),
        }
    agi_result["persistence_edge_cases"] = {
        "duplicate_memory_count_after_reload": duplicate_count,
        "duplicate_write_is_append_semantics": duplicate_count == 2,
        "corrupt_main_state_load_result": corrupt_load_result,
        "corrupt_state_does_not_raise": True,
        "partial_file_results": partial_results,
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
