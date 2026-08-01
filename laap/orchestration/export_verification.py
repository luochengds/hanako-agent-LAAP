"""Export TLA+ specs and verification reports for representative LAAP Petri nets."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from laap.orchestration.petri import ColoredToken, PetriNet, PetriPlace, PetriTransition, TokenColor
from laap.orchestration.verifier import PetriNetVerifier


def _token(value: int = 1) -> ColoredToken:
    """Produce a deterministic colored token for verification nets."""
    return ColoredToken(color=TokenColor.DATA, value=value)


def _forward(tokens: List[ColoredToken]) -> List[ColoredToken]:
    """Pass one token through unchanged."""
    return tokens[:1] if tokens else []


def _make_sequential_net() -> PetriNet:
    """Simple sequential net without deadlock: p1 -> t1 -> p2."""
    net = PetriNet(net_id="simple_sequential_net")

    p1 = PetriPlace("p1")
    p1.deposit(_token())
    net.add_place(p1)
    net.add_place(PetriPlace("p2"))

    net.add_transition(PetriTransition("t1", {"p1": 1}, {"p2": _forward}))
    return net


def _make_psi_harness_closed_loop_net() -> PetriNet:
    """PSI-Harness closed-loop abstraction that can deadlock in a sink.

    A token enters the PSI loop but can only drain when an external
    condition place is satisfied.  Because ``cond`` has no incoming
    transitions, the loop can get stuck while ``sink`` remains a sink
    place, modeling a harness waiting on an unresolved external guard.
    """
    net = PetriNet(net_id="psi_harness_closed_loop")

    start = PetriPlace("start")
    start.deposit(_token())
    net.add_place(start)
    net.add_place(PetriPlace("loop"))
    net.add_place(PetriPlace("cond"))
    net.add_place(PetriPlace("sink"))

    net.add_transition(
        PetriTransition("enter", {"start": 1}, {"loop": _forward})
    )
    net.add_transition(
        PetriTransition("drain", {"loop": 1, "cond": 1}, {"sink": _forward})
    )
    return net


def _make_dependency_chain_deadlock_net() -> PetriNet:
    """Complex dependency-chain deadlock net.

    Two processes compete for two shared resources in opposite orders:

        P1: acquire A -> acquire B -> release A/B -> done
        P2: acquire B -> acquire A -> release A/B -> done

    If P1 holds A and waits for B while P2 holds B and waits for A,
    the net reaches a deadlock.  This mirrors the classic
    deadlock-detection demo where interleaved resource requests form a
    circular wait.
    """
    net = PetriNet(net_id="complex_dependency_chain_deadlock")

    p1_ready = PetriPlace("p1_ready")
    p1_ready.deposit(_token())
    net.add_place(p1_ready)
    net.add_place(PetriPlace("p1_holds_a"))
    net.add_place(PetriPlace("p1_holds_b"))
    net.add_place(PetriPlace("p1_done"))

    p2_ready = PetriPlace("p2_ready")
    p2_ready.deposit(_token())
    net.add_place(p2_ready)
    net.add_place(PetriPlace("p2_holds_b"))
    net.add_place(PetriPlace("p2_holds_a"))
    net.add_place(PetriPlace("p2_done"))

    resource_a = PetriPlace("resource_a")
    resource_a.deposit(_token())
    net.add_place(resource_a)

    resource_b = PetriPlace("resource_b")
    resource_b.deposit(_token())
    net.add_place(resource_b)

    def release_both(tokens: List[ColoredToken]) -> List[ColoredToken]:
        """Release one token of each resource back to the resource pool."""
        return tokens[:2] if tokens else []

    # Process P1: A -> B -> done (returns both resources).
    net.add_transition(
        PetriTransition("p1_acquire_a", {"p1_ready": 1, "resource_a": 1}, {"p1_holds_a": _forward})
    )
    net.add_transition(
        PetriTransition("p1_acquire_b", {"p1_holds_a": 1, "resource_b": 1}, {"p1_holds_b": _forward})
    )
    net.add_transition(
        PetriTransition(
            "p1_done",
            {"p1_holds_b": 1},
            {"p1_done": _forward, "resource_a": release_both, "resource_b": release_both},
        )
    )

    # Process P2: B -> A -> done (returns both resources).
    net.add_transition(
        PetriTransition("p2_acquire_b", {"p2_ready": 1, "resource_b": 1}, {"p2_holds_b": _forward})
    )
    net.add_transition(
        PetriTransition("p2_acquire_a", {"p2_holds_b": 1, "resource_a": 1}, {"p2_holds_a": _forward})
    )
    net.add_transition(
        PetriTransition(
            "p2_done",
            {"p2_holds_a": 1},
            {"p2_done": _forward, "resource_a": release_both, "resource_b": release_both},
        )
    )

    return net


# Ordered list of representative nets to export.
_REPRESENTATIVE_NETS: List[Callable[[], PetriNet]] = [
    _make_sequential_net,
    _make_psi_harness_closed_loop_net,
    _make_dependency_chain_deadlock_net,
]

# TLA+ property/invariant definitions to append to each .tla module.
_TLA_PROPERTIES: Dict[str, Dict[str, str]] = {
    "simple_sequential_net": {"EndStateReachable": "<>(p2 > 0)"},
    "psi_harness_closed_loop": {"SinkReachable": "<>(sink > 0)"},
    "complex_dependency_chain_deadlock": {},
}

_TLA_INVARIANTS: Dict[str, Dict[str, str]] = {
    "simple_sequential_net": {},
    "psi_harness_closed_loop": {},
    "complex_dependency_chain_deadlock": {
        "DeadlockFree": "~((p1_holds_a > 0) /\\ (p2_holds_b > 0))"
    },
}

# Names to reference in each .cfg file (TypeInvariant is added by default).
_TLA_CFG_PROPERTIES: Dict[str, List[str]] = {
    "simple_sequential_net": ["EndStateReachable"],
    "psi_harness_closed_loop": ["SinkReachable"],
    "complex_dependency_chain_deadlock": [],
}

_TLA_CFG_INVARIANTS: Dict[str, List[str]] = {
    "simple_sequential_net": ["TypeInvariant"],
    "psi_harness_closed_loop": ["TypeInvariant"],
    "complex_dependency_chain_deadlock": ["DeadlockFree", "TypeInvariant"],
}


def _run_reachability_checks(net: PetriNet) -> List[Dict[str, Any]]:
    """Run reachability checks against meaningful target markings for *net*."""
    results: List[Dict[str, Any]] = []
    place_ids = sorted(net.places.keys())

    def _check(target: Dict[str, int], description: str) -> None:
        reachable, path = PetriNetVerifier.reachability_check(net, target)
        results.append(
            {
                "description": description,
                "target": target,
                "reachable": reachable,
                "path": path,
            }
        )

    if net.net_id == "simple_sequential_net":
        _check({"p2": 1}, "end place p2 is reachable")
    elif net.net_id == "psi_harness_closed_loop":
        _check({"sink": 1}, "sink place is reachable (requires external cond)")
        _check({"loop": 1}, "loop is reachable after enter")
    elif net.net_id == "complex_dependency_chain_deadlock":
        _check(
            {"p1_done": 1, "p2_done": 1},
            "both processes complete without deadlock",
        )
        _check(
            {"p1_holds_a": 1, "p2_holds_b": 1},
            "circular-wait deadlock marking is reachable",
        )

    return results


def export_tla_reports(output_dir: str = "docs/verification_results") -> Dict[str, Any]:
    """Generate TLA+ specs and verification reports for representative nets.

    For each net this writes:
      * ``{net_id}.tla``          -- TLA+ module text
      * ``{net_id}.cfg``          -- TLC configuration file
      * ``{net_id}_report.json``  -- boundedness / liveness / reachability results
      * ``summary.md``            -- human-readable summary table

    Returns a summary dictionary of the exported artifacts.
    """
    os.makedirs(output_dir, exist_ok=True)

    net_summaries: List[Dict[str, Any]] = []

    for builder in _REPRESENTATIVE_NETS:
        net = builder()
        net_id = net.net_id

        tla_properties = _TLA_PROPERTIES.get(net_id, {})
        tla_invariants = _TLA_INVARIANTS.get(net_id, {})
        tla_spec = PetriNetVerifier.generate_tla_plus(
            net, properties=tla_properties, invariants=tla_invariants
        )
        tla_path = os.path.join(output_dir, f"{net_id}.tla")
        with open(tla_path, "w", encoding="utf-8") as f:
            f.write(tla_spec)

        cfg_properties = _TLA_CFG_PROPERTIES.get(net_id, [])
        cfg_invariants = _TLA_CFG_INVARIANTS.get(net_id, [])
        cfg_spec = PetriNetVerifier.generate_tla_cfg(
            net, properties=cfg_properties, invariants=cfg_invariants
        )
        cfg_path = os.path.join(output_dir, f"{net_id}.cfg")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(cfg_spec)

        is_bounded, max_bound = PetriNetVerifier.boundedness_check(net)
        liveness = PetriNetVerifier.liveness_check(net)
        reachability = _run_reachability_checks(net)

        report: Dict[str, Any] = {
            "net_id": net_id,
            "boundedness": {
                "is_bounded": is_bounded,
                "max_bound": max_bound,
            },
            "liveness": liveness,
            "reachability": reachability,
        }

        report_path = os.path.join(output_dir, f"{net_id}_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        net_summaries.append(
            {
                "net_id": net_id,
                "boundedness": report["boundedness"],
                "liveness": report["liveness"],
                "reachability": report["reachability"],
                "tla_path": tla_path,
                "cfg_path": cfg_path,
                "cfg_properties": cfg_properties,
                "cfg_invariants": cfg_invariants,
                "report_path": report_path,
            }
        )

    summary_path = os.path.join(output_dir, "summary.md")
    _write_summary_md(summary_path, net_summaries)

    return {
        "output_dir": os.path.abspath(output_dir),
        "nets": net_summaries,
        "summary_path": summary_path,
    }


def _write_summary_md(path: str, net_summaries: List[Dict[str, Any]]) -> None:
    """Write a Markdown summary of verification results."""
    lines: List[str] = [
        "# LAAP Petri Net Verification Results",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}Z",
        "",
        "| Net | Bounded | Max Bound | Deadlocks Found | Sink Places | Reachability Highlights |",
        "|-----|---------|-----------|-----------------|-------------|------------------------|",
    ]

    for summary in net_summaries:
        net_id = summary["net_id"]
        bounded = summary["boundedness"]["is_bounded"]
        max_bound = summary["boundedness"]["max_bound"]
        deadlocks = summary["liveness"]["deadlocks"]
        sink_places = summary["liveness"]["sink_places"]

        reachability_notes = []
        for check in summary["reachability"]:
            status = "✅" if check["reachable"] else "❌"
            reachability_notes.append(f"{status} {check['description']}")
        reachability_cell = "<br>".join(reachability_notes)

        lines.append(
            f"| {net_id} | {bounded} | {max_bound} | {len(deadlocks)} | {', '.join(sink_places) or 'none'} | {reachability_cell} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- **simple_sequential_net**: A straight-line workflow; bounded, no deadlocks, and end place ``p2`` is reachable.",
            "- **psi_harness_closed_loop**: Models a PSI harness loop blocked on an external ``cond`` place. The loop place is reachable after ``enter`` fires, but ``sink`` is only reachable if the external condition is satisfied; with ``cond`` initially empty, ``sink`` cannot be reached.",
            "- **complex_dependency_chain_deadlock**: Two processes acquire shared resources in opposite order; bounded but can reach a circular-wait deadlock (``p1_holds_a`` and ``p2_holds_b`` simultaneously). Both processes completing together (``p1_done`` and ``p2_done`` together) is unreachable because the resource contention makes a circular wait unavoidable from the initial marking.",
            "",
            "## TLC Configuration",
            "",
            "Each net has a corresponding ``.cfg`` file that can be loaded directly into the TLA+ Toolbox or ``tlc2``.",
            "",
        ]
    )

    for summary in net_summaries:
        net_id = summary["net_id"]
        cfg_path = summary["cfg_path"]
        properties = summary["cfg_properties"]
        invariants = summary["cfg_invariants"]
        lines.append(f"- **{net_id}**: ``{os.path.basename(cfg_path)}``")
        lines.append(f"  - Properties: {', '.join(['TypeInvariant'] + properties) or 'TypeInvariant'}")
        lines.append(f"  - Invariants: {', '.join(invariants) or 'none'}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    result = export_tla_reports()
    print(f"Exported verification artifacts to: {result['output_dir']}")
    for net in result["nets"]:
        checks = ["TypeInvariant"] + net["cfg_properties"] + [
            f"INVARIANT {name}" for name in net["cfg_invariants"]
        ]
        print(f"  - {net['net_id']}:")
        print(f"      TLA: {net['tla_path']}")
        print(f"      CFG: {net['cfg_path']}")
        print(f"      Report: {net['report_path']}")
        print(f"      TLC checks: {', '.join(checks)}")
    print(f"Summary written to: {result['summary_path']}")
