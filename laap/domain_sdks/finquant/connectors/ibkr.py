"""LAAP FinQuant Domain SDK — Interactive Brokers (IBKR) connector stub.

IBKR TWS API provides multi-asset global execution (stocks, options,
futures, forex). Tier 2 execution-grade.

Optional dependency: ``ib_insync``. Requires TWS or IB Gateway running
locally. **Phase 1 stub**: full implementation deferred to Phase 2
(live trading).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.domain_sdks.finquant.connectors.base import (
    ConnectorCapability,
    ConnectorHealth,
    ConnectorTier,
    FinancialConnector,
    MarketClassification,
    Order,
    OrderResult,
    OrderStatus,
)

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.ibkr")


class IBKRConnector(FinancialConnector):
    """Interactive Brokers connector (Phase 1 stub).

    Real implementation (Phase 2) will use ``ib_insync`` to connect
    to TWS / IB Gateway. This stub advertises capabilities so the
    connector registry knows it exists, but ``connect()`` raises
    NotImplementedError until Phase 2.
    """

    tier = ConnectorTier.TIER_2_EXECUTION
    supported_markets = {
        MarketClassification.US,
        MarketClassification.EU,
        MarketClassification.HK,
        MarketClassification.FUTURES,
        MarketClassification.FOREX,
    }
    requires_credentials = True

    def __init__(self) -> None:
        self._connected = False

    @property
    def connector_id(self) -> str:
        return "ibkr"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.MARKET_DATA,
            ConnectorCapability.HISTORICAL_DATA,
            ConnectorCapability.ORDER_EXECUTION,
            ConnectorCapability.PORTFOLIO_QUERY,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError(
            "IBKR live connector is Phase 2 (live trading). "
            "Use PaperTradingConnector for execution in Phase 1."
        )

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth.DISCONNECTED

    async def place_order(self, order: Order) -> OrderResult:
        return OrderResult(
            status=OrderStatus.REJECTED,
            reject_reason="ibkr_not_implemented_in_phase_1",
        )
