"""LAAP observability package.

Provides structured JSON logging and a minimal Prometheus-style metrics
exporter. Designed to depend only on the Python standard library so it
remains importable in minimal CI environments.

Public API:
    from laap.observability.logger import StructuredLogger, get_logger, PrometheusExporter
"""

from laap.observability.logger import (
    PrometheusExporter,
    StructuredLogger,
    get_logger,
)

__all__ = ["StructuredLogger", "get_logger", "PrometheusExporter"]
