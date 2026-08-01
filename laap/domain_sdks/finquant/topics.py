"""LAAP FinQuant Domain SDK — CognitiveBus topic namespace.

Defines the ``finquant.*`` topic namespace following LAAP's
``{domain}.{category}.{action}`` convention. These topics are the
message-routing keys used by the CognitiveBus to dispatch events
between FinQuant cognitive actors.

Topic map::

    finquant.market.stream          — Real-time market data perception events
    finquant.market.anomaly         — Anomaly detection alerts
    finquant.market.quote           — Single-quote snapshot requests/responses

    finquant.analysis.request       — Request quantitative analysis
    finquant.analysis.result        — Analysis results (indicators, factors)

    finquant.risk.assessment        — Periodic risk assessment
    finquant.risk.breach            — Risk limit breach (high priority)

    finquant.strategy.proposed      — Strategist proposes a strategy
    finquant.strategy.validated     — Backtest validation complete
    finquant.strategy.rejected      — Safety policy rejected strategy

    finquant.execution.order        — Order to be sent
    finquant.execution.fill         — Order fill confirmation
    finquant.execution.rejected     — Order rejected by platform or safety

    finquant.learning.pnl           — P&L feedback for PSI learning loop
    finquant.learning.attribution   — Strategy attribution analysis
"""

from __future__ import annotations

from typing import Dict, List

# ── Market data perception ─────────────────────────────────────────
MARKET_STREAM = "finquant.market.stream"
MARKET_ANOMALY = "finquant.market.anomaly"
MARKET_QUOTE = "finquant.market.quote"

# ── Quantitative analysis ──────────────────────────────────────────
ANALYSIS_REQUEST = "finquant.analysis.request"
ANALYSIS_RESULT = "finquant.analysis.result"

# ── Risk assessment ────────────────────────────────────────────────
RISK_ASSESSMENT = "finquant.risk.assessment"
RISK_BREACH = "finquant.risk.breach"

# ── Strategy lifecycle ─────────────────────────────────────────────
STRATEGY_PROPOSED = "finquant.strategy.proposed"
STRATEGY_VALIDATED = "finquant.strategy.validated"
STRATEGY_REJECTED = "finquant.strategy.rejected"

# ── Execution ──────────────────────────────────────────────────────
EXECUTION_ORDER = "finquant.execution.order"
EXECUTION_FILL = "finquant.execution.fill"
EXECUTION_REJECTED = "finquant.execution.rejected"

# ── Learning (PSI feedback) ────────────────────────────────────────
LEARNING_PNL = "finquant.learning.pnl"
LEARNING_ATTRIBUTION = "finquant.learning.attribution"


# ── Grouped topic sets for convenient subscription ────────────────

MARKET_TOPICS: List[str] = [MARKET_STREAM, MARKET_ANOMALY, MARKET_QUOTE]
ANALYSIS_TOPICS: List[str] = [ANALYSIS_REQUEST, ANALYSIS_RESULT]
RISK_TOPICS: List[str] = [RISK_ASSESSMENT, RISK_BREACH]
STRATEGY_TOPICS: List[str] = [
    STRATEGY_PROPOSED,
    STRATEGY_VALIDATED,
    STRATEGY_REJECTED,
]
EXECUTION_TOPICS: List[str] = [
    EXECUTION_ORDER,
    EXECUTION_FILL,
    EXECUTION_REJECTED,
]
LEARNING_TOPICS: List[str] = [LEARNING_PNL, LEARNING_ATTRIBUTION]

# All registered FinQuant topics, used by FinQuantDomainSDK.register_bus_topics()
ALL_TOPICS: List[str] = (
    MARKET_TOPICS
    + ANALYSIS_TOPICS
    + RISK_TOPICS
    + STRATEGY_TOPICS
    + EXECUTION_TOPICS
    + LEARNING_TOPICS
)

# Topic → human description (for CLI listing, docs generation)
TOPIC_DESCRIPTIONS: Dict[str, str] = {
    MARKET_STREAM: "Real-time market data perception events",
    MARKET_ANOMALY: "Anomaly detection alerts",
    MARKET_QUOTE: "Single-quote snapshot requests/responses",
    ANALYSIS_REQUEST: "Request quantitative analysis",
    ANALYSIS_RESULT: "Analysis results (indicators, factors)",
    RISK_ASSESSMENT: "Periodic risk assessment",
    RISK_BREACH: "Risk limit breach (high priority)",
    STRATEGY_PROPOSED: "Strategist proposes a strategy",
    STRATEGY_VALIDATED: "Backtest validation complete",
    STRATEGY_REJECTED: "Safety policy rejected strategy",
    EXECUTION_ORDER: "Order to be sent",
    EXECUTION_FILL: "Order fill confirmation",
    EXECUTION_REJECTED: "Order rejected by platform or safety",
    LEARNING_PNL: "P&L feedback for PSI learning loop",
    LEARNING_ATTRIBUTION: "Strategy attribution analysis",
}


def topic_categories() -> Dict[str, List[str]]:
    """Return topics grouped by category for documentation / CLI output."""
    return {
        "market": MARKET_TOPICS,
        "analysis": ANALYSIS_TOPICS,
        "risk": RISK_TOPICS,
        "strategy": STRATEGY_TOPICS,
        "execution": EXECUTION_TOPICS,
        "learning": LEARNING_TOPICS,
    }
