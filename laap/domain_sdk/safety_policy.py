"""LAAP Domain SDK — Safety Policy Framework.

Domain safety policies are hard gates that cannot be overridden by the LLM.
They run in LAAP's security ``zone_executor`` BEFORE any domain action
(order, medical recommendation, legal advice) is executed.

Key principle: **Safety is enforced in code, not in prompts.** The LLM
cannot bypass these gates via prompt injection or social engineering
because the checks execute deterministically in Python.

Usage::

    from laap.domain_sdk import DomainSafetyPolicy, SafetyBreachError

    class FinQuantSafetyPolicy(DomainSafetyPolicy):
        max_position_pct: float = 0.10

        def pre_execution_gate(self, action, context):
            if action.size / context.capital > self.max_position_pct:
                raise SafetyBreachError(
                    f"Position size {action.size} exceeds max {self.max_position_pct}",
                    policy=self.domain_id,
                    violation="position_limit",
                )
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.domain_sdk.safety_policy")


class SafetyViolationType(Enum):
    """Categories of safety violations for structured error handling."""

    POSITION_LIMIT = auto()
    DRAWDOWN_LIMIT = auto()
    RATE_LIMIT = auto()
    RESTRICTED_ITEM = auto()
    LIQUIDITY = auto()
    COMPLIANCE = auto()
    LEVERAGE = auto()
    CONCENTRATION = auto()
    CUSTOM = auto()


class SafetyBreachError(Exception):
    """Raised when a safety policy gate is violated.

    This error cannot be caught and suppressed by the LLM — it propagates
    up through the CognitiveBus and halts the action pipeline.

    Attributes:
        message: Human-readable error description.
        domain: Domain ID that raised the breach.
        violation: Type of violation (SafetyViolationType or string).
        details: Additional context dict for logging/auditing.
    """

    def __init__(
        self,
        message: str,
        domain: str = "",
        violation: Any = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.domain = domain
        self.violation = violation if isinstance(violation, SafetyViolationType) else SafetyViolationType.CUSTOM
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "SafetyBreachError",
            "message": self.message,
            "domain": self.domain,
            "violation": self.violation.name,
            "details": self.details,
        }

    def __str__(self) -> str:
        return f"[SafetyBreach:{self.violation.name}] {self.message}"


@dataclass
class SafetyCheckResult:
    """Result of a safety policy check (non-raising form).

    Attributes:
        passed: True if the check passed.
        violation: Violation type if failed, None otherwise.
        message: Description if failed.
        severity: "info", "warning", "critical".
        details: Additional context.
    """

    passed: bool = True
    violation: Optional[SafetyViolationType] = None
    message: str = ""
    severity: str = "info"
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls) -> "SafetyCheckResult":
        return cls(passed=True)

    @classmethod
    def fail(
        cls,
        violation: SafetyViolationType,
        message: str,
        severity: str = "critical",
        details: Optional[Dict[str, Any]] = None,
    ) -> "SafetyCheckResult":
        return cls(
            passed=False,
            violation=violation,
            message=message,
            severity=severity,
            details=details or {},
        )

    def raise_if_failed(self, domain: str = "") -> None:
        """Convert to SafetyBreachError if the check failed."""
        if not self.passed:
            raise SafetyBreachError(
                message=self.message,
                domain=domain,
                violation=self.violation,
                details=self.details,
            )


class DomainSafetyPolicy(ABC):
    """Abstract base for domain safety policies.

    Subclasses define domain-specific safety constraints as class attributes
    and implement the ``pre_execution_gate`` method. The gate is called
    before every domain action and raises ``SafetyBreachError`` on violation.

    The policy also supports non-raising validation via ``validate()``
    which returns a ``SafetyCheckResult`` for advisory checks.

    Attributes:
        domain_id: Domain identifier (set by subclass or SDK).
    """

    domain_id: str = "base"

    @abstractmethod
    def pre_execution_gate(self, action: Any, context: Any) -> None:
        """Hard gate — raises SafetyBreachError if any constraint is violated.

        This method is called BEFORE any domain action is executed. It must
        be deterministic and must not depend on LLM output.

        Args:
            action: The action to validate (e.g. Order, Recommendation).
            context: Execution context (e.g. Portfolio, PatientRecord).

        Raises:
            SafetyBreachError: If any safety constraint is violated.
        """
        ...

    def validate(self, action: Any, context: Any) -> SafetyCheckResult:
        """Non-raising validation — returns a SafetyCheckResult.

        Default implementation calls ``pre_execution_gate`` and catches
        the error. Subclasses may override for more granular checks.

        Args:
            action: The action to validate.
            context: Execution context.

        Returns:
            SafetyCheckResult indicating pass/fail with details.
        """
        try:
            self.pre_execution_gate(action, context)
            return SafetyCheckResult.ok()
        except SafetyBreachError as e:
            return SafetyCheckResult.fail(
                violation=e.violation,
                message=e.message,
                details=e.details,
            )

    def get_config(self) -> Dict[str, Any]:
        """Return the policy's configuration as a dict.

        Subclasses can override to expose their constraint values for
        inspection, CLI display, or dynamic adjustment.
        """
        return {
            attr: getattr(self, attr)
            for attr in dir(self)
            if not attr.startswith("_")
            and not callable(getattr(self, attr))
            and attr not in ("domain_id",)
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} domain={self.domain_id}>"


class AllowAllSafetyPolicy(DomainSafetyPolicy):
    """Permissive policy that allows all actions.

    For development and testing only. Never use in production.
    """

    domain_id: str = "dev"

    def pre_execution_gate(self, action: Any, context: Any) -> None:
        """Always passes — no checks performed."""
        pass
