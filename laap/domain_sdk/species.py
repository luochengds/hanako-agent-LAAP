"""LAAP Domain SDK — Cognitive Species Library.

Species templates are precompiled reasoning patterns that enable zero-token
code generation for recurring domain tasks. Each template encapsulates a
parameterized code pattern that can be instantiated and executed without
LLM token consumption.

This extends LAAP's existing ``laap.species.code_templates`` pattern to
support domain-specific species with:
- Parameterized templates (Jinja2-style ``{{var}}`` placeholders)
- Versioning for template evolution
- Category-based organization
- Execution context with harness function access

Usage::

    from laap.domain_sdk import SpeciesTemplate, SpeciesLibrary

    library = SpeciesLibrary()

    template = SpeciesTemplate(
        id="finquant.strategy.momentum_cross",
        name="Moving Average Crossover",
        category="strategy",
        template_code="async def execute(ctx, data): ...",
        parameters={"fast_period": {"type": "int", "default": 20}},
    )

    library.register(template)
    instance = library.instantiate("finquant.strategy.momentum_cross",
                                    fast_period=30)
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.domain_sdk.species")


@dataclass
class SpeciesTemplate:
    """A precompiled reasoning pattern template.

    Attributes:
        id: Unique dotted ID following ``{domain}.{category}.{name}``.
        name: Human-readable name.
        category: Category for grouping (e.g. "strategy", "analysis").
        description: Detailed description.
        template_code: The code template with ``{{var}}`` placeholders.
        parameters: Parameter spec dict with type, default, range.
        domain: Domain ID extracted from ID prefix.
        species_version: Template version (independent of instances).
        author: Template author.
        tags: Searchable tags.
        created_at: Unix timestamp.
        execution_harness: List of harness function names this template calls.
    """

    id: str
    name: str = ""
    category: str = ""
    description: str = ""
    template_code: str = ""
    parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    domain: str = ""
    species_version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    execution_harness: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.domain:
            parts = self.id.split(".")
            if len(parts) >= 1:
                self.domain = parts[0]
        if not self.category:
            parts = self.id.split(".")
            if len(parts) >= 2:
                self.category = parts[1]
        if not self.name:
            self.name = self.id.rsplit(".", 1)[-1].replace("_", " ").title()

    def to_dict(self, include_code: bool = False) -> Dict[str, Any]:
        """Serialize to dict for listing / CLI output."""
        d = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description[:200] if self.description else "",
            "domain": self.domain,
            "species_version": self.species_version,
            "author": self.author,
            "tags": list(self.tags),
            "parameters": dict(self.parameters),
            "execution_harness": list(self.execution_harness),
        }
        if include_code:
            d["template_code"] = self.template_code
        return d

    def get_placeholders(self) -> List[str]:
        """Extract ``{{var}}`` placeholder names from template_code."""
        if not self.template_code:
            return []
        return list(set(re.findall(r"\{\{(\w+)\}\}", self.template_code)))

    def render(self, **params: Any) -> str:
        """Render the template code with provided parameters.

        Applies default values for unspecified parameters, then substitutes
        ``{{var}}`` placeholders with parameter values.

        Args:
            **params: Parameter values to substitute.

        Returns:
            Rendered code string.

        Raises:
            ValueError: If a required parameter (no default) is missing.
        """
        merged: Dict[str, Any] = {}

        # Apply defaults
        for pname, pspec in self.parameters.items():
            if "default" in pspec:
                merged[pname] = pspec["default"]

        # Override with provided values
        merged.update(params)

        # Check required parameters
        missing = []
        for pname, pspec in self.parameters.items():
            if pspec.get("required", False) and pname not in merged:
                missing.append(pname)
        if missing:
            raise ValueError(
                f"Species template '{self.id}' missing required parameters: {missing}"
            )

        # Substitute placeholders
        rendered = self.template_code
        for key, value in merged.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))

        return rendered

    def validate_params(self, **params: Any) -> List[str]:
        """Validate parameters against their specs.

        Returns:
            List of validation error messages (empty if all valid).
        """
        errors = []
        for pname, pspec in self.parameters.items():
            if pname not in params:
                if pspec.get("required", False) and "default" not in pspec:
                    errors.append(f"Missing required parameter: {pname}")
                continue

            value = params[pname]
            ptype = pspec.get("type", "any")
            type_map = {
                "int": int,
                "float": (int, float),
                "str": str,
                "bool": bool,
                "list": list,
                "dict": dict,
            }
            expected = type_map.get(ptype)
            if expected and not isinstance(value, expected):
                errors.append(
                    f"Parameter '{pname}' expected {ptype}, got {type(value).__name__}"
                )

            if "range" in pspec and isinstance(value, (int, float)):
                lo, hi = pspec["range"]
                if not (lo <= value <= hi):
                    errors.append(
                        f"Parameter '{pname}' value {value} out of range [{lo}, {hi}]"
                    )

            if "enum" in pspec and value not in pspec["enum"]:
                errors.append(
                    f"Parameter '{pname}' value '{value}' not in enum {pspec['enum']}"
                )

        return errors


@dataclass
class SpeciesInstance:
    """An instantiated species template ready for execution.

    Attributes:
        template_id: ID of the source template.
        rendered_code: The rendered code string.
        parameters: The parameters used for instantiation.
        domain: Domain ID.
    """

    template_id: str
    rendered_code: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    domain: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "parameters": dict(self.parameters),
            "domain": self.domain,
            "code_size": len(self.rendered_code),
        }


class SpeciesLibrary:
    """Registry for cognitive species templates.

    Thread-safe library supporting registration, instantiation, and
    domain-scoped queries. Each domain SDK registers its templates here
    during initialization.

    Usage::

        library = SpeciesLibrary()
        library.register(my_template)
        instance = library.instantiate("finquant.strategy.momentum_cross",
                                        fast_period=30)
    """

    def __init__(self) -> None:
        self._templates: Dict[str, SpeciesTemplate] = {}
        self._lock = threading.RLock()

    def register(self, template: SpeciesTemplate, overwrite: bool = False) -> bool:
        """Register a species template.

        Args:
            template: The SpeciesTemplate to register.
            overwrite: If True, overwrites an existing template with same ID.

        Returns:
            True if registered, False if skipped (already exists, no overwrite).
        """
        with self._lock:
            if template.id in self._templates and not overwrite:
                logger.debug("Species template already registered: %s", template.id)
                return False
            self._templates[template.id] = template
        logger.debug(
            "Registered species template: %s [%s/%s]",
            template.id, template.domain, template.category,
        )
        return True

    def register_many(self, templates: List[SpeciesTemplate]) -> int:
        """Register multiple templates. Returns count of newly registered."""
        count = 0
        for t in templates:
            if self.register(t):
                count += 1
        return count

    def get(self, template_id: str) -> Optional[SpeciesTemplate]:
        """Return the template with *template_id*, or None."""
        with self._lock:
            return self._templates.get(template_id)

    def list(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[SpeciesTemplate]:
        """List templates, optionally filtered by domain and/or category."""
        with self._lock:
            templates = list(self._templates.values())
        result = []
        for t in templates:
            if domain is not None and t.domain != domain:
                continue
            if category is not None and t.category != category:
                continue
            result.append(t)
        return result

    def list_ids(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[str]:
        """Return template IDs, optionally filtered."""
        return [t.id for t in self.list(domain=domain, category=category)]

    def instantiate(
        self,
        template_id: str,
        validate: bool = True,
        **params: Any,
    ) -> SpeciesInstance:
        """Instantiate a template with parameters.

        Args:
            template_id: The template to instantiate.
            validate: If True, validate parameters before rendering.
            **params: Parameter values.

        Returns:
            SpeciesInstance with rendered code.

        Raises:
            KeyError: If template not found.
            ValueError: If parameter validation fails.
        """
        with self._lock:
            template = self._templates.get(template_id)
        if template is None:
            raise KeyError(f"Species template '{template_id}' not found")

        if validate:
            errors = template.validate_params(**params)
            if errors:
                raise ValueError(
                    f"Parameter validation failed for '{template_id}':\n  - "
                    + "\n  - ".join(errors)
                )

        rendered = template.render(**params)
        return SpeciesInstance(
            template_id=template_id,
            rendered_code=rendered,
            parameters=params,
            domain=template.domain,
        )

    def unregister(self, template_id: str) -> bool:
        """Remove a template from the library."""
        with self._lock:
            if template_id in self._templates:
                del self._templates[template_id]
                return True
            return False

    def clear(self) -> None:
        """Remove all templates. For test isolation."""
        with self._lock:
            self._templates.clear()

    def __contains__(self, template_id: object) -> bool:
        if isinstance(template_id, str):
            with self._lock:
                return template_id in self._templates
        return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._templates)

    @property
    def count(self) -> int:
        return len(self)

    @property
    def domains(self) -> List[str]:
        """Return sorted list of domains with registered templates."""
        with self._lock:
            return sorted({t.domain for t in self._templates.values() if t.domain})

    @property
    def categories(self) -> List[str]:
        """Return sorted list of all categories."""
        with self._lock:
            return sorted({t.category for t in self._templates.values() if t.category})
