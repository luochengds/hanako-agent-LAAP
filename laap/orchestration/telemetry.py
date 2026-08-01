"""LAAP Aether — Observability telemetry collector for orchestration."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from laap.orchestration.aaosa import AAOSACoordinator
from laap.orchestration.actor import ActorSystem, AgentCell
from laap.orchestration.petri import PetriNet
from laap.orchestration.primitives import AetherMessage


@dataclass
class TelemetrySpan:
    """A single observability span recording an operation."""

    span_id: str
    parent_id: str | None
    name: str
    start_time: float
    end_time: float | None
    attributes: dict[str, Any]

    @property
    def duration_ms(self) -> float | None:
        """Return span duration in milliseconds, or None if still active."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000.0


class TelemetryCollector:
    """Collect telemetry spans, metrics and events for orchestration."""

    def __init__(self) -> None:
        self._spans: dict[str, TelemetrySpan] = {}
        self._active: set[str] = set()
        self._finished: list[TelemetrySpan] = []
        self._counters: dict[tuple[str, frozenset[tuple[str, str]]], float] = {}
        self._histograms: dict[tuple[str, frozenset[tuple[str, str]]], list[float]] = {}
        self._events: list[dict[str, Any]] = []

    def start_span(
        self,
        name: str,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TelemetrySpan:
        """Start a new span and return it immediately (non-blocking)."""
        span_id = str(uuid.uuid4())
        span = TelemetrySpan(
            span_id=span_id,
            parent_id=parent_id,
            name=name,
            start_time=time.monotonic(),
            end_time=None,
            attributes=dict(attributes or {}),
        )
        self._spans[span_id] = span
        self._active.add(span_id)
        return span

    def end_span(self, span_id: str) -> TelemetrySpan | None:
        """End an active span and move it to finished spans."""
        span = self._spans.get(span_id)
        if span is None or span.end_time is not None:
            return span
        span.end_time = time.monotonic()
        self._active.discard(span_id)
        self._finished.append(span)
        return span

    def record_metric(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a metric sample. Counters are summed; durations are histogrammed."""
        labels = labels or {}
        key = (name, frozenset(labels.items()))
        if self._is_histogram(name):
            self._histograms.setdefault(key, []).append(float(value))
        else:
            self._counters[key] = self._counters.get(key, 0.0) + float(value)

    def record_event(
        self,
        name: str,
        attributes: dict[str, Any],
    ) -> None:
        """Record a discrete event with attributes (non-blocking)."""
        self._events.append(
            {
                "name": name,
                "timestamp": time.monotonic(),
                "attributes": dict(attributes),
            }
        )

    def active_spans(self) -> list[TelemetrySpan]:
        """Return currently active spans."""
        return [self._spans[sid] for sid in self._active]

    def finished_spans(self) -> list[TelemetrySpan]:
        """Return completed spans in completion order."""
        return list(self._finished)

    def get_metric(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> float | dict[str, Any] | None:
        """Return a counter value or histogram summary for the given metric labels."""
        labels = labels or {}
        key = (name, frozenset(labels.items()))
        if key in self._counters:
            return self._counters[key]
        if key in self._histograms:
            values = self._histograms[key]
            return {"count": len(values), "sum": sum(values)}
        return None

    @staticmethod
    def _is_histogram(name: str) -> bool:
        """Infer histogram semantics from metric name."""
        return (
            name.endswith("_duration_ms")
            or name.endswith("_latency_ms")
            or "_duration_" in name
            or "_latency_" in name
        )

    def prometheus_export(self) -> str:
        """Export collected metrics in Prometheus text exposition format."""
        lines: list[str] = []

        # Counters
        counter_groups: dict[str, list[tuple[dict[str, str], float]]] = defaultdict(list)
        for (name, label_frozenset), value in self._counters.items():
            counter_groups[name].append((dict(label_frozenset), value))

        for name in sorted(counter_groups):
            lines.append(f"# HELP {name} {name}")
            lines.append(f"# TYPE {name} counter")
            for labels, value in sorted(
                counter_groups[name], key=lambda item: tuple(sorted(item[0].items()))
            ):
                label_str = _format_labels(labels)
                lines.append(f"{name}{label_str} {value}")
            lines.append("")

        # Histograms
        hist_groups: dict[str, list[tuple[dict[str, str], list[float]]]] = defaultdict(list)
        for (name, label_frozenset), values in self._histograms.items():
            hist_groups[name].append((dict(label_frozenset), values))

        for name in sorted(hist_groups):
            lines.append(f"# HELP {name} {name}")
            lines.append(f"# TYPE {name} histogram")
            for labels, values in sorted(
                hist_groups[name], key=lambda item: tuple(sorted(item[0].items()))
            ):
                count = len(values)
                total = sum(values)
                label_str = _format_labels(labels)
                bucket_labels = {**labels, "le": "+Inf"}
                bucket_str = _format_labels(bucket_labels)
                lines.append(f"{name}_count{label_str} {count}")
                lines.append(f"{name}_sum{label_str} {total}")
                lines.append(f"{name}_bucket{bucket_str} {count}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def _format_labels(labels: dict[str, str]) -> str:
    """Format labels as a Prometheus label set string."""
    if not labels:
        return ""
    pairs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(pairs) + "}"


def _message_labels(message: AetherMessage, actor_id: str | None = None) -> dict[str, str]:
    """Build label dict from an AetherMessage."""
    labels: dict[str, str] = {}
    if message.msg_type is not None:
        labels["msg_type"] = str(message.msg_type.value)
    if actor_id is not None:
        labels["actor_id"] = actor_id
    elif message.recipient is not None:
        labels["actor_id"] = message.recipient.actor_id
    return labels


class OrchestrationTelemetry:
    """Wrap ActorSystem, PetriNet and AAOSACoordinator with telemetry instrumentation."""

    def __init__(
        self,
        actor_system: ActorSystem,
        petri_net: PetriNet,
        aaosa_coordinator: AAOSACoordinator | None = None,
        collector: TelemetryCollector | None = None,
    ):
        self.actor_system = actor_system
        self.petri_net = petri_net
        self.aaosa_coordinator = aaosa_coordinator
        self.collector = collector or TelemetryCollector()

        # Stash originals so instrumentation is reversible and idempotent.
        self._original_send = actor_system.send
        self._original_broadcast = actor_system.broadcast
        self._original_fire_transition = petri_net.fire_transition
        self._original_process_message = AgentCell._process_message
        if aaosa_coordinator is not None:
            self._original_aaosa_broadcast = aaosa_coordinator.broadcast_task
            self._original_aaosa_resolve = aaosa_coordinator.resolve_claims

        self._instrument()

    def _instrument(self) -> None:
        self._instrument_actor_system()
        self._instrument_petri_net()
        if self.aaosa_coordinator is not None:
            self._instrument_aaosa()

    def _instrument_actor_system(self) -> None:
        collector = self.collector
        original_send = self._original_send
        original_broadcast = self._original_broadcast

        async def _instrumented_send(message: AetherMessage) -> None:
            labels = _message_labels(message)
            collector.record_metric("laap_actor_messages_sent_total", 1, labels)
            span = collector.start_span("laap_actor_send_latency_ms")
            start = time.monotonic()
            try:
                await original_send(message)
            finally:
                collector.end_span(span.span_id)
                collector.record_metric(
                    "laap_actor_send_latency_ms",
                    (time.monotonic() - start) * 1000.0,
                    labels,
                )

        async def _instrumented_broadcast(
            message: AetherMessage,
            capability_filter: str | None = None,
        ) -> None:
            span = collector.start_span("laap_actor_broadcast_latency_ms")
            start = time.monotonic()
            try:
                await original_broadcast(message, capability_filter=capability_filter)
            finally:
                collector.end_span(span.span_id)
                collector.record_metric(
                    "laap_actor_broadcast_latency_ms",
                    (time.monotonic() - start) * 1000.0,
                )
                targets = list(self.actor_system.actors.values())
                if capability_filter is not None:
                    capable = self.actor_system.capability_registry.get(capability_filter, set())
                    targets = [a for a in targets if a.address in capable]
                for actor in targets:
                    collector.record_metric(
                        "laap_actor_messages_sent_total",
                        1,
                        {"msg_type": str(message.msg_type.value), "actor_id": actor.actor_id},
                    )

        self.actor_system.send = _instrumented_send
        self.actor_system.broadcast = _instrumented_broadcast

        original_process_message = self._original_process_message

        async def _instrumented_process_message(self_actor: AgentCell, message: AetherMessage) -> None:
            labels = _message_labels(message, actor_id=self_actor.actor_id)
            collector.record_metric("laap_actor_messages_received_total", 1, labels)
            span = collector.start_span("laap_actor_receive_latency_ms")
            start = time.monotonic()
            try:
                await original_process_message(self_actor, message)
            finally:
                collector.end_span(span.span_id)
                collector.record_metric(
                    "laap_actor_receive_latency_ms",
                    (time.monotonic() - start) * 1000.0,
                    labels,
                )

        AgentCell._process_message = _instrumented_process_message

    def _instrument_petri_net(self) -> None:
        collector = self.collector
        original_fire_transition = self._original_fire_transition
        net_id = self.petri_net.net_id

        async def _instrumented_fire_transition(transition_id: str) -> bool:
            span = collector.start_span("laap_transition_fire_duration_ms")
            start = time.monotonic()
            try:
                result = await original_fire_transition(transition_id)
                return result
            finally:
                collector.end_span(span.span_id)
                labels = {"net_id": net_id, "transition_id": transition_id}
                collector.record_metric(
                    "laap_transition_fire_duration_ms",
                    (time.monotonic() - start) * 1000.0,
                    labels,
                )

        self.petri_net.fire_transition = _instrumented_fire_transition

        def _listener(event: str, payload: dict[str, Any]) -> None:
            if event == "transition_fired":
                entry = payload.get("entry", {})
                transition_id = entry.get("transition_id", "")
                labels = {"net_id": net_id, "transition_id": transition_id}
                collector.record_metric("laap_transition_fires_total", 1, labels)

        self.petri_net.add_listener(_listener)

    def _instrument_aaosa(self) -> None:
        collector = self.collector
        coordinator = self.aaosa_coordinator
        original_broadcast = self._original_aaosa_broadcast
        original_resolve = self._original_aaosa_resolve

        async def _instrumented_broadcast(task_item: Any) -> None:
            collector.record_metric(
                "laap_aaosa_broadcasts_total",
                1,
                {"task_id": task_item.task_id},
            )
            await original_broadcast(task_item)

        async def _instrumented_resolve(task_id: str) -> str | None:
            winner_id = await original_resolve(task_id)
            labels: dict[str, str] = {"task_id": task_id}
            if winner_id is not None:
                labels["winner_id"] = winner_id
            collector.record_metric("laap_aaosa_resolutions_total", 1, labels)
            return winner_id

        coordinator.broadcast_task = _instrumented_broadcast
        coordinator.resolve_claims = _instrumented_resolve
