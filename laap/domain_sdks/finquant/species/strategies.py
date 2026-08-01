"""LAAP FinQuant Domain SDK — Strategy species templates.

Precompiled reasoning patterns for trading strategies. Each template
encapsulates a parameterized async ``execute(ctx, data)`` function that
relies on zero-token harness functions for all numeric computation.

Templates defined:

- ``finquant.strategy.momentum_cross``  — Moving average crossover (momentum)
- ``finquant.strategy.mean_reversion``  — Bollinger band mean reversion
- ``finquant.strategy.pairs_trade``     — Cointegration pairs trading
- ``finquant.strategy.factor_tilt``     — Factor-based portfolio tilting
"""

from __future__ import annotations

import logging
from typing import List

from laap.domain_sdk.species import SpeciesTemplate

logger = logging.getLogger("laap.domain_sdks.finquant.species.strategies")


# ── 1. Moving Average Crossover (Momentum) ────────────────────────

_MOMENTUM_CROSS_CODE = '''async def execute(ctx, data):
    # Compute fast & slow SMA via harness (zero-token)
    fast_sma = await ctx.harness("finquant.indicators.compute", data=data, indicators=[{"name": "sma", "period": {{fast_period}}}])
    slow_sma = await ctx.harness("finquant.indicators.compute", data=data, indicators=[{"name": "sma", "period": {{slow_period}}}])
    regime = await ctx.harness("finquant.indicators.detect_regime", data=data)
    if regime["regime"] != "trending":
        return {"action": "flat", "reason": "regime_not_trending"}
    fast_vals = fast_sma["indicators"]["sma"]
    slow_vals = slow_sma["indicators"]["sma"]
    if len(fast_vals) < 2 or len(slow_vals) < 2:
        return {"action": "hold"}
    if fast_vals[-1] > slow_vals[-1] and fast_vals[-2] <= slow_vals[-2]:
        return {"action": "long", "symbol": data[-1].get("symbol", ""), "size": "kelly"}
    if fast_vals[-1] < slow_vals[-1] and fast_vals[-2] >= slow_vals[-2]:
        return {"action": "short", "symbol": data[-1].get("symbol", ""), "size": "kelly"}
    return {"action": "hold"}
'''


momentum_cross = SpeciesTemplate(
    id="finquant.strategy.momentum_cross",
    name="Moving Average Crossover (Momentum)",
    category="strategy",
    description=(
        "Classic fast/slow simple-moving-average crossover strategy gated "
        "by a regime filter. Goes long when the fast SMA crosses above the "
        "slow SMA and short on the opposite cross, but only when the "
        "regime detector classifies the market as trending. Otherwise "
        "flattens the position to avoid whipsaw in choppy markets."
    ),
    template_code=_MOMENTUM_CROSS_CODE,
    parameters={
        "fast_period": {
            "type": "int",
            "default": 20,
            "range": [5, 100],
            "description": "Fast SMA lookback period in bars.",
        },
        "slow_period": {
            "type": "int",
            "default": 50,
            "range": [20, 250],
            "description": "Slow SMA lookback period in bars.",
        },
    },
    execution_harness=[
        "finquant.indicators.compute",
        "finquant.indicators.detect_regime",
    ],
    species_version="1.0.0",
    tags=["momentum", "trend", "ma crossover"],
)


# ── 2. Bollinger Band Mean Reversion ──────────────────────────────

_MEAN_REVERSION_CODE = '''async def execute(ctx, data):
    # Compute Bollinger Bands via harness (zero-token)
    bbands = await ctx.harness(
        "finquant.indicators.compute",
        data=data,
        indicators=[{"name": "bbands", "period": {{bbands_period}}, "num_std": {{num_std}}}],
    )
    regime = await ctx.harness("finquant.indicators.detect_regime", data=data)
    if regime["regime"] == "trending":
        return {"action": "flat", "reason": "regime_trending_skip_mean_reversion"}
    bands = bbands["indicators"].get("bbands", [])
    if not bands or len(bands) < 1:
        return {"action": "hold"}
    last = bands[-1]
    upper = last.get("upper", 0.0)
    lower = last.get("lower", 0.0)
    mid = last.get("middle", 0.0)
    price = data[-1].get("close", 0.0) if data else 0.0
    symbol = data[-1].get("symbol", "") if data else ""
    if price < lower:
        return {"action": "long", "symbol": symbol, "size": "kelly", "reason": "price_below_lower_band"}
    if price > upper:
        return {"action": "short", "symbol": symbol, "size": "kelly", "reason": "price_above_upper_band"}
    return {"action": "hold", "symbol": symbol, "reason": "price_within_bands"}
'''


mean_reversion = SpeciesTemplate(
    id="finquant.strategy.mean_reversion",
    name="Bollinger Band Mean Reversion",
    category="strategy",
    description=(
        "Mean-reversion strategy using Bollinger Bands. Goes long when "
        "price closes below the lower band and short when it closes above "
        "the upper band, expecting reversion to the mean. Skips trending "
        "regimes where mean reversion typically fails."
    ),
    template_code=_MEAN_REVERSION_CODE,
    parameters={
        "bbands_period": {
            "type": "int",
            "default": 20,
            "range": [10, 50],
            "description": "Bollinger Band lookback period in bars.",
        },
        "num_std": {
            "type": "float",
            "default": 2.0,
            "range": [1.0, 3.0],
            "description": "Number of standard deviations for the bands.",
        },
    },
    execution_harness=[
        "finquant.indicators.compute",
        "finquant.indicators.detect_regime",
    ],
    species_version="1.0.0",
    tags=["mean reversion", "bollinger", "contrarian"],
)


# ── 3. Cointegration Pairs Trading ────────────────────────────────

_PAIRS_TRADE_CODE = '''async def execute(ctx, data):
    # Run cointegration test on the spread via harness (zero-token)
    legs = data.get("legs") if isinstance(data, dict) else None
    if legs is None and isinstance(data, list):
        legs = data
    coint = await ctx.harness("finquant.factors.cointegration", series_y=legs[0], series_x=legs[1])
    if not coint.get("cointegrated", False):
        return {"action": "flat", "reason": "not_cointegrated"}
    spread = coint.get("residuals", [])
    if len(spread) < 2:
        return {"action": "hold"}
    mean_spread = sum(spread) / len(spread)
    std_spread = (sum((v - mean_spread) ** 2 for v in spread) / max(len(spread) - 1, 1)) ** 0.5
    if std_spread <= 0:
        return {"action": "hold"}
    zscore = (spread[-1] - mean_spread) / std_spread
    symbols = data.get("symbols", ["", ""]) if isinstance(data, dict) else ["", ""]
    if zscore > {{entry_z}}:
        return {"action": "short_spread", "symbols": symbols, "zscore": zscore, "size": "kelly"}
    if zscore < -{{entry_z}}:
        return {"action": "long_spread", "symbols": symbols, "zscore": zscore, "size": "kelly"}
    if abs(zscore) < {{exit_z}}:
        return {"action": "flatten", "symbols": symbols, "zscore": zscore, "reason": "spread_normalized"}
    return {"action": "hold", "zscore": zscore}
'''


pairs_trade = SpeciesTemplate(
    id="finquant.strategy.pairs_trade",
    name="Cointegration Pairs Trading",
    category="strategy",
    description=(
        "Statistical arbitrage between two cointegrated instruments. Runs "
        "an Engle-Granger cointegration test, computes the z-score of the "
        "spread residual, goes long/short the spread when |z| exceeds the "
        "entry threshold, and flattens when the spread normalizes below "
        "the exit threshold."
    ),
    template_code=_PAIRS_TRADE_CODE,
    parameters={
        "entry_z": {
            "type": "float",
            "default": 2.0,
            "range": [1.0, 3.5],
            "description": "Z-score magnitude required to enter a spread trade.",
        },
        "exit_z": {
            "type": "float",
            "default": 0.5,
            "range": [0.0, 2.0],
            "description": "Z-score magnitude below which the spread is flattened.",
        },
    },
    execution_harness=["finquant.factors.cointegration"],
    species_version="1.0.0",
    tags=["pairs trading", "statistical arbitrage", "cointegration"],
)


# ── 4. Factor-Based Portfolio Tilting ─────────────────────────────

_FACTOR_TILT_CODE = '''async def execute(ctx, data):
    # Run Fama-French regression to obtain factor betas via harness (zero-token)
    portfolio = data.get("portfolio", {}) if isinstance(data, dict) else {}
    returns = portfolio.get("returns", [])
    factor_data = portfolio.get("factor_data", {})
    target = "{{target_factor}}"
    ff = await ctx.harness(
        "finquant.factors.fama_french",
        asset_returns=returns,
        factor_data=factor_data,
    )
    betas = ff.get("betas", {})
    holdings = portfolio.get("holdings", [])
    if not holdings:
        return {"action": "hold", "reason": "no_holdings"}
    target_beta = betas.get(target, 0.0)
    tilt = {{tilt_strength}}
    # Tilt weights toward high-target-factor stocks, away from low.
    scored = []
    for h in holdings:
        sym = h.get("symbol", "")
        w = float(h.get("weight", 0.0))
        b = float(h.get("betas", {}).get(target, 0.0))
        scored.append((sym, w, b))
    total_score = sum(b for _, _, b in scored) or 1.0
    new_weights = {}
    for sym, w, b in scored:
        adj = w * (1.0 + tilt * (b / total_score if total_score else 0.0))
        new_weights[sym] = adj
    # Normalize weights to sum to 1.0
    wsum = sum(new_weights.values()) or 1.0
    new_weights = {s: w / wsum for s, w in new_weights.items()}
    return {
        "action": "rebalance",
        "target_factor": target,
        "betas": betas,
        "new_weights": new_weights,
    }
'''


factor_tilt = SpeciesTemplate(
    id="finquant.strategy.factor_tilt",
    name="Factor-Based Portfolio Tilting",
    category="strategy",
    description=(
        "Portfolio rebalancing strategy that tilts weights toward "
        "instruments with high exposure to a target factor. Runs a "
        "Fama-French regression to estimate factor betas, then scales "
        "each holding's weight in proportion to its target-factor beta."
    ),
    template_code=_FACTOR_TILT_CODE,
    parameters={
        "target_factor": {
            "type": "str",
            "default": "momentum",
            "enum": ["momentum", "value", "quality", "low_vol"],
            "description": "Factor to tilt the portfolio toward.",
        },
        "tilt_strength": {
            "type": "float",
            "default": 0.05,
            "range": [0.01, 0.30],
            "description": "Strength of the tilt applied to base weights.",
        },
    },
    execution_harness=["finquant.factors.fama_french"],
    species_version="1.0.0",
    tags=["factor investing", "portfolio", "tilt", "fama french"],
)


# ── Aggregate export ──────────────────────────────────────────────

STRATEGY_TEMPLATES: List[SpeciesTemplate] = [
    momentum_cross,
    mean_reversion,
    pairs_trade,
    factor_tilt,
]

__all__ = [
    "STRATEGY_TEMPLATES",
    "momentum_cross",
    "mean_reversion",
    "pairs_trade",
    "factor_tilt",
]
