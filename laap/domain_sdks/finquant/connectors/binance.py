"""LAAP FinQuant Domain SDK — Binance crypto connector.

Tier 2 execution-grade connector for crypto spot & futures. Uses the
official ``python-binance`` SDK. Supports real-time WebSocket streaming
and order execution.

Optional dependency: ``python-binance``. Requires API key/secret.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from laap.domain_sdks.finquant.connectors.base import (
    ConnectorCapability,
    ConnectorHealth,
    ConnectorTier,
    FinancialConnector,
    MarketClassification,
    OHLCVBar,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Tick,
)

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.binance")


class BinanceConnector(FinancialConnector):
    """Binance crypto exchange connector — execution & streaming.

    Supports spot crypto pairs (e.g. BTCUSDT, ETHUSDT). Real-time
    WebSocket streaming and order execution.
    """

    tier = ConnectorTier.TIER_2_EXECUTION
    supported_markets = {MarketClassification.CRYPTO}
    requires_credentials = True

    def __init__(self) -> None:
        self._connected = False
        self._client: Any = None
        self._creds: Dict[str, Any] = {}

    @property
    def connector_id(self) -> str:
        return "binance"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.MARKET_DATA,
            ConnectorCapability.HISTORICAL_DATA,
            ConnectorCapability.ORDER_EXECUTION,
            ConnectorCapability.PORTFOLIO_QUERY,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if not credentials or "api_key" not in credentials or "api_secret" not in credentials:
            raise ValueError("BinanceConnector requires api_key and api_secret")
        try:
            from binance.client import Client  # type: ignore
            self._creds = dict(credentials)
            self._client = Client(
                api_key=credentials["api_key"],
                api_secret=credentials["api_secret"],
            )
            self._connected = True
            logger.info("BinanceConnector connected")
        except ImportError as e:
            raise ImportError(
                "python-binance is required for BinanceConnector. "
                "Install with: pip install python-binance"
            ) from e

    async def health_check(self) -> ConnectorHealth:
        if not self._connected:
            return ConnectorHealth.DISCONNECTED
        try:
            self._client.ping()
            return ConnectorHealth.HEALTHY
        except Exception:
            return ConnectorHealth.UNHEALTHY

    async def get_quote(self, symbols: List[str]) -> Dict[str, Tick]:
        if not self._connected:
            raise RuntimeError("BinanceConnector not connected")
        out: Dict[str, Tick] = {}
        for sym in symbols:
            try:
                ticker = self._client.get_symbol_ticker(symbol=sym)
                price = float(ticker["price"])
                out[sym] = Tick(symbol=sym, price=price, source=self.connector_id)
            except Exception as e:
                logger.warning("Binance quote failed for %s: %s", sym, e)
        return out

    async def stream_ticks(self, symbols: List[str]) -> AsyncIterator[Tick]:
        """Yield real-time ticks via Binance WebSocket.

        Uses depth / trade streams. For Phase 1 this is a stub that
        yields one snapshot per symbol — full WebSocket integration is
        Phase 2.
        """
        quotes = await self.get_quote(symbols)
        for tick in quotes.values():
            yield tick

    async def place_order(self, order: Order) -> OrderResult:
        if not self._connected:
            return OrderResult(status=OrderStatus.REJECTED,
                               reject_reason="not_connected")
        try:
            side = "BUY" if order.side == OrderSide.BUY else "SELL"
            otype_map = {
                OrderType.MARKET: "MARKET",
                OrderType.LIMIT: "LIMIT",
            }
            params: Dict[str, Any] = {
                "symbol": order.symbol,
                "side": side,
                "quantity": order.size,
                "type": otype_map.get(order.order_type, "MARKET"),
            }
            if order.order_type == OrderType.LIMIT and order.limit_price:
                params["price"] = order.limit_price
                params["timeInForce"] = "GTC"
            resp = self._client.create_order(**params)
            fills = resp.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                total_cost = sum(float(f["qty"]) * float(f["price"]) for f in fills)
                avg_price = total_cost / total_qty if total_qty else 0.0
                return OrderResult(
                    status=OrderStatus.FILLED,
                    order_id=str(resp.get("orderId", "")),
                    filled_size=total_qty,
                    avg_fill_price=avg_price,
                    commission=sum(float(f.get("commission", 0)) for f in fills),
                    raw=resp,
                )
            return OrderResult(
                status=OrderStatus.PENDING,
                order_id=str(resp.get("orderId", "")),
                raw=resp,
            )
        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
            )
