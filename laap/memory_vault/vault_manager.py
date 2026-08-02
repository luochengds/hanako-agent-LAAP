"""Small compatibility vault used by the RSI integration.

The repository's active memory providers live under ``laap.memory``.  Older
RSI and Truth Grounding code still needs an agent-scoped SQLite vault with the
``_get_vault`` and ``_open_vault_connection`` API.  This module deliberately
keeps that compatibility surface narrow and dependency-free; it does not
replace the active memory providers.

SQLCipher is not required here.  Callers must treat this as local state and
use the higher-level encrypted provider when vault encryption is required.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

from laap.config.paths import get_state_dir


_SAFE_AGENT = re.compile(r"[^A-Za-z0-9_.-]+")


def _open_vault_connection(db_path: str | Path, key_hex: str = "") -> sqlite3.Connection:
    """Open a row-mapping SQLite connection for a local agent vault.

    ``key_hex`` is accepted for API compatibility with the historical
    SQLCipher implementation.  Standard SQLite is used when SQLCipher is not
    installed, so callers can still run the RSI pipeline locally.
    """
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class VaultManager:
    """Agent-scoped local vault registry compatible with legacy callers."""

    def __init__(self, vault_dir: str | Path | None = None) -> None:
        self.vault_dir = str(vault_dir or (get_state_dir() / "vaults"))
        self._cache_lock = threading.RLock()
        self._vault_cache: Dict[str, Tuple[str, str]] = {}

    @staticmethod
    def _safe_agent_name(agent_name: str) -> str:
        value = _SAFE_AGENT.sub("_", str(agent_name or "default")).strip("._")
        return value[:80] or "default"

    def _get_vault(self, agent_name: str = "default") -> Tuple[str, str]:
        """Return ``(db_path, key_hex)`` for an isolated agent vault."""
        safe_name = self._safe_agent_name(agent_name)
        with self._cache_lock:
            cached = self._vault_cache.get(safe_name)
            if cached is not None:
                return cached
            root = Path(self.vault_dir).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            db_path = root / f"{safe_name}.sqlite3"
            # Stable compatibility key.  Standard SQLite ignores it; a future
            # SQLCipher adapter can use the same API without changing callers.
            key_hex = hashlib.sha256(safe_name.encode("utf-8")).hexdigest()
            result = (str(db_path), key_hex)
            self._vault_cache[safe_name] = result
            return result

    @staticmethod
    def _ensure_memory_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_scope_created "
            "ON memories(scope, created_at DESC)"
        )

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Store one memory through the legacy MCP vault API."""
        if not str(content).strip():
            raise ValueError("content must not be empty")
        scope = str(scope or "episodic")
        memory_id = f"mem_{uuid.uuid4().hex[:16]}"
        created_at = time.time()
        db_path, key_hex = self._get_vault(agent_name)
        conn = _open_vault_connection(db_path, key_hex)
        try:
            self._ensure_memory_schema(conn)
            conn.execute(
                "INSERT INTO memories(memory_id, agent_name, scope, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    str(agent_name),
                    scope,
                    str(content),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "stored": True,
            "memory_id": memory_id,
            "scope": scope,
            "created_at": created_at,
        }

    def retrieve(
        self,
        agent_name: str,
        query: str = "",
        scope: str | None = None,
        limit: int = 10,
    ) -> list[Dict[str, Any]]:
        """Retrieve memories from one agent vault using safe parameterized SQL."""
        db_path, key_hex = self._get_vault(agent_name)
        conn = _open_vault_connection(db_path, key_hex)
        try:
            self._ensure_memory_schema(conn)
            limit = max(1, min(int(limit), 200))
            clauses = []
            params: list[Any] = []
            if scope:
                clauses.append("scope = ?")
                params.append(str(scope))
            terms = [t for t in re.split(r"\\s+", str(query).strip()) if t]
            if terms:
                clauses.append("(" + " OR ".join("content LIKE ?" for _ in terms) + ")")
                params.extend(f"%{term}%" for term in terms)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = conn.execute(
                "SELECT memory_id, agent_name, scope, content, metadata, created_at "
                f"FROM memories{where} ORDER BY created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item["metadata"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    item["metadata"] = {}
                result.append(item)
            return result
        finally:
            conn.close()

    def consolidate(self, agent_name: str | None = None) -> Dict[str, Any]:
        """Return lightweight statistics for one or all initialized vaults."""
        root = Path(self.vault_dir).expanduser().resolve()
        names = [self._safe_agent_name(agent_name)] if agent_name else [
            p.stem for p in root.glob("*.sqlite3")
        ]
        vaults = []
        total = 0
        for name in names:
            db_path, key_hex = self._get_vault(name)
            conn = _open_vault_connection(db_path, key_hex)
            try:
                self._ensure_memory_schema(conn)
                count = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
                scopes = {
                    row[0]: int(row[1])
                    for row in conn.execute(
                        "SELECT scope, COUNT(*) FROM memories GROUP BY scope"
                    ).fetchall()
                }
                total += count
                vaults.append({"agent_name": name, "total": count, "by_scope": scopes})
            finally:
                conn.close()
        return {"total": total, "vaults": vaults}


vault_manager = VaultManager()

__all__ = ["VaultManager", "vault_manager", "_open_vault_connection"]
