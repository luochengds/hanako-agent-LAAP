"""LAAP FinQuant Domain SDK — Analysis species templates.

Precompiled reasoning patterns for quantitative analysis tasks.
Each template encapsulates a parameterized async ``execute(ctx, data)``
function that relies on zero-token harness functions for computation.

Templates defined:

- ``finquant.analysis.regime_detect``       — Market regime detection
- ``finquant.analysis.risk_decompose``      — Portfolio risk decomposition
- ``finquant.analysis.factor_attribution``  — Strategy factor attribution
"""

from __future__ import annotations

import logging
from typing import List

from laap.domain_sdk.species import SpeciesTemplate

logger = logging.getLogger("laap.domain_sdks.finquant.species.analyses")


# ── 1. Market Regime Detection ───────────────────────────────────

_REGIME_DETECT_CODE = '''async def execute(ctx, data):
    # Detect market regime via harness (zero-token)
    regime = await ctx.harness("finquant.indicators.detect_regime", data=data)
    return {
        "analysis": "regime_detect",
        "regime": regime.get("regime", "unknown"),
        "confidence": regime.get("confidence", 0.0),
        "change_pct": regime.get("change_pct", 0.0),
        "volatility": regime.get("volatility", 0.0),
    }
'''


regime_detect = SpeciesTemplate(
    id="finquant.analysis.regime_detect",
    name="Market Regime Detection",
    category="analysis",
    description=(
        "Classifies the prevailing market regime (trending, volatile, "
        "quiet, or mean_reverting) over the trailing window using the "
        "regime detector harness. Used to gate strategy selection and "
        "risk posture."
    ),
    template_code=_REGIME_DETECT_CODE,
    parameters={},
    execution_harness=["finquant.indicators.detect_regime"],
    species_version="1.0.0",
    tags=["regime", "analysis", "market structure"],
)


# ── 2. Portfolio Risk Decomposition ───────────────────────────────

_RISK_DECOMPOSE_CODE = '''async def execute(ctx, data):
    # Decompose portfolio risk via VaR harness (zero-token)
    portfolio = data.get("portfolio", data) if isinstance(data, dict) else data
    method = "{{method}}"
    var_result = await ctx.harness(
        "finquant.risk.var",
        returns=portfolio.get("returns", []),
        confidence=portfolio.get("confidence", 0.95),
        method=method,
    )
    return {
        "analysis": "risk_decompose",
        "method": method,
        "var": var_result.get("var", 0.0),
        "cvar": var_result.get("cvar", 0.0),
        "horizon": var_result.get("horizon", 1),
        "components": var_result.get("components", {}),
    }
'''


risk_decompose = SpeciesTemplate(
    id="finquant.analysis.risk_decompose",
    name="Portfolio Risk Decomposition",
    category="analysis",
    description=(
        "Decomposes portfolio risk by computing Value-at-Risk and "
        "Conditional VaR via the selected method (historical, parametric, "
        "or Monte Carlo). Returns the aggregate risk figure plus any "
        "component-level breakdown the harness provides."
    ),
    template_code=_RISK_DECOMPOSE_CODE,
    parameters={
        "method": {
            "type": "str",
            "default": "historical",
            "enum": ["historical", "parametric", "monte_carlo"],
            "description": "VaR computation method.",
        },
    },
    execution_harness=["finquant.risk.var"],
    species_version="1.0.0",
    tags=["risk", "var", "decomposition", "analysis"],
)


# ── 3. Strategy Factor Attribution ────────────────────────────────

_FACTOR_ATTRIBUTION_CODE = '''async def execute(ctx, data):
    # Attribute strategy P&L to factors via Fama-French regression (zero-token)
    portfolio = data.get("portfolio", data) if isinstance(data, dict) else data
    strategy_returns = portfolio.get("returns", [])
    factor_data = portfolio.get("factor_data", {})
    ff = await ctx.harness(
        "finquant.factors.fama_french",
        asset_returns=strategy_returns,
        factor_data=factor_data,
    )
    return {
        "analysis": "factor_attribution",
        "alpha": ff.get("alpha", 0.0),
        "betas": ff.get("betas", {}),
        "r_squared": ff.get("r_squared", 0.0),
        "factor_contributions": ff.get("factor_contributions", {}),
    }
'''


factor_attribution = SpeciesTemplate(
    id="finquant.analysis.factor_attribution",
    name="Strategy Factor Attribution",
    category="analysis",
    description=(
        "Attributes strategy P&L to common risk factors by regressing "
        "strategy returns against a Fama-French factor model. Reports "
        "alpha, factor betas, R-squared, and per-factor contribution."
    ),
    template_code=_FACTOR_ATTRIBUTION_CODE,
    parameters={},
    execution_harness=["finquant.factors.fama_french"],
    species_version="1.0.0",
    tags=["attribution", "fama french", "analysis"],
)


# ── Aggregate export ──────────────────────────────────────────────

ANALYSIS_TEMPLATES: List[SpeciesTemplate] = [
    regime_detect,
    risk_decompose,
    factor_attribution,
]

__all__ = [
    "ANALYSIS_TEMPLATES",
    "regime_detect",
    "risk_decompose",
    "factor_attribution",
]
