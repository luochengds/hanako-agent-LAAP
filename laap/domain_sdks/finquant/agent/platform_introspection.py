"""LAAP FinQuant Domain SDK — Platform introspection.

The financial agent's "self-awareness" layer. Produces a live, ground-truth
snapshot of everything the SDK currently is: which actors are spawned,
which harness functions are callable, connector health, current portfolio
positions & P&L, safety-policy limits, species templates, recent
CognitiveBus events.

This is *not* an LLM hallucination of platform state — it is read
directly from the live SDK objects the agent is wired to. The agent's
system prompt embeds this snapshot so it can answer "how is the platform
doing right now" with facts, and decide which tool to call next on the
basis of real capability availability.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.domain_sdks.finquant.agent.introspection")


@dataclass
class PlatformSnapshot:
    """A point-in-time snapshot of the FinQuant SDK's live state.

    All fields are JSON-serializable primitives so the snapshot can be
    embedded directly in an LLM system prompt and logged for audit.
    """

    captured_at: float = field(default_factory=time.time)
    domain_id: str = "finquant"
    domain_version: str = "1.0.0"

    # ── Actor system ──
    actors: List[Dict[str, Any]] = field(default_factory=list)
    # ── Harness functions (the zero-token deterministic toolbox) ──
    harness_functions: List[Dict[str, Any]] = field(default_factory=list)
    # ── Species templates (strategy / analysis / risk_model blueprints) ──
    species_templates: List[Dict[str, Any]] = field(default_factory=list)
    # ── Connectors ──
    connectors: List[Dict[str, Any]] = field(default_factory=list)
    active_connector: Optional[str] = None
    # ── Portfolio (live, from connector) ──
    portfolio: Optional[Dict[str, Any]] = None
    positions: List[Dict[str, Any]] = field(default_factory=list)
    # ── Safety policy ──
    safety_policy: Dict[str, Any] = field(default_factory=dict)
    # ── Recent bus events (last N, ring buffer) ──
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    # ── CognitiveBus topics registered ──
    topics: List[str] = field(default_factory=list)
    # ── Agent's own cumulative stats ──
    agent_stats: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Render the snapshot as a compact, LLM-readable text block."""
        lines: List[str] = []
        lines.append(f"# FinQuant Platform Live State @ t={self.captured_at:.1f}")
        lines.append(f"domain={self.domain_id} v{self.domain_version}")

        # Actors
        lines.append(f"\n## Cognitive Actors ({len(self.actors)} spawned)")
        for a in self.actors:
            cap = a.get("capabilities", [])
            cap_names = [c.get("name", "?") if isinstance(c, dict) else str(c) for c in cap]
            lines.append(
                f"- {a.get('actor_id','?')}: caps=[{', '.join(cap_names)}] "
                f"subscribed={a.get('subscribes', [])}"
            )

        # Harness
        lines.append(f"\n## Harness Functions ({len(self.harness_functions)} zero-token)")
        for h in self.harness_functions:
            lines.append(
                f"- {h.get('name','?')}: {h.get('description','')[:80]}"
            )

        # Species
        lines.append(f"\n## Species Templates ({len(self.species_templates)})")
        for s in self.species_templates:
            lines.append(
                f"- {s.get('id','?')} [{s.get('category','?')}]: {s.get('description','')[:60]}"
            )

        # Connectors
        lines.append(f"\n## Connectors (active={self.active_connector})")
        for c in self.connectors:
            lines.append(
                f"- {c.get('connector_id','?')}: health={c.get('health','?')} "
                f"caps={c.get('capabilities', [])} tier={c.get('tier','?')}"
            )

        # Portfolio
        if self.portfolio:
            lines.append("\n## Portfolio")
            lines.append(
                f"- cash={self.portfolio.get('cash','?')} "
                f"equity={self.portfolio.get('equity','?')} "
                f"PnL={self.portfolio.get('pnl','?')}"
            )
        if self.positions:
            lines.append(f"\n## Open Positions ({len(self.positions)})")
            for p in self.positions[:20]:
                lines.append(
                    f"- {p.get('symbol','?')}: size={p.get('size','?')} "
                    f"avg={p.get('avg_price','?')} pnl={p.get('unrealized_pnl','?')}"
                )

        # Safety
        if self.safety_policy:
            lines.append("\n## Safety Policy Limits")
            for k, v in self.safety_policy.items():
                lines.append(f"- {k}: {v}")

        # Recent events
        if self.recent_events:
            lines.append(f"\n## Recent Bus Events (last {len(self.recent_events)})")
            for e in self.recent_events[-10:]:
                lines.append(
                    f"- [{e.get('topic','?')}] {e.get('summary','')[:80]}"
                )

        # Agent stats
        if self.agent_stats:
            lines.append("\n## Agent Stats")
            for k, v in self.agent_stats.items():
                lines.append(f"- {k}: {v}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        import dataclasses

        return dataclasses.asdict(self)


class PlatformIntrospector:
    """Builds :class:`PlatformSnapshot` from live SDK references.

    Holds weak references to the SDK's runtime objects (harness registry,
    actor system, connector, safety policy, species library) and reads
    them on each :meth:`snapshot` call. Never mutates state — pure read.
    """

    def __init__(
        self,
        harness_registry: Any = None,
        actor_system: Any = None,
        connector: Any = None,
        safety_policy: Any = None,
        species_library: Any = None,
        cognitive_bus: Any = None,
        connector_registry: Any = None,
    ) -> None:
        self.harness_registry = harness_registry
        self.actor_system = actor_system
        self.connector = connector
        self.safety_policy = safety_policy
        self.species_library = species_library
        self.cognitive_bus = cognitive_bus
        self.connector_registry = connector_registry
        # Ring buffer of recent bus events captured via subscription.
        self._recent_events: List[Dict[str, Any]] = []
        self._max_events = 50
        self._subscribed = False

    # ── Public ────────────────────────────────────────────────────

    def snapshot(self, agent_stats: Optional[Dict[str, Any]] = None) -> PlatformSnapshot:
        """Capture a live snapshot. Safe to call on every agent turn."""
        snap = PlatformSnapshot(agent_stats=agent_stats or {})
        try:
            snap.actors = self._read_actors()
        except Exception as exc:
            logger.debug("read actors failed: %s", exc)
        try:
            snap.harness_functions = self._read_harness()
        except Exception as exc:
            logger.debug("read harness failed: %s", exc)
        try:
            snap.species_templates = self._read_species()
        except Exception as exc:
            logger.debug("read species failed: %s", exc)
        try:
            snap.connectors, snap.active_connector = self._read_connectors()
        except Exception as exc:
            logger.debug("read connectors failed: %s", exc)
        try:
            snap.portfolio, snap.positions = self._read_portfolio()
        except Exception as exc:
            logger.debug("read portfolio failed: %s", exc)
        try:
            snap.safety_policy = self._read_safety()
        except Exception as exc:
            logger.debug("read safety failed: %s", exc)
        try:
            snap.topics = self._read_topics()
        except Exception as exc:
            logger.debug("read topics failed: %s", exc)
        snap.recent_events = list(self._recent_events)
        return snap

    def record_event(self, topic: str, summary: str, payload: Any = None) -> None:
        """Record a bus event into the ring buffer (called by bus subscriber)."""
        self._recent_events.append(
            {
                "topic": topic,
                "summary": str(summary)[:200],
                "ts": time.time(),
                "payload_preview": str(payload)[:120] if payload is not None else "",
            }
        )
        if len(self._recent_events) > self._max_events:
            del self._recent_events[: len(self._recent_events) - self._max_events]

    async def attach_to_bus(self) -> None:
        """Best-effort subscribe to all finquant.* topics on the cognitive bus."""
        if self._subscribed or self.cognitive_bus is None:
            return
        try:
            from laap.domain_sdks.finquant.topics import ALL_TOPICS

            for topic in ALL_TOPICS:
                try:
                    sub = getattr(self.cognitive_bus, "subscribe", None)
                    if sub is not None:
                        await sub(topic, self._bus_handler)
                except Exception:
                    pass
            self._subscribed = True
        except Exception as exc:
            logger.debug("attach_to_bus failed: %s", exc)

    # ── Readers (each defensive — returns [] / {} on failure) ─────

    async def _bus_handler(self, topic: str, message: Any) -> None:
        try:
            payload = getattr(message, "payload", message)
            summary = ""
            if isinstance(payload, dict):
                summary = payload.get("summary") or payload.get("topic", "") or str(payload)[:80]
            self.record_event(topic, summary, payload)
        except Exception:
            pass

    def _read_actors(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.actor_system is None:
            return out
        actors_map = getattr(self.actor_system, "actors", None)
        if isinstance(actors_map, dict):
            for aid, cell in actors_map.items():
                out.append(self._describe_actor(aid, cell))
        cells = getattr(self.actor_system, "cells", None)
        if isinstance(cells, dict) and not out:
            for aid, cell in cells.items():
                out.append(self._describe_actor(aid, cell))
        return out

    @staticmethod
    def _describe_actor(aid: str, cell: Any) -> Dict[str, Any]:
        caps = getattr(cell, "capabilities", []) or []
        return {
            "actor_id": aid,
            "capabilities": [
                {"name": getattr(c, "name", str(c)), "confidence": getattr(c, "confidence", None)}
                for c in caps
            ],
            "address": getattr(cell, "address", None),
            "subscribes": getattr(cell, "subscribed_topics", []) or [],
        }

    def _read_harness(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.harness_registry is None:
            return out
        list_names = getattr(self.harness_registry, "list_names", None)
        if callable(list_names):
            try:
                names = list_names(domain="finquant") or list_names() or []
            except TypeError:
                names = list_names() or []
            for name in names:
                out.append(
                    {
                        "name": name,
                        "description": self._harness_desc(name),
                    }
                )
        return out

    def _harness_desc(self, name: str) -> str:
        try:
            get = getattr(self.harness_registry, "get", None)
            if callable(get):
                fn = get(name)
                if fn is not None:
                    return (getattr(fn, "description", "") or getattr(fn, "__doc__", "") or "")[:120]
        except Exception:
            pass
        return ""

    def _read_species(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.species_library is None:
            return out
        try:
            from laap.domain_sdks.finquant.species import ALL_SPECIES_TEMPLATES

            for t in ALL_SPECIES_TEMPLATES:
                out.append(
                    {
                        "id": getattr(t, "id", "") or t.get("id", ""),
                        "category": getattr(t, "category", "") or t.get("category", ""),
                        "description": (getattr(t, "description", "") or t.get("description", ""))[:120],
                    }
                )
        except Exception:
            # Fallback: try library.list()
            lst = getattr(self.species_library, "list", None)
            if callable(lst):
                try:
                    for t in lst():
                        out.append(
                            {
                                "id": getattr(t, "id", ""),
                                "category": getattr(t, "category", ""),
                                "description": (getattr(t, "description", "") or "")[:120],
                            }
                        )
                except Exception:
                    pass
        return out

    def _read_connectors(self) -> tuple:
        out: List[Dict[str, Any]] = []
        active = None
        # Active connector first
        if self.connector is not None:
            active = getattr(self.connector, "connector_id", "active")
            out.append(self._describe_connector(self.connector))
        # Registry
        if self.connector_registry is not None:
            try:
                reg = getattr(self.connector_registry, "_registry", {})
                for cid, conn in reg.items():
                    if any(c.get("connector_id") == cid for c in out):
                        continue
                    out.append(self._describe_connector(conn))
            except Exception:
                pass
        return out, active

    @staticmethod
    def _describe_connector(conn: Any) -> Dict[str, Any]:
        caps = getattr(conn, "capabilities", set()) or set()
        try:
            caps_list = [c.name if hasattr(c, "name") else str(c) for c in caps]
        except Exception:
            caps_list = []
        tier = getattr(conn, "tier", None)
        return {
            "connector_id": getattr(conn, "connector_id", "unknown"),
            "health": getattr(conn, "_health", "unknown"),
            "capabilities": caps_list,
            "tier": tier.name if hasattr(tier, "name") else str(tier),
        }

    def _read_portfolio(self) -> tuple:
        if self.connector is None:
            return None, []
        # Defensive: portfolio query may need async; we try sync first,
        # callers that want live data should pre-fetch via the connector.
        portfolio = None
        positions: List[Dict[str, Any]] = []
        try:
            get_portfolio = getattr(self.connector, "get_portfolio", None)
            if callable(get_portfolio):
                import inspect

                if inspect.iscoroutinefunction(get_portfolio):
                    # Can't await here (snapshot is sync); leave for async path.
                    portfolio = None
                else:
                    portfolio = get_portfolio()
        except Exception:
            portfolio = None
        try:
            get_positions = getattr(self.connector, "get_positions", None)
            if callable(get_positions):
                import inspect

                if not inspect.iscoroutinefunction(get_positions):
                    raw = get_positions() or []
                    for p in raw:
                        positions.append(
                            {
                                "symbol": getattr(p, "symbol", ""),
                                "size": getattr(p, "size", 0.0),
                                "avg_price": getattr(p, "avg_price", None),
                                "unrealized_pnl": getattr(p, "unrealized_pnl", None),
                            }
                        )
        except Exception:
            pass
        if portfolio is not None and not isinstance(portfolio, dict):
            portfolio = {
                "cash": getattr(portfolio, "cash", None),
                "equity": getattr(portfolio, "equity", None),
                "pnl": getattr(portfolio, "pnl", None),
            }
        return portfolio, positions

    async def read_portfolio_async(self) -> tuple:
        """Async portfolio reader — use when the connector needs await."""
        if self.connector is None:
            return None, []
        portfolio = None
        positions: List[Dict[str, Any]] = []
        try:
            get_portfolio = getattr(self.connector, "get_portfolio", None)
            if callable(get_portfolio):
                import inspect

                if inspect.iscoroutinefunction(get_portfolio):
                    portfolio = await get_portfolio()
                else:
                    portfolio = get_portfolio()
        except Exception as exc:
            logger.debug("async portfolio read failed: %s", exc)
        try:
            get_positions = getattr(self.connector, "get_positions", None)
            if callable(get_positions):
                import inspect

                if inspect.iscoroutinefunction(get_positions):
                    raw = await get_positions() or []
                else:
                    raw = get_positions() or []
                for p in raw:
                    positions.append(
                        {
                            "symbol": getattr(p, "symbol", ""),
                            "size": getattr(p, "size", 0.0),
                            "avg_price": getattr(p, "avg_price", None),
                            "unrealized_pnl": getattr(p, "unrealized_pnl", None),
                        }
                    )
        except Exception as exc:
            logger.debug("async positions read failed: %s", exc)
        if portfolio is not None and not isinstance(portfolio, dict):
            portfolio = {
                "cash": getattr(portfolio, "cash", None),
                "equity": getattr(portfolio, "equity", None),
                "pnl": getattr(portfolio, "pnl", None),
            }
        return portfolio, positions

    def _read_safety(self) -> Dict[str, Any]:
        if self.safety_policy is None:
            return {}
        out: Dict[str, Any] = {}
        for attr in (
            "max_position_pct",
            "max_drawdown_pct",
            "max_leverage",
            "max_order_value",
            "rate_limit_per_minute",
            "require_paper_first",
            "restricted_symbols",
            "allowed_markets",
        ):
            val = getattr(self.safety_policy, attr, None)
            if val is not None:
                out[attr] = val
        # If the policy exposes a to_dict / describe, prefer that.
        for m in ("to_dict", "describe", "as_dict"):
            fn = getattr(self.safety_policy, m, None)
            if callable(fn):
                try:
                    d = fn()
                    if isinstance(d, dict):
                        out.update(d)
                        break
                except Exception:
                    pass
        return out

    def _read_topics(self) -> List[str]:
        try:
            from laap.domain_sdks.finquant.topics import ALL_TOPICS

            return list(ALL_TOPICS)
        except Exception:
            return []


__all__ = ["PlatformIntrospector", "PlatformSnapshot"]
