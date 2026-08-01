"""LAAP FinQuant Domain SDK — Financial Quantitative Digital Life Agent.

Phase 1 implementation of the Financial Quantitative Domain SDK. Mounts
into a ``LAAPRuntime`` to provide:

- **14 harness functions** (deterministic, zero-token): market data,
  technical indicators, risk metrics, factor models, statistics, backtest.
- **9 species templates** (4 strategies + 3 analyses + 2 risk models).
- **5 cognitive actors**: MarketWatcher, Analyst, RiskManager,
  Strategist, Executor — wired into LAAP's PSI cognitive loop.
- **15 CognitiveBus topics** in the ``finquant.*`` namespace.
- **FinQuantSafetyPolicy**: hard gates (position, drawdown, leverage,
  liquidity, rate limit, restricted symbols, paper-trade-first).
- **7 financial connectors**: PaperTrading (default), Yahoo, AkShare,
  Tushare, Binance, IBKR (stub), CTP (stub).

Quick start::

    from laap import LAAPRuntime
    from laap.domain_sdks.finquant import FinQuantDomainSDK

    runtime = LAAPRuntime()
    runtime.mount_domain(FinQuantDomainSDK())

    # Invoke a harness function (zero-token)
    result = await runtime.invoke_harness(
        "finquant.risk.kelly_criterion",
        win_prob=0.55, win_loss_ratio=1.5,
    )

    # List registered species templates
    templates = runtime.list_species_templates(domain="finquant")

Public API: see ``__all__`` below.
"""

from __future__ import annotations

from laap.domain_sdk.base import DomainManifest, DomainSDKBase

from laap.domain_sdks.finquant.sdk import FinQuantDomainSDK

# Re-export subpackage public APIs for convenient access
from laap.domain_sdks.finquant.connectors import (
    ConnectorCapability,
    ConnectorHealth,
    ConnectorRegistry,
    ConnectorTier,
    FinancialConnector,
    MarketClassification,
    OHLCVBar,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingConnector,
    Portfolio,
    Position,
    Tick,
    get_connector_registry,
    reset_global_registry,
    resolve_connector,
)
from laap.domain_sdks.finquant.harness import (
    HARNESS_FUNCTIONS,
    register_all as register_harness,
)
from laap.domain_sdks.finquant.safety.policy import (
    FinQuantOrder,
    FinQuantPortfolio,
    FinQuantSafetyPolicy,
)
from laap.domain_sdks.finquant.species import (
    ALL_SPECIES_TEMPLATES,
    SPECIES_CATEGORIES,
    register_all as register_species,
)
from laap.domain_sdks.finquant.topics import (
    ALL_TOPICS,
    TOPIC_DESCRIPTIONS,
    topic_categories,
)

# Financial agent (LLM-driven, opt-in). Import is defensive so the SDK
# still loads if the agent's optional dependencies (openai SDK, etc.)
# are missing.
try:
    from laap.domain_sdks.finquant.agent import (
        AgentConfig,
        FinQuantAgent,
        LLMConfig,
        PlatformIntrospector,
        PlatformSnapshot,
        VoiceConfig,
        VoiceInterface,
    )
    _AGENT_AVAILABLE = True
except Exception as _agent_import_exc:  # pragma: no cover - optional dep
    _AGENT_AVAILABLE = False
    AgentConfig = None  # type: ignore[assignment]
    FinQuantAgent = None  # type: ignore[assignment]
    LLMConfig = None  # type: ignore[assignment]
    PlatformIntrospector = None  # type: ignore[assignment]
    PlatformSnapshot = None  # type: ignore[assignment]
    VoiceConfig = None  # type: ignore[assignment]
    VoiceInterface = None  # type: ignore[assignment]

__version__ = "1.0.0"
__domain_id__ = "finquant"

__all__ = [
    # ── SDK entry point ──
    "FinQuantDomainSDK",
    # ── Connectors ──
    "FinancialConnector",
    "ConnectorCapability",
    "ConnectorHealth",
    "ConnectorTier",
    "ConnectorRegistry",
    "MarketClassification",
    "PaperTradingConnector",
    "get_connector_registry",
    "reset_global_registry",
    "resolve_connector",
    # ── Connector data types ──
    "Tick",
    "OHLCVBar",
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Position",
    "Portfolio",
    # ── Safety ──
    "FinQuantSafetyPolicy",
    "FinQuantOrder",
    "FinQuantPortfolio",
    # ── Harness ──
    "HARNESS_FUNCTIONS",
    "register_harness",
    # ── Species ──
    "ALL_SPECIES_TEMPLATES",
    "SPECIES_CATEGORIES",
    "register_species",
    # ── Topics ──
    "ALL_TOPICS",
    "TOPIC_DESCRIPTIONS",
    "topic_categories",
    # ── Financial agent (LLM-driven) ──
    "FinQuantAgent",
    "AgentConfig",
    "LLMConfig",
    "VoiceConfig",
    "VoiceInterface",
    "PlatformIntrospector",
    "PlatformSnapshot",
    # ── Metadata ──
    "__version__",
    "__domain_id__",
]
