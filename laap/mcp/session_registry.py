"""LAAP MCP — Session Registry

Persistent mapping between MCP client session_ids and LAAP lifeform_ids.
Enables external MCP clients (Claude Code / Cursor / Trae) to mount a
stable LAAP cognitive brain across multiple sessions.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("laap.mcp.session_registry")


class MCPSessionRegistry:
    """Thread-safe persistent registry mapping MCP session_id to lifeform_id.

    The mapping is persisted to a JSON file (default ``~/.laap/mcp_sessions.json``)
    so that the same MCP client session can resume its LAAP brain state across
    server restarts. Writes are atomic (write to ``<path>.tmp`` then rename).
    """

    DEFAULT_FILE_NAME = "mcp_sessions.json"

    def __init__(self, file_path: Optional[str] = None) -> None:
        """Initialize the session registry.

        Args:
            file_path: Optional override for the persistence file path.
                When ``None``, defaults to ``~/.laap/mcp_sessions.json``.
        """
        if file_path is not None:
            self.file_path: str = file_path
        else:
            laap_home = os.environ.get("LAAP_ROOT") or str(Path.home() / ".laap")
            self.file_path = os.path.join(laap_home, self.DEFAULT_FILE_NAME)

        self._lock = threading.Lock()
        self._sessions: Dict[str, str] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────

    def register_session(
        self, session_id: str, lifeform_id: Optional[str] = None
    ) -> str:
        """Register a session and return its lifeform_id.

        If the session_id is already known, the existing lifeform_id is
        returned unchanged. If a new lifeform_id is not provided, one is
        generated as ``f"mcp-{session_id[:8]}"``.

        Args:
            session_id: MCP client session identifier.
            lifeform_id: Optional explicit lifeform_id to associate.

        Returns:
            The lifeform_id bound to this session_id.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")

        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                # Keep the existing binding unless caller explicitly overrides.
                if lifeform_id is not None and lifeform_id != existing:
                    self._sessions[session_id] = lifeform_id
                    self._persist()
                    return lifeform_id
                return existing

            resolved = lifeform_id or f"mcp-{session_id[:8]}"
            self._sessions[session_id] = resolved
            self._persist()
            return resolved

    def get_lifeform_id(self, session_id: str) -> Optional[str]:
        """Look up the lifeform_id for a session_id.

        Args:
            session_id: MCP client session identifier.

        Returns:
            The bound lifeform_id, or ``None`` if unknown.
        """
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> Dict[str, str]:
        """Return a shallow copy of all session_id → lifeform_id mappings."""
        with self._lock:
            return dict(self._sessions)

    # ── persistence helpers ───────────────────────────────────────────

    def _persist(self) -> None:
        """Atomically write the session map to ``self.file_path``.

        Caller must already hold ``self._lock``.
        """
        try:
            parent = os.path.dirname(self.file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = self.file_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._sessions, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.file_path)
        except Exception as e:  # pragma: no cover - best effort persistence
            logger.warning(
                f"MCPSessionRegistry: failed to persist {self.file_path}: {e}"
            )

    def _load(self) -> None:
        """Load the session map from ``self.file_path`` if it exists."""
        try:
            if not os.path.exists(self.file_path):
                return
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                with self._lock:
                    self._sessions = {
                        str(k): str(v) for k, v in data.items() if k and v
                    }
            logger.debug(
                f"MCPSessionRegistry: loaded {len(self._sessions)} sessions from {self.file_path}"
            )
        except Exception as e:  # pragma: no cover - best effort load
            logger.warning(f"MCPSessionRegistry: failed to load {self.file_path}: {e}")

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._sessions)
        return f"<MCPSessionRegistry file={self.file_path!r} sessions={count}>"


# ── module-level singleton ────────────────────────────────────────────

_REGISTRY: Optional[MCPSessionRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> MCPSessionRegistry:
    """Return the process-wide :class:`MCPSessionRegistry` singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = MCPSessionRegistry()
    return _REGISTRY


__all__ = ["MCPSessionRegistry", "get_registry"]
