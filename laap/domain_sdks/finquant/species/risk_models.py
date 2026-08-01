"""LAAP FinQuant Domain SDK — Risk model species templates.

Precompiled reasoning patterns for continuous risk monitoring and
position sizing. Each template encapsulates a parameterized async
``execute(ctx, data)`` function that relies on zero-token harness
functions for computation.

Templates defined:

- ``finquant.risk_model.var_monitor``   — VaR monitoring model
- ``finquant.risk_model.kelly_sizing``  — Kelly criterion position sizing
"""

from __future__ import annotations

import logging
from typing import List

from laap.domain_sdk.species import SpeciesTemplate

logger = logging.getLogger("laap.domain_sdks.finquant.species.risk_models")


# ── 1. VaR Monitoring Model ───────────────────────────────────────

_VAR_MONITOR_CODE = '''async def execute(ctx, data):
    # Continuous VaR / CVaR monitoring via harness (zero-token)
    portfolio = data.get("portfolio", data) if isinstance(data, dict) else data
    returns = portfolio.get("returns", [])
    var_result = await ctx.harness(
        "finquant.risk.var",
        returns=returns,
        confidence={{confidence}},
        horizon={{horizon}},
        method="historical",
    )
    var = var_result.get("var", 0.0)
    cvar = var_result.get("cvar", 0.0)
    status = "ok"
    if abs(cvar) > abs(var) * 1.5:
        status = "tail_risk_elevated"
    return {
        "model": "var_monitor",
        "confidence": {{confidence}},
        "horizon": {{horizon}},
        "var": var,
        "cvar": cvar,
        "status": status,
    }
'''


var_monitor = SpeciesTemplate(
    id="finquant.risk_model.var_monitor",
    name="VaR Monitoring Model",
    category="risk_model",
    description=(
        "Continuous risk monitoring model that recomputes Value-at-Risk "
        "and Conditional VaR at a configurable confidence level and "
        "horizon. Flags elevated tail risk when CVaR materially exceeds "
        "VaR."
    ),
    template_code=_VAR_MONITOR_CODE,
    parameters={
        "confidence": {
            "type": "float",
            "default": 0.95,
            "range": [0.90, 0.99],
            "description": "VaR confidence level (e.g. 0.95 = 95%).",
        },
        "horizon": {
            "type": "int",
            "default": 1,
            "range": [1, 10],
            "description": "Risk horizon in periods.",
        },
    },
    execution_harness=["finquant.risk.var"],
    species_version="1.0.0",
    tags=["risk model", "var", "monitoring", "cvar"],
)


# ── 2. Kelly Criterion Position Sizing ────────────────────────────

_KELLY_SIZING_CODE = '''async def execute(ctx, data):
    # Kelly criterion position sizing via harness (zero-token)
    payload = data.get("signal", data) if isinstance(data, dict) else data
    win_rate = float(payload.get("win_rate", 0.0))
    win_loss_ratio = float(payload.get("win_loss_ratio", 0.0))
    kelly = await ctx.harness(
        "finquant.risk.kelly_criterion",
        win_rate=win_rate,
        win_loss_ratio=win_loss_ratio,
        fraction={{fraction}},
    )
    return {
        "model": "kelly_sizing",
        "fraction": {{fraction}},
        "full_kelly": kelly.get("full_kelly", 0.0),
        "fractional_kelly": kelly.get("fractional_kelly", 0.0),
        "recommended_size": kelly.get("fractional_kelly", 0.0),
    }
'''


kelly_sizing = SpeciesTemplate(
    id="finquant.risk_model.kelly_sizing",
    name="Kelly Criterion Position Sizing",
    category="risk_model",
    description=(
        "Position-sizing model using the Kelly criterion. Computes the "
        "full-Kelly fraction and a safer fractional-Kelly size from the "
        "strategy's win rate and win/loss ratio. Fractional Kelly is "
        "used by default to reduce variance and drawdown."
    ),
    template_code=_KELLY_SIZING_CODE,
    parameters={
        "fraction": {
            "type": "float",
            "default": 0.5,
            "range": [0.1, 1.0],
            "description": "fractional Kelly for safety (0.5 = half Kelly).",
        },
    },
    execution_harness=["finquant.risk.kelly_criterion"],
    species_version="1.0.0",
    tags=["risk model", "kelly", "position sizing"],
)


# ── Aggregate export ──────────────────────────────────────────────

RISK_MODEL_TEMPLATES: List[SpeciesTemplate] = [
    var_monitor,
    kelly_sizing,
]

__all__ = [
    "RISK_MODEL_TEMPLATES",
    "var_monitor",
    "kelly_sizing",
]
