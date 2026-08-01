"""LAAP FinQuant Domain SDK — AkShare connector.

AkShare is an open-source financial data library for Chinese markets
(A-shares, bonds, futures, funds). Free, 15-minute delayed.

Optional dependency: ``akshare``. If not installed, ``connect()`` raises
``ImportError``. Used for CN-market historical analysis & research.
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

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.akshare")


class AkShareConnector(FinancialConnector):
    """AkShare data connector — free CN market data (A-shares, futures)."""

    tier = ConnectorTier.TIER_0_FREE_DELAYED
    supported_markets = {
        MarketClassification.CN,
        MarketClassification.FUTURES,
    }
    requires_credentials = False

    def __init__(self) -> None:
        self._connected = False
        self._ak: Any = None

    @property
    def connector_id(self) -> str:
        return "akshare"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.HISTORICAL_DATA,
            ConnectorCapability.FUNDAMENTAL_DATA,
            ConnectorCapability.NEWS_FEED,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        try:
            import akshare as ak  # type: ignore
            self._ak = ak
            self._connected = True
            logger.info("AkShareConnector connected (akshare v%s)", ak.__version__)
        except ImportError as e:
            raise ImportError(
                "akshare is required for AkShareConnector. "
                "Install with: pip install akshare"
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
        if not self._connected or self._ak is None:
            raise RuntimeError("AkShareConnector not connected")

        out: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            try:
                # AkShare's stock_zh_a_hist is the daily K-line for A-shares.
                # Other instruments have different APIs; we wrap the common case.
                df = self._ak.stock_zh_a_hist(
                    symbol=sym, period=interval, start_date=start.replace("-", ""),
                    end_date=end.replace("-", ""), adjust="qfq",
                )
                bars: List[OHLCVBar] = []
                for _, row in df.iterrows():
                    bars.append(
                        OHLCVBar(
                            timestamp=0.0,  # AkShare returns strings; caller normalizes
                            open=float(row["开盘"]),
                            high=float(row["最高"]),
                            low=float(row["最低"]),
                            close=float(row["收盘"]),
                            volume=float(row["成交量"]),
                            symbol=sym,
                        )
                    )
                out[sym] = bars
            except Exception as e:
                logger.warning("AkShare fetch failed for %s: %s", sym, e)
                out[sym] = []
        return out
