"""LAAP FinQuant Domain SDK — Cognitive species templates subpackage.

Aggregates all FinQuant species templates (strategies, analyses, risk
models) and provides a single registration entry point for the domain
SDK bootstrap.

Public API::

    from laap.domain_sdks.finquant.species import (
        ALL_SPECIES_TEMPLATES,
        SPECIES_CATEGORIES,
        register_all,
    )

    library = SpeciesLibrary()
    register_all(library)

Template count: 9 (4 strategies + 3 analyses + 2 risk models).
"""

from __future__ import annotations

import logging
from typing import Dict, List

from laap.domain_sdk.species import SpeciesLibrary, SpeciesTemplate
from laap.domain_sdks.finquant.species.analyses import ANALYSIS_TEMPLATES
from laap.domain_sdks.finquant.species.risk_models import RISK_MODEL_TEMPLATES
from laap.domain_sdks.finquant.species.strategies import STRATEGY_TEMPLATES

logger = logging.getLogger("laap.domain_sdks.finquant.species")


# ── Combined registry ─────────────────────────────────────────────

ALL_SPECIES_TEMPLATES: List[SpeciesTemplate] = (
    STRATEGY_TEMPLATES + ANALYSIS_TEMPLATES + RISK_MODEL_TEMPLATES
)


# ── Category → template id map ────────────────────────────────────

SPECIES_CATEGORIES: Dict[str, List[str]] = {}
for _t in ALL_SPECIES_TEMPLATES:
    SPECIES_CATEGORIES.setdefault(_t.category, []).append(_t.id)


def register_all(library: SpeciesLibrary) -> int:
    """Register every FinQuant species template into *library*.

    Args:
        library: A :class:`laap.domain_sdk.species.SpeciesLibrary`.

    Returns:
        Number of newly registered templates (duplicates are skipped).
    """
    count = 0
    for template in ALL_SPECIES_TEMPLATES:
        try:
            if library.register(template):
                count += 1
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "Failed to register species template %s: %s", template.id, exc
            )
    logger.info(
        "Registered %d/%d FinQuant species templates", count, len(ALL_SPECIES_TEMPLATES)
    )
    return count


__all__ = [
    # Aggregates
    "ALL_SPECIES_TEMPLATES",
    "SPECIES_CATEGORIES",
    "register_all",
    # Sub-module template lists
    "STRATEGY_TEMPLATES",
    "ANALYSIS_TEMPLATES",
    "RISK_MODEL_TEMPLATES",
    # Re-exports for convenience
    "SpeciesTemplate",
    "SpeciesLibrary",
]
