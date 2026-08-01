"""ErrorHandler — 完整错误处理系统(重试/熔断/降级/恢复/审计)"""
from __future__ import annotations
import time, json, logging, traceback, threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.error_handler")

class ErrorSeverity(Enum):
    DEBUG = 0; INFO = 1; WARNING = 2; ERROR = 3; CRITICAL = 4

class CircuitState(Enum):
    CLOSED = "closed"; HALF_OPEN = "half_open"; OPEN = "open"

@dataclass
class CircuitBreaker:
    name: str = ""; failure_count: int = 0; max_failures: int = 5
    recovery_timeout: float = 30.0; last_failure: float = 0.0
    state: CircuitState = CircuitState.CLOSED
    half_open_attempts: int = 0; max_half_open_attempts: int = 3

@dataclass
class ErrorRecord:
    timestamp: float = 0.0; source: str = ""; message: str = ""
    severity: ErrorSeverity = ErrorSeverity.ERROR; traceback: str = ""
    recovered: bool = False; duration_ms: float = 0.0

class ErrorHandler:
    """统一错误处理器 — 分类/重试/熔断/降级/恢复/审计"""
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._records: List[ErrorRecord] = []
        self._max_records = 1000
        self._recovery_handlers: Dict[str, Callable] = {}
        self._fallback_handlers: Dict[str, Callable] = {}
        self._stats = {"total_errors": 0, "recovered": 0, "circuit_breaks": 0}
        self._lock = threading.RLock()
    
    def classify(self, error: str) -> ErrorSeverity:
        """分类错误严重度"""
        error_lower = error.lower()
        if any(w in error_lower for w in ["critical", "fatal", "crash", "segfault"]):
            return ErrorSeverity.CRITICAL
        if any(w in error_lower for w in ["timeout", "rate", "limit", "429", "500", "503"]):
            return ErrorSeverity.ERROR
        if any(w in error_lower for w in ["warning", "deprecated", "slow"]):
            return ErrorSeverity.WARNING
        return ErrorSeverity.INFO
    
    def should_retry(self, error: str) -> bool:
        """判断是否应该重试"""
        return self.classify(error) in (ErrorSeverity.ERROR, ErrorSeverity.WARNING)
    
    def call_with_retry(self, fn: Callable, *args, name: str = "unknown",
                        max_retries: int = 3, base_delay: float = 1.0, **kwargs) -> Any:
        """带重试+指数退避+熔断的函数调用"""
        # Check circuit breaker
        breaker = self._get_or_create_breaker(name)
        self._check_circuit(breaker)
        
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                self._record_success(breaker)
                return result
            except Exception as e:
                last_error = e
                self._record_failure(breaker, name, str(e))
                
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Retry {attempt+1}/{max_retries} for {name}: {e}")
                    time.sleep(delay)
        
        # Try fallback
        if name in self._fallback_handlers:
            try:
                logger.info(f"Fallback for {name}")
                return self._fallback_handlers[name]()
            except Exception as e:
                logger.error(f"Fallback also failed: {e}")
        
        raise last_error
    
    def _get_or_create_breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name)
        return self._breakers[name]
    
    def _check_circuit(self, breaker: CircuitBreaker):
        if breaker.state == CircuitState.OPEN:
            elapsed = time.time() - breaker.last_failure
            if elapsed >= breaker.recovery_timeout:
                breaker.state = CircuitState.HALF_OPEN
                logger.info(f"Circuit {breaker.name} half-open")
            else:
                self._stats["circuit_breaks"] += 1
                raise Exception(f"Circuit breaker OPEN for {breaker.name} (retry in {breaker.recovery_timeout - elapsed:.0f}s)")
    
    def _record_failure(self, breaker: CircuitBreaker, name: str, msg: str):
        with self._lock:
            breaker.failure_count += 1
            breaker.last_failure = time.time()
            self._stats["total_errors"] += 1
            if breaker.failure_count >= breaker.max_failures:
                breaker.state = CircuitState.OPEN
                logger.warning(f"Circuit OPEN for {name} ({breaker.failure_count} failures)")
            rec = ErrorRecord(timestamp=time.time(), source=name, message=msg,
                              severity=ErrorSeverity.ERROR, recovered=False)
            self._records.append(rec)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
    
    def _record_success(self, breaker: CircuitBreaker):
        with self._lock:
            if breaker.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                breaker.state = CircuitState.CLOSED
                breaker.failure_count = 0
                logger.info(f"Circuit {breaker.name} closed")
    
    def register_fallback(self, name: str, handler: Callable):
        self._fallback_handlers[name] = handler
    
    def register_recovery(self, name: str, handler: Callable):
        self._recovery_handlers[name] = handler
    
    def get_stats(self) -> dict:
        return dict(self._stats, circuits=len(self._breakers),
                    open_circuits=sum(1 for b in self._breakers.values() if b.state == CircuitState.OPEN))
    
    def get_recent_errors(self, limit: int = 10) -> List[dict]:
        return [{"time": r.timestamp, "source": r.source, "msg": r.message[:80],
                 "recovered": r.recovered} for r in self._records[-limit:]]
