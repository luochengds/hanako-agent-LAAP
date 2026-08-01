"""Cognition monitor — lightweight per-turn data collection for the quantum engine.

Logs structured metadata (no message content) to a rotating JSONL file.
Enables offline analysis of hallucination guard behavior and quantum
engine performance.

Log format (JSONL, one object per line):
  {
    "ts": 1234567890.123,         // Unix timestamp
    "turn": 42,                   // Turn number
    "scenario": "normal",         // Optional classification
    "cognition_ms": 0.5,          // Quantum engine time
    "generation_ms": 850.0,       // LLM generation time
    "total_ms": 860.0,            // Total turn time
    
    // Quantum state
    "confidence": 0.58,
    "uncertainty": 0.19,
    "entropy": 0.004,
    "coherence": 0.72,
    "arousal": 0.35,
    "curiosity": 1.0,
    
    // Guard decisions
    "guard_action": "generate",   // generate / reject / caveat
    "guard_reason": "pass",
    "guard_latency_ms": 0.01,
    
    // Post-validation
    "validation_valid": true,
    "validation_caveat": false,
    "validation_issues": [],
    
    // Token usage
    "input_tokens": 150,
    "output_tokens": 85,
    "hqkv_prefix_tokens": 38,
    
    "temperature": 0.55,
    "top_p": 0.95,
    "success": true,
  }

Usage:
    from laap.agent_core.quantum_cognition.cognition_monitor import CognitionMonitor
    monitor = CognitionMonitor()
    monitor.log_turn(stats, decision, result, ...)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('quantum_cognition.monitor')


@dataclass
class TurnRecord:
    """Single turn record for the cognition monitor.

    All fields optional — only populated fields are logged.
    """
    ts: float = 0.0
    turn: int = 0
    cognition_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0

    # Quantum state
    confidence: float = 0.5
    uncertainty: float = 0.5
    entropy: float = 0.5
    coherence: float = 0.5
    arousal: float = 0.5
    curiosity: float = 1.0

    # Guard
    guard_action: str = 'generate'
    guard_reason: str = 'pass'
    guard_latency_ms: float = 0.0

    # Validation
    validation_valid: bool = True
    validation_caveat: bool = False
    validation_issues: List[str] = field(default_factory=list)

    # Token usage
    input_tokens: int = 0
    output_tokens: int = 0
    hqkv_prefix_tokens: int = 0

    # Generation params
    temperature: float = 0.7
    top_p: float = 0.9

    # Learning
    success: bool = True


class CognitionMonitor:
    """Lightweight per-turn data collection for the quantum cognition engine.

    Logs to a rotating JSONL file at *log_dir*.  Files are rotated daily.

    Parameters
    ----------
    log_dir : str, optional
        Directory for log files.  Defaults to ``~/.laap/monitor/``.
    max_records_per_file : int
        Max records before rotation.  Default 100000.
    enabled : bool
        If False, all log calls are no-ops.
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        max_records_per_file: int = 100000,
        enabled: bool = True,
    ):
        self._enabled = enabled
        if not enabled:
            self._file = None
            self._turn_count = 0
            return

        self._log_dir = log_dir or os.path.expanduser('~/.laap/monitor')
        os.makedirs(self._log_dir, exist_ok=True)
        self._max_records = max_records_per_file
        self._turn_count = 0
        self._records_since_rotation = 0

        self._open_file()

    def _open_file(self):
        """Open a new log file with timestamped name."""
        date_str = time.strftime('%Y%m%d')
        self._filepath = os.path.join(
            self._log_dir, f'cognition_{date_str}.jsonl'
        )
        self._file = open(self._filepath, 'a', encoding='utf-8')
        self._records_since_rotation = 0
        logger.info(f'[monitor] logging to {self._filepath}')

    def _maybe_rotate(self):
        """Rotate log file if max_records exceeded."""
        if self._records_since_rotation >= self._max_records:
            self._file.close()
            self._open_file()

    def log_turn(
        self,
        quantum_stats: Optional[Dict] = None,
        guard_decision: Optional[Dict] = None,
        validation_result: Optional[Dict] = None,
        generation_params: Optional[Dict] = None,
        timing: Optional[Dict] = None,
        tokens: Optional[Dict] = None,
        success: bool = True,
    ):
        """Log a single turn's data.

        All parameters are optional — missing fields use defaults.
        Only log the fields you have; unused fields are omitted.

        Parameters
        ----------
        quantum_stats : dict, optional
            From ``PsiQuantumCognition.get_stats()``.
        guard_decision : dict, optional
            With keys 'action', 'reason'.
        validation_result : dict, optional
            From ``HallucinationGuard.validate()``.
            With keys 'is_valid', 'needs_caveat', 'issues'.
        generation_params : dict, optional
            With keys 'temperature', 'top_p', 'hqkv_prefix_tokens'.
        timing : dict, optional
            With keys 'cognition_ms', 'generation_ms', 'total_ms'.
        tokens : dict, optional
            With keys 'input_tokens', 'output_tokens'.
        success : bool
            Whether the turn was completed successfully.
        """
        if not self._enabled or (self._file is None):
            return

        self._turn_count += 1

        record = TurnRecord(
            ts=time.time(),
            turn=self._turn_count,
            success=success,
        )

        # Quantum stats
        if quantum_stats:
            record.confidence = quantum_stats.get('confidence', 0.5)
            record.uncertainty = quantum_stats.get('uncertainty', 0.5)
            record.entropy = quantum_stats.get('quantum_entropy', 0.5)
            record.coherence = quantum_stats.get('spectral_coherence', 0.5)
            record.arousal = quantum_stats.get('arousal', 0.5)
            record.curiosity = quantum_stats.get('curiosity', 1.0)

        # Guard decision
        if guard_decision:
            record.guard_action = guard_decision.get('action', 'generate')
            record.guard_reason = guard_decision.get('reason', 'pass')

        # Validation
        if validation_result:
            record.validation_valid = validation_result.get('is_valid', True)
            record.validation_caveat = validation_result.get('needs_caveat', False)
            record.validation_issues = validation_result.get('issues', [])

        # Generation params
        if generation_params:
            record.temperature = generation_params.get('temperature', 0.7)
            record.top_p = generation_params.get('top_p', 0.9)
            record.hqkv_prefix_tokens = generation_params.get('hqkv_prefix_tokens', 0)

        # Timing
        if timing:
            record.cognition_ms = timing.get('cognition_ms', 0.0)
            record.generation_ms = timing.get('generation_ms', 0.0)
            record.total_ms = timing.get('total_ms', 0.0)

        # Tokens
        if tokens:
            record.input_tokens = tokens.get('input_tokens', 0)
            record.output_tokens = tokens.get('output_tokens', 0)

        # Write JSONL (compact, no whitespace)
        data = {k: v for k, v in asdict(record).items()
                if v is not None and v != []}
        line = json.dumps(data, ensure_ascii=False, separators=(',', ':'))

        try:
            self._file.write(line + '\n')
            self._file.flush()
            self._records_since_rotation += 1
            self._maybe_rotate()
        except OSError as e:
            logger.warning(f'[monitor] write failed: {e}')

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return monitor statistics."""
        return {
            'enabled': self._enabled,
            'total_turns': self._turn_count,
            'log_dir': self._log_dir,
            'current_file': getattr(self, '_filepath', ''),
        }

    def close(self):
        """Close the log file."""
        if self._file:
            self._file.close()
            self._file = None

    def __repr__(self) -> str:
        return (f'CognitionMonitor(turns={self._turn_count}, '
                f'file={getattr(self, "_filepath", "N/A")})')
