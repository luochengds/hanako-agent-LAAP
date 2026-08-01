"""LAAP FinQuant Domain SDK — CTP (Chinese futures) connector stub.

CTP is the dominant gateway for Chinese futures (SHFE, DCE, CZCE, CFFEX).
Tier 3 ultra-low-latency execution. Uses ``vnpy`` CTP gateway.

Optional dependency: ``vnpy_ctp``. **Phase 1 stub** — full implementation
deferred to Phase 2.
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

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.ctp")


class CTPConnector(FinancialConnector):
    """CTP Chinese futures execution connector (Phase 1 stub)."""

    tier = ConnectorTier.TIER_3_INSTITUTIONAL
    supported_markets = {MarketClassification.FUTURES}
    requires_credentials = True

    def __init__(self) -> None:
        self._connected = False

    @property
    def connector_id(self) -> str:
        return "ctp"

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
            "CTP live connector is Phase 2 (live trading). "
            "Use PaperTradingConnector for execution in Phase 1."
        )

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth.DISCONNECTED

    async def place_order(self, order: Order) -> OrderResult:
        return OrderResult(
            status=OrderStatus.REJECTED,
            reject_reason="ctp_not_implemented_in_phase_1",
        )
