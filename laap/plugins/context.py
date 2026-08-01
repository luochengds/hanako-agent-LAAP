"""LAAP plugin execution context."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PluginContext:
    """Runtime context passed to a plugin during activation.

    The context exposes registries so plugins can register tools, gateways,
    providers, or UI extensions without directly importing implementation
    details.
    """

    tool_registry: Optional[Any] = None
    gateway_registry: Optional[Any] = None
    provider_registry: Optional[Any] = None
