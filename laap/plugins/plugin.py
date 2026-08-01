"""LAAP plugin dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Plugin:
    """A LAAP plugin descriptor.

    Plugins can extend tools, gateways, providers, or UI.  Activation failures
    must not propagate to the core system.
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    entrypoint: str = ""
    dependencies: List[str] = field(default_factory=list)
    hooks: Dict[str, List[str]] = field(default_factory=dict)
    enabled: bool = True
