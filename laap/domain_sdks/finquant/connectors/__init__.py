"""LAAP FinQuant Domain SDK — Connectors package.

Public API for the connectors subpackage. Re-exports the base classes,
data types, the PaperTradingConnector, and the connector registry.

Concrete live connectors (Yahoo, AkShare, Binance, Tushare, IBKR, CTP)
are not imported eagerly — they lazy-load their optional dependencies
on ``connect()``. Import them explicitly when needed::

    from laap.domain_sdks.finquant.connectors.yahoo import YahooFinanceConnector
"""

from __future__ import annotations

from laap.domain_sdks.finquant.connectors.base import (
    ConnectorCapability,
    ConnectorHealth,
    ConnectorTier,
    FinancialConnector,
    MarketClassification,
    OHLCVBar,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Tick,
)
from laap.domain_sdks.finquant.connectors.paper import PaperTradingConnector
from laap.domain_sdks.finquant.connectors.registry import (
    ConnectorRegistry,
    get_connector_registry,
    reset_global_registry,
    resolve_connector,
)

__all__ = [
    # Base
    "FinancialConnector",
    "ConnectorCapability",
    "ConnectorHealth",
    "ConnectorTier",
    "MarketClassification",
    # Data types
    "Tick",
    "OHLCVBar",
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Position",
    "Portfolio",
    # Concrete
    "PaperTradingConnector",
    # Registry
    "ConnectorRegistry",
    "get_connector_registry",
    "reset_global_registry",
    "resolve_connector",
]
