"""LAAP FinQuant Domain SDK — Tushare Pro connector.

Tushare Pro is a paid CN-market data API (https://tushare.pro).
Tier 1: real-time CN equities, funds, bonds, futures. Requires token.

Optional dependency: ``tushare``. Requires API token.
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
    OHLCVBar,
)

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.tushare")


class TushareConnector(FinancialConnector):
    """Tushare Pro data connector — CN market real-time & historical."""

    tier = ConnectorTier.TIER_1_REALTIME
    supported_markets = {
        MarketClassification.CN,
        MarketClassification.FUTURES,
    }
    requires_credentials = True

    def __init__(self) -> None:
        self._connected = False
        self._api: Any = None
        self._token: str = ""

    @property
    def connector_id(self) -> str:
        return "tushare"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.HISTORICAL_DATA,
            ConnectorCapability.FUNDAMENTAL_DATA,
            ConnectorCapability.MARKET_DATA,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if not credentials or "token" not in credentials:
            raise ValueError("TushareConnector requires a token")
        try:
            import tushare as ts  # type: ignore
            ts.set_token(credentials["token"])
            self._token = credentials["token"]
            self._api = ts.pro_api()
            self._connected = True
            logger.info("TushareConnector connected")
        except ImportError as e:
            raise ImportError(
                "tushare is required for TushareConnector. "
                "Install with: pip install tushare"
            ) from e

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY if self._connected else ConnectorHealth.DISCONNECTED

    async def fetch_ohlcv(
        self,
        symbols: List[str],
        start: str,
        end: str,
        interval: str = "1d",
    ) -> Dict[str, List[OHLCVBar]]:
        if not self._connected or self._api is None:
            raise RuntimeError("TushareConnector not connected")
        out: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            try:
                # daily endpoint: ts_code, trade_date, open, high, low, close, vol
                df = self._api.daily(
                    ts_code=sym,
                    start_date=start.replace("-", ""),
                    end_date=end.replace("-", ""),
                )
                bars: List[OHLCVBar] = []
                for _, row in df.iterrows():
                    bars.append(
                        OHLCVBar(
                            timestamp=0.0,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["vol"]),
                            symbol=sym,
                        )
                    )
                out[sym] = bars
            except Exception as e:
                logger.warning("Tushare fetch failed for %s: %s", sym, e)
                out[sym] = []
        return out
