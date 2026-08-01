"""LAAP Skill dataclass.

A Skill is a discoverable, versioned capability bundle.  It is described by a
``skill.yaml`` file and implemented by a small Python handler (usually
``main.py``) that exposes the advertised capabilities.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    """A loaded skill with metadata, capabilities, and handler information."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    schema: Dict[str, Any] = field(default_factory=dict)
    handler_path: str = "main.py"
    config: Dict[str, Any] = field(default_factory=dict)

    # Legacy / metadata fields preserved for backward compatibility with the
    # previous SKILL.md-based skills system.
    body: str = ""
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None
    platform: str = "all"
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    author: str = ""
    enabled: bool = True
    loaded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description[:120],
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "platform": self.platform,
            "enabled": self.enabled,
            "capabilities": self.capabilities,
            "body_size": len(self.body),
        }

    def to_short_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description[:80],
            "category": self.category,
        }
