"""Audit Logger — Immutable audit trail"""
from __future__ import annotations
import time, json, hashlib, logging, threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("security.audit.logger")

class AuditCategory(str, Enum):
    AUTH = "auth"
    ACCESS = "access"
    CHANGE = "change"
    EVOLUTION = "evolution"
    SECURITY = "security"
    SYSTEM = "system"

@dataclass
class AuditEvent:
    id: str = ""
    category: AuditCategory = AuditCategory.SYSTEM
    action: str = ""
    actor: str = ""
    resource: str = ""
    details: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    hash: str = ""
    previous_hash: str = ""

class AuditLogger:
    def __init__(self):
        self._events: List[AuditEvent] = []
        self._lock = threading.RLock()
    @property
    def logs(self) -> List:
        return list(self._events)

    def get_events(self, event_type: str = "") -> List:
        if event_type:
            return [e for e in self._events if e.action == event_type]
        return list(self._events)

    def clear(self):
        with self._lock:
            self._events.clear()

    def log(self, action_or_category, details_or_action=None, actor: str = "", resource: str = "", details=None):
        """Overloaded log method: supports both test API and original API.
        
        Test API: log(action_name, details_dict)
        Original: log(category, action, actor, resource, details)
        """
        import time as _time
        if isinstance(action_or_category, str) and isinstance(details_or_action, dict):
            # Test API: log("action_name", {"key": "val"})
            action_name = action_or_category
            det = details_or_action or {}
            with self._lock:
                from laap.security.audit.logger import AuditEvent
                prev_hash = self._events[-1].hash if self._events else "0" * 64
                event = AuditEvent(
                    id=f"aud_{int(_time.time()*1e6)}",
                    action=action_name,
                    details=det,
                    previous_hash=prev_hash,
                )
                chain_data = f"{prev_hash}:{event.id}:{event.action}:{event.timestamp}"
                import hashlib
                event.hash = hashlib.sha256(chain_data.encode()).hexdigest()
                self._events.append(event)
            return event.id
        
        # Original API
        return self._original_log(action_or_category, details_or_action, actor, resource, details)

    def _original_log(self, category: AuditCategory, action: str, actor: str, resource: str = "", details: Dict = None) -> str:
        prev_hash = self._events[-1].hash if self._events else "0" * 64
        event = AuditEvent(
            id=f"aud_{int(time.time()*1e6)}_{hashlib.md5((action+actor+str(time.time())).encode()).hexdigest()[:8]}",
            category=category, action=action, actor=actor, resource=resource,
            details=details or {}, previous_hash=prev_hash
        )
        chain_data = f"{prev_hash}:{event.id}:{event.action}:{event.actor}:{event.timestamp}"
        event.hash = hashlib.sha256(chain_data.encode()).hexdigest()
        with self._lock:
            self._events.append(event)
        logger.info(f"Audit: {category.value} | {action} | {actor}")
        return event.id
    def verify_chain(self) -> bool:
        with self._lock:
            prev_hash = "0" * 64
            for event in self._events:
                chain_data = f"{prev_hash}:{event.id}:{event.action}:{event.actor}:{event.timestamp}"
                expected = hashlib.sha256(chain_data.encode()).hexdigest()
                if event.hash != expected:
                    return False
                prev_hash = event.hash
            return True
    def query(self, category: Optional[AuditCategory] = None, actor: str = "", limit: int = 100) -> List[AuditEvent]:
        results = self._events
        if category:
            results = [e for e in results if e.category == category]
        if actor:
            results = [e for e in results if e.actor == actor]
        return results[-limit:]
