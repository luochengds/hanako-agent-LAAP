"""LAAP FinQuant Domain SDK — LLM tool schemas (OpenAI function-calling format).

Defines the 15 tools the financial agent can call. Each schema mirrors
an underlying capability: zero-token harness functions, cognitive-actor
delegation, connector queries, or platform introspection.

The schemas are deliberately strict (typed, with enums where applicable)
so the LLM produces well-formed arguments on the first try — critical
for voice mode where a re-prompt round costs seconds of latency.
"""

from __future__ import annotations

from typing import Any, Dict, List

# OpenAI-style tool schemas. Each entry is {"type":"function","function":{...}}.
TOOL_SCHEMAS: List[Dict[str, Any]] = [
    # ── Market data ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": (
                "Fetch OHLCV historical bars for a symbol. Use this to pull "
                "raw price data before computing indicators or running a "
                "backtest. Routes to the active connector."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "e.g. 'AAPL', '000001.SZ', 'BTCUSDT'"},
                    "interval": {
                        "type": "string",
                        "enum": ["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
                        "description": "Bar interval; default '1d'",
                    },
                    "limit": {"type": "integer", "description": "Number of bars (default 100, max 1000)"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Get a real-time quote snapshot for a symbol (last price, bid/ask).",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    # ── Indicators / analysis ──────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "compute_indicators",
            "description": (
                "Compute technical indicators (SMA, EMA, RSI, MACD, Bollinger, "
                "ATR, etc.) over OHLCV data. Zero-token harness function. "
                "Pass the bars you fetched with get_market_data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "description": "OHLCV bars [{open,high,low,close,volume,timestamp}, ...]",
                        "items": {"type": "object"},
                    },
                    "indicators": {
                        "type": "array",
                        "description": "Indicators to compute",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "e.g. 'sma','ema','rsi','macd','bbands','atr'"},
                                "period": {"type": "integer"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["data", "indicators"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_regime",
            "description": "Detect the market regime (trending up/down, ranging, volatile) for OHLCV data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {"type": "array", "items": {"type": "object"}},
                    "window": {"type": "integer", "description": "Lookback window (default 20)"},
                },
                "required": ["data"],
            },
        },
    },
    # ── Risk ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "compute_var",
            "description": "Compute Value-at-Risk (VaR) and Conditional VaR (CVaR) from a return series.",
            "parameters": {
                "type": "object",
                "properties": {
                    "returns": {"type": "array", "items": {"type": "number"}, "description": "Periodic returns"},
                    "confidence": {"type": "number", "description": "e.g. 0.95 or 0.99 (default 0.95)"},
                },
                "required": ["returns"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stress_test",
            "description": "Run a stress test on the current portfolio (e.g. -10% market shock, 2008 replay).",
            "parameters": {
                "type": "object",
                "properties": {
                    "positions": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Current positions [{symbol,size,avg_price}, ...]",
                    },
                    "scenario": {
                        "type": "string",
                        "enum": ["market_crash", "flash_crash", "rates_up", "rates_down", "vol_spike", "custom"],
                        "description": "Stress scenario name",
                    },
                    "shock_pct": {"type": "number", "description": "For 'custom': per-position shock percentage"},
                },
                "required": ["positions", "scenario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kelly_criterion",
            "description": "Compute the Kelly-optimal fraction for a strategy given win probability and payoff ratio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "win_prob": {"type": "number", "description": "Win probability [0,1]"},
                    "win_loss_ratio": {"type": "number", "description": "Avg win / avg loss"},
                },
                "required": ["win_prob", "win_loss_ratio"],
            },
        },
    },
    # ── Statistics ─────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "compute_statistics",
            "description": "Compute performance statistics: Sharpe, Sortino, max drawdown, z-score test, ADF test.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["sharpe", "sortino", "max_drawdown", "zscore", "adf"],
                        "description": "Which statistic to compute",
                    },
                    "values": {"type": "array", "items": {"type": "number"}, "description": "Return series"},
                    "risk_free_rate": {"type": "number", "description": "Annualized risk-free rate (default 0.0)"},
                },
                "required": ["metric", "values"],
            },
        },
    },
    # ── Backtest ───────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": (
                "Run a full backtest of a strategy on historical data. "
                "Returns equity curve, trades, P&L, and risk metrics. "
                "Use this to validate a strategy before proposing live trading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "string",
                        "description": "Species template id, e.g. 'dual_ma_cross', 'mean_reversion', 'momentum'",
                    },
                    "symbol": {"type": "string"},
                    "data": {"type": "array", "items": {"type": "object"}, "description": "OHLCV bars"},
                    "params": {"type": "object", "description": "Strategy parameters (e.g. {fast:5, slow:20})"},
                    "initial_capital": {"type": "number", "description": "Default 100000"},
                    "commission_bps": {"type": "number", "description": "Commission in bps (default 5)"},
                },
                "required": ["strategy_id", "symbol", "data"],
            },
        },
    },
    # ── Strategy / species ─────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "list_strategies",
            "description": "List all available strategy/analysis/risk-model species templates registered in the SDK.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["strategy", "analysis", "risk_model", "all"],
                        "description": "Filter by category (default 'all')",
                    },
                },
            },
        },
    },
    # ── Portfolio / execution ──────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "Get the current portfolio: cash, equity, P&L, and open positions (live from connector).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": (
                "Place an order through the Executor actor. The hard safety "
                "policy gate runs FIRST and cannot be bypassed — orders that "
                "violate position/drawdown/leverage limits are rejected. "
                "Defaults to paper trading; live requires explicit mode."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "size": {"type": "number", "description": "Quantity (positive number)"},
                    "order_type": {"type": "string", "enum": ["market", "limit", "stop", "stop_limit"]},
                    "limit_price": {"type": "number", "description": "Required for limit/stop_limit"},
                    "stop_price": {"type": "number", "description": "Required for stop/stop_limit"},
                    "time_in_force": {"type": "string", "description": "day/gtc/ioc/fok (default day)"},
                },
                "required": ["symbol", "side", "size"],
            },
        },
    },
    # ── Platform introspection ─────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_platform_state",
            "description": (
                "Get a live snapshot of the FinQuant platform: spawned actors, "
                "registered harness functions, species templates, connector "
                "health, safety-policy limits, recent CognitiveBus events. "
                "Use this before answering questions about platform internals."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": (
                "Speak text aloud via TTS (voice mode). Use for spoken "
                "intermediate status in long-running tasks, or when the user "
                "is on a voice channel. In text mode this is a no-op."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to speak (concise, natural)"},
                    "interrupt": {"type": "boolean", "description": "Interrupt any current speech (default true)"},
                },
                "required": ["text"],
            },
        },
    },
    # ── Memory (lightweight, in-process) ───────────────────────────
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Recall a prior analysis / decision from the agent's conversation memory by keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword or phrase to search"},
                },
                "required": ["query"],
            },
        },
    },
]

# Quick lookup: name → schema
TOOL_SCHEMA_BY_NAME: Dict[str, Dict[str, Any]] = {
    s["function"]["name"]: s for s in TOOL_SCHEMAS
}

ALL_TOOL_NAMES: List[str] = list(TOOL_SCHEMA_BY_NAME.keys())


def get_schemas(names: List[str]) -> List[Dict[str, Any]]:
    """Return the OpenAI-style schemas for the requested tool names."""
    return [TOOL_SCHEMA_BY_NAME[n] for n in names if n in TOOL_SCHEMA_BY_NAME]


__all__ = ["TOOL_SCHEMAS", "TOOL_SCHEMA_BY_NAME", "ALL_TOOL_NAMES", "get_schemas"]
