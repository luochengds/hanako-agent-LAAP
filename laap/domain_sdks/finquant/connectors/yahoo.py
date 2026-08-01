"""LAAP FinQuant Domain SDK — Yahoo Finance connector.

Free historical-data connector backed by ``yfinance`` (pip package).
Tier 0: 15-minute delayed, suitable for research & historical analysis
but **not** for live execution.

Optional dependency: ``yfinance``. If not installed, ``connect()`` raises
``ImportError`` with a helpful message. Tests should use
``PaperTradingConnector`` instead.
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

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.yahoo")


class YahooFinanceConnector(FinancialConnector):
    """Yahoo Finance historical data connector (free, global).

    Supports US, EU, HK equities and ETFs. Does NOT support real-time
    streaming or order execution.
    """

    tier = ConnectorTier.TIER_0_FREE_DELAYED
    supported_markets = {
        MarketClassification.US,
        MarketClassification.EU,
        MarketClassification.HK,
    }
    requires_credentials = False

    def __init__(self) -> None:
        self._connected = False
        self._yf: Any = None

    @property
    def connector_id(self) -> str:
        return "yahoo"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.HISTORICAL_DATA,
            ConnectorCapability.FUNDAMENTAL_DATA,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        try:
            import yfinance as yf  # type: ignore
            self._yf = yf
            self._connected = True
            logger.info("YahooFinanceConnector connected (yfinance v%s)", yf.__version__)
        except ImportError as e:
            raise ImportError(
                "yfinance is required for YahooFinanceConnector. "
                "Install with: pip install yfinance"
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
        if not self._connected or self._yf is None:
            raise RuntimeError("YahooFinanceConnector not connected")

        out: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            try:
                ticker = self._yf.Ticker(sym)
                df = ticker.history(start=start, end=end, interval=interval)
                bars: List[OHLCVBar] = []
                for ts, row in df.iterrows():
                    bars.append(
                        OHLCVBar(
                            timestamp=ts.timestamp() if hasattr(ts, "timestamp") else 0.0,
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=float(row["Volume"]),
                            symbol=sym,
                        )
                    )
                out[sym] = bars
            except Exception as e:
                logger.warning("Yahoo fetch failed for %s: %s", sym, e)
                out[sym] = []
        return out
