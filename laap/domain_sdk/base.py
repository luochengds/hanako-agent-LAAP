"""LAAP Domain SDK — Domain-specific digital life agent framework.

This module defines the abstract contract that all domain SDKs implement.
It mirrors the existing ``AgentAdapter`` pattern (laap/sdk/adapter.py):
each domain SDK "adapts" LAAP's generic cognitive harness to a specific
domain by registering specialized harness functions, cognitive actors,
species templates, CognitiveBus topics, and safety policies.

Usage::

    from laap.domain_sdk import DomainSDKBase, DomainManifest

    class FinQuantDomainSDK(DomainSDKBase):
        def manifest(self) -> DomainManifest:
            return DomainManifest(
                domain_id="finquant",
                domain_name="Financial Quantitative",
                version="1.0.0",
                description="Financial quantitative analysis digital life agent",
            )
        def register_harness_functions(self, registry): ...
        def register_cognitive_actors(self, actor_system): ...
        def register_species_templates(self, species_library): ...
        def register_bus_topics(self, cognitive_bus): ...
        def get_safety_policy(self): ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from laap.domain_sdk.harness_function import HarnessFunctionRegistry
    from laap.domain_sdk.safety_policy import DomainSafetyPolicy
    from laap.domain_sdk.species import SpeciesLibrary

logger = logging.getLogger("laap.domain_sdk.base")


@dataclass
class DomainManifest:
    """Manifest describing a domain SDK.

    Analogous to ``skill.yaml`` but for domain SDKs. Provides metadata
    for discovery, compatibility checking, and capability advertisement.

    Attributes:
        domain_id: Unique lowercase identifier (e.g. "finquant").
        domain_name: Human-readable name (e.g. "Financial Quantitative").
        version: Semantic version string.
        description: Short description of the domain.
        cognitive_actors: List of actor IDs this SDK spawns.
        harness_functions: List of harness function names this SDK registers.
        bus_topics: List of CognitiveBus topics this SDK publishes/subscribes.
        species_categories: Categories of species templates this SDK provides.
        data_sources: External data sources this SDK integrates.
        safety_policy_class: Dotted path to the safety policy class.
        min_laap_version: Minimum LAAP version required.
    """

    domain_id: str
    domain_name: str
    version: str = "0.0.0"
    description: str = ""
    cognitive_actors: List[str] = field(default_factory=list)
    harness_functions: List[str] = field(default_factory=list)
    bus_topics: List[str] = field(default_factory=list)
    species_categories: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    safety_policy_class: Optional[str] = None
    min_laap_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manifest to a dict for CLI output / JSON API."""
        return {
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "version": self.version,
            "description": self.description,
            "cognitive_actors": list(self.cognitive_actors),
            "harness_functions": list(self.harness_functions),
            "bus_topics": list(self.bus_topics),
            "species_categories": list(self.species_categories),
            "data_sources": list(self.data_sources),
            "safety_policy_class": self.safety_policy_class,
            "min_laap_version": self.min_laap_version,
        }


class DomainSDKBase(ABC):
    """Abstract contract for all domain SDKs.

    Every domain SDK inherits from this class and implements 6 abstract methods.
    The ``initialize()`` method provides a standard registration sequence that
    mounts the SDK into a ``LAAPRuntime`` instance.

    This mirrors the ``AgentAdapter`` pattern (laap/sdk/adapter.py): domain SDKs
    "adapt" LAAP to a specific domain, just as agent adapters adapt LAAP's
    brain to a specific external agent host.

    Abstract methods:
        - manifest(): Return the domain manifest metadata.
        - register_harness_functions(registry): Register deterministic computations.
        - register_cognitive_actors(actor_system): Spawn domain actors.
        - register_species_templates(species_library): Add precompiled templates.
        - register_bus_topics(cognitive_bus): Subscribe to CognitiveBus topics.
        - get_safety_policy(): Return the domain safety policy enforcer.
    """

    @abstractmethod
    def manifest(self) -> DomainManifest:
        """Return the domain manifest.

        Returns:
            DomainManifest with domain metadata.
        """
        ...

    @abstractmethod
    def register_harness_functions(
        self, registry: "HarnessFunctionRegistry"
    ) -> None:
        """Register domain-specific harness functions.

        Harness functions are deterministic, token-free computations that
        the LLM can invoke via tool-calls. They are the primary mechanism
        for surpassing general-purpose LLM limitations in the domain.

        Args:
            registry: The runtime's harness function registry to register into.
        """
        ...

    @abstractmethod
    def register_cognitive_actors(self, actor_system: Any) -> None:
        """Spawn domain-specific cognitive actors into the ActorSystem.

        Each actor advertises Capabilities that the CognitiveBus can route
        messages to. Actors wrap harness functions with PSI state tracking.

        Args:
            actor_system: The runtime's ActorSystem instance.
        """
        ...

    @abstractmethod
    def register_species_templates(
        self, species_library: "SpeciesLibrary"
    ) -> None:
        """Register domain-specific cognitive species templates.

        Species templates are precompiled reasoning patterns that enable
        zero-token code generation for recurring domain tasks.

        Args:
            species_library: The runtime's species library to add templates into.
        """
        ...

    @abstractmethod
    def register_bus_topics(self, cognitive_bus: Any) -> None:
        """Register domain-specific CognitiveBus topics.

        Follows the namespace convention: ``{domain}.{category}.{action}``
        e.g. ``finquant.market.stream``, ``finquant.risk.assess``.

        Args:
            cognitive_bus: The runtime's ArisCognitiveBus instance.
        """
        ...

    @abstractmethod
    def get_safety_policy(self) -> "DomainSafetyPolicy":
        """Return the domain safety policy enforcer.

        Safety policies are hard gates that cannot be overridden by the LLM.
        For financial domain: position limits, drawdown kill-switch, etc.

        Returns:
            DomainSafetyPolicy instance for this domain.
        """
        ...

    # ── Standard initialization sequence ────────────────────────────

    def initialize(self, runtime: Any) -> None:
        """Mount this domain SDK into a LAAPRuntime.

        Calls all registration methods in the correct order and stores
        the safety policy in the runtime's policy map. This method is
        called by ``LAAPRuntime.mount_domain()`` and should not be
        called directly by SDK authors.

        Args:
            runtime: The LAAPRuntime instance to mount into.

        Raises:
            RuntimeError: If the runtime lacks required registries.
        """
        manifest = self.manifest()
        logger.info(
            "Initializing domain SDK: %s v%s (%s)",
            manifest.domain_id,
            manifest.version,
            manifest.domain_name,
        )

        # Validate runtime has required registries
        if not hasattr(runtime, "_harness_registry"):
            raise RuntimeError(
                "Runtime missing _harness_registry; "
                "ensure LAAPRuntime is initialized with domain_sdk support"
            )
        if not hasattr(runtime, "_species_library"):
            raise RuntimeError(
                "Runtime missing _species_library; "
                "ensure LAAPRuntime is initialized with domain_sdk support"
            )
        if not hasattr(runtime, "_safety_policies"):
            raise RuntimeError(
                "Runtime missing _safety_policies; "
                "ensure LAAPRuntime is initialized with domain_sdk support"
            )

        # Register in correct order: functions → species → actors → bus → safety
        self.register_harness_functions(runtime._harness_registry)
        self.register_species_templates(runtime._species_library)

        if hasattr(runtime, "system"):
            self.register_cognitive_actors(runtime.system)

        if runtime._cognitive_bus is not None:
            self.register_bus_topics(runtime._cognitive_bus)
        elif hasattr(runtime, "_cognitive_bus"):
            logger.debug(
                "CognitiveBus not yet initialized for domain %s; "
                "bus topics will be registered when bus is created",
                manifest.domain_id,
            )

        runtime._safety_policies[manifest.domain_id] = self.get_safety_policy()

        # Track mounted domain
        if not hasattr(runtime, "_mounted_domains"):
            runtime._mounted_domains = {}
        runtime._mounted_domains[manifest.domain_id] = self

        logger.info(
            "Domain SDK mounted: %s (actors=%d, harness=%d, species_categories=%d)",
            manifest.domain_id,
            len(manifest.cognitive_actors),
            len(manifest.harness_functions),
            len(manifest.species_categories),
        )

    def __repr__(self) -> str:
        try:
            m = self.manifest()
            return f"<DomainSDK {m.domain_id} v{m.version}>"
        except Exception:
            return f"<DomainSDK {self.__class__.__name__}>"
