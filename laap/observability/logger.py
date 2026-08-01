"""Structured JSON logging + minimal Prometheus exporter.

This module deliberately uses only the Python standard library so it can
be imported in any environment without extra dependencies. The
:class:`StructuredLogger` emits one JSON object per log record with the
following fields:

    {
      "timestamp":     ISO-8601 UTC,
      "component":     user-supplied component name,
      "event_type":    level name (INFO / WARNING / ERROR / ...),
      "payload":       user-supplied dict or string,
      "self_model_version": module-level version tag
    }

The :class:`PrometheusExporter` keeps an in-memory registry of counters
and gauges and can expose them on ``http://localhost:9090/metrics`` in
the Prometheus text exposition format.

Usage:
    from laap.observability.logger import get_logger, PrometheusExporter

    log = get_logger("psi_driver")
    log.info("cycle_complete", {"cycle_id": 42, "latency_ms": 7.3})

    exporter = PrometheusExporter()
    exporter.inc("psi_cycles_total")
    exporter.set("psi_latency_ms", 7.3)
    exporter.expose_http()  # blocks; serves /metrics on port 9090
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Union

# Default version tag — kept simple so the module stays dependency-free.
# Tools that maintain a Self Model can override this via ``set_self_model_version``.
_SELF_MODEL_VERSION = "unspecified"


def set_self_model_version(version: str) -> None:
    """Override the ``self_model_version`` field embedded in every record."""
    global _SELF_MODEL_VERSION
    _SELF_MODEL_VERSION = str(version)


def get_self_model_version() -> str:
    """Return the current ``self_model_version`` tag."""
    return _SELF_MODEL_VERSION


Payload = Union[Dict[str, Any], str, None]


class StructuredLogger:
    """JSON-line logger backed by the stdlib :mod:`logging` module.

    Each call to :meth:`info` / :meth:`warning` / :meth:`error` /
    :meth:`debug` emits a single JSON object on a single line, making
    the output trivially consumable by ``jq``, ELK, Datadog, etc.
    """

    def __init__(self, component: str, logger: Optional[logging.Logger] = None) -> None:
        self.component = component
        self._logger = logger or logging.getLogger(f"laap.observability.{component}")
        # Ensure at least one handler exists so records are not lost when
        # the host application has not configured logging.
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

    # ── Core emit ─────────────────────────────────────────────────────

    def _emit(self, level: str, event_type: str, message: str, payload: Payload) -> None:
        record = {
            "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
            "component": self.component,
            "event_type": event_type,
            "message": message,
            "payload": payload if payload is not None else {},
            "self_model_version": get_self_model_version(),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        levelno = getattr(logging, level, logging.INFO)
        self._logger.log(levelno, line)

    # ── Convenience helpers ───────────────────────────────────────────

    def debug(self, message: str, payload: Payload = None) -> None:
        self._emit("DEBUG", "debug", message, payload)

    def info(self, message: str, payload: Payload = None) -> None:
        self._emit("INFO", "info", message, payload)

    def warning(self, message: str, payload: Payload = None) -> None:
        self._emit("WARNING", "warning", message, payload)

    def error(self, message: str, payload: Payload = None) -> None:
        self._emit("ERROR", "error", message, payload)

    def critical(self, message: str, payload: Payload = None) -> None:
        self._emit("CRITICAL", "critical", message, payload)

    # ── Compatibility with logging.Logger ─────────────────────────────

    def log(self, level: int, message: str, payload: Payload = None) -> None:
        name = logging.getLevelName(level)
        self._emit(name, name.lower(), message, payload)


def get_logger(component: str) -> StructuredLogger:
    """Factory returning a :class:`StructuredLogger` for ``component``."""
    return StructuredLogger(component)


# ═══════════════════════════════════════════════════════════════════════
#  PrometheusExporter — minimal in-process metrics + HTTP exposition
# ═══════════════════════════════════════════════════════════════════════


class PrometheusExporter:
    """Minimal Prometheus-style counter/gauge exporter.

    Maintains an in-process registry of metrics (counters and gauges)
    and can expose them on ``http://localhost:9090/metrics`` in the
    Prometheus text exposition format.

    Note:
        This implementation intentionally depends only on the standard
        library. For production deployments, prefer the
        ``prometheus_client`` package — this class is a drop-in
        fallback for minimal environments.
    """

    DEFAULT_PORT = 9090

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None

    # ── Metric mutations ──────────────────────────────────────────────

    def inc(self, name: str, value: float = 1.0) -> None:
        """Increment a counter by ``value`` (must be ≥ 0)."""
        if value < 0:
            raise ValueError("counter increments must be non-negative")
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value

    def set(self, name: str, value: float) -> None:
        """Set a gauge to ``value``."""
        with self._lock:
            self._gauges[name] = float(value)

    # ── Serialisation ─────────────────────────────────────────────────

    def render(self) -> str:
        """Render the registry in the Prometheus text exposition format."""
        lines = []
        with self._lock:
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
        return "\n".join(lines) + ("\n" if lines else "")

    # ── HTTP exposition ───────────────────────────────────────────────

    def expose_http(self, port: Optional[int] = None, block: bool = True) -> None:
        """Serve ``/metrics`` on ``port`` (default 9090).

        Args:
            port: Override the port set at construction time.
            block: When ``True`` (default), blocks the calling thread
                serving requests until interrupted. When ``False``, the
                server runs in a background daemon thread and the call
                returns immediately.
        """
        if port is None:
            port = self.port

        exporter = self

        class _MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib API name
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = exporter.render().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                # Silence default request logging to keep stdout clean.
                return

        self._server = ThreadingHTTPServer(("0.0.0.0", port), _MetricsHandler)
        if not block:
            self._server_thread = threading.Thread(
                target=self._server.serve_forever, daemon=True
            )
            self._server_thread.start()
            return
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._server.shutdown()

    def stop(self) -> None:
        """Stop the HTTP server if it was started in non-blocking mode."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)
            self._server_thread = None
