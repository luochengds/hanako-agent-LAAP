"""LAAP Domain SDK — Domain-specific digital life agent framework.

This package provides the foundational infrastructure for building
domain-specialized digital life agents on top of LAAP's cognitive harness.

The Financial Quantitative SDK is the inaugural domain SDK, with subsequent
domains (legal, biomed, research, startup) following the same contract.

Core API::

    from laap.domain_sdk import (
        # Base contract
        DomainSDKBase, DomainManifest,
        # Harness functions
        HarnessFunction, HarnessFunctionRegistry, harness_function,
        # Safety
        DomainSafetyPolicy, SafetyBreachError, SafetyCheckResult, SafetyViolationType,
        # Species library
        SpeciesTemplate, SpeciesInstance, SpeciesLibrary,
        # Registry
        DomainSDKRegistry,
    )
"""

from __future__ import annotations

from laap.domain_sdk.base import DomainManifest, DomainSDKBase
from laap.domain_sdk.harness_function import (
    HarnessFunction,
    HarnessFunctionRegistry,
    harness_function,
)
from laap.domain_sdk.safety_policy import (
    AllowAllSafetyPolicy,
    DomainSafetyPolicy,
    SafetyBreachError,
    SafetyCheckResult,
    SafetyViolationType,
)
from laap.domain_sdk.species import (
    SpeciesInstance,
    SpeciesLibrary,
    SpeciesTemplate,
)
from laap.domain_sdk.registry import DomainSDKRegistry

__all__ = [
    # Base contract
    "DomainSDKBase",
    "DomainManifest",
    # Harness functions
    "HarnessFunction",
    "HarnessFunctionRegistry",
    "harness_function",
    # Safety
    "DomainSafetyPolicy",
    "AllowAllSafetyPolicy",
    "SafetyBreachError",
    "SafetyCheckResult",
    "SafetyViolationType",
    # Species library
    "SpeciesTemplate",
    "SpeciesInstance",
    "SpeciesLibrary",
    # Registry
    "DomainSDKRegistry",
]
