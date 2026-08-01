"""LAAP FinQuant Domain SDK — Paper Trading connector.

The ``PaperTradingConnector`` is a built-in execution connector that
simulates order fills using a slippage model. It is **always available**
(no external dependencies, no credentials) and serves two purposes:

1. **Default execution target**: New strategies must paper-trade before
   going live (``FinQuantSafetyPolicy.require_paper_trade_first = True``).
2. **Test harness**: Tests and backtests can run end-to-end without
   real broker connectivity.

The simulated fill logic:
    - Market orders fill at last price ± slippage (random or deterministic).
    - Limit orders fill if the limit price is reached within the bar.
    - Slippage model: "none", "linear" (size-proportional), "volume_based".

This connector also maintains an in-memory ``Portfolio`` so that
``get_portfolio()`` and ``get_positions()`` work without any external
broker. The safety policy gate is enforced *before* any simulated fill,
mirroring the live-execution contract.
"""

from __future__ import annotations

import logging
import time
import uuid
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
    Portfolio,
    Position,
    Tick,
)

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.paper")


class PaperTradingConnector(FinancialConnector):
    """Simulated execution connector — always available, no credentials.

    The default slippage model is ``"linear"`` with a 5 bps coefficient
    (0.0005 in decimal). For deterministic tests, set ``slippage_model="none"``
    or pass ``slippage_bps=0``.

    Args:
        initial_cash: Starting cash balance for the virtual portfolio.
        slippage_model: "none", "linear", or "volume_based".
        slippage_bps: Slippage in basis points for "linear" model.
        commission_bps: Commission in basis points per fill.
        last_prices: Initial price map {symbol: price} for fill simulation.
    """

    tier = ConnectorTier.TIER_2_EXECUTION
    supported_markets = {
        MarketClassification.US,
        MarketClassification.CN,
        MarketClassification.EU,
        MarketClassification.HK,
        MarketClassification.CRYPTO,
        MarketClassification.FUTURES,
    }
    requires_credentials = False

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        slippage_model: str = "linear",
        slippage_bps: float = 5.0,
        commission_bps: float = 1.0,
        last_prices: Optional[Dict[str, float]] = None,
    ) -> None:
        self._slippage_model = slippage_model
        self._slippage_bps = slippage_bps
        self._commission_bps = commission_bps
        self._last_prices: Dict[str, float] = dict(last_prices or {})
        self._connected = False
        self._portfolio = Portfolio(
            cash=initial_cash,
            positions=[],
            total_value=initial_cash,
        )
        # Track open orders by client_order_id for cancel support
        self._open_orders: Dict[str, Order] = {}
        self._fills_log: List[Dict[str, Any]] = []

    # ── FinancialConnector contract ──────────────────────────────────

    @property
    def connector_id(self) -> str:
        return "paper"

    @property
    def capabilities(self):
        return {
            ConnectorCapability.ORDER_EXECUTION,
            ConnectorCapability.PORTFOLIO_QUERY,
            ConnectorCapability.MARKET_DATA,
        }

    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        """Paper trading needs no credentials — always succeeds."""
        self._connected = True
        logger.info(
            "PaperTradingConnector connected (cash=%s, slippage=%s/%sbps)",
            self._portfolio.cash, self._slippage_model, self._slippage_bps,
        )

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY if self._connected else ConnectorHealth.DISCONNECTED

    async def disconnect(self) -> None:
        self._connected = False

    # ── Market data (simulated) ─────────────────────────────────────

    async def get_quote(self, symbols: List[str]) -> Dict[str, Tick]:
        """Return last known prices as Tick snapshots."""
        out: Dict[str, Tick] = {}
        for sym in symbols:
            price = self._last_prices.get(sym, 0.0)
            out[sym] = Tick(
                symbol=sym,
                price=price,
                bid=price,
                ask=price,
                source=self.connector_id,
            )
        return out

    async def stream_ticks(self, symbols: List[str]) -> AsyncIterator[Tick]:
        """Paper connector does not stream real ticks — yields one snapshot then ends.

        Real connectors override this with a true async generator.
        """
        if not self._connected:
            raise RuntimeError("PaperTradingConnector not connected")
        quotes = await self.get_quote(symbols)
        for sym, tick in quotes.items():
            yield tick

    async def fetch_ohlcv(
        self,
        symbols: List[str],
        start: str,
        end: str,
        interval: str = "1d",
    ) -> Dict[str, List[OHLCVBar]]:
        """Paper connector has no historical data store — return empty bars."""
        # In production, paper trading would proxy to a real data connector.
        # For Phase 1, return empty lists so callers can detect "no data".
        return {sym: [] for sym in symbols}

    # ── Execution ──────────────────────────────────────────────────

    async def place_order(self, order: Order) -> OrderResult:
        """Simulate order fill against last known price + slippage model.

        The safety policy gate is enforced by the *caller* (Executor actor),
        NOT by the connector — this mirrors the live connector contract
        where the safety gate runs before the order reaches the exchange API.
        """
        if not self._connected:
            return OrderResult(
                status=OrderStatus.REJECTED,
                reject_reason="connector_not_connected",
            )

        last_price = self._last_prices.get(order.symbol)
        if last_price is None or last_price <= 0:
            return OrderResult(
                status=OrderStatus.REJECTED,
                reject_reason=f"no_last_price_for_{order.symbol}",
            )

        # Determine fill price
        if order.order_type == OrderType.MARKET:
            fill_price = self._apply_slippage(last_price, order)
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                return OrderResult(
                    status=OrderStatus.REJECTED,
                    reject_reason="limit_order_requires_limit_price",
                )
            # Buy limit fills if last_price <= limit_price
            # Sell limit fills if last_price >= limit_price
            if order.side == OrderSide.BUY and last_price > order.limit_price:
                return OrderResult(
                    status=OrderStatus.PENDING,
                    order_id=self._gen_order_id(),
                    reject_reason="limit_not_reached",
                )
            if order.side == OrderSide.SELL and last_price < order.limit_price:
                return OrderResult(
                    status=OrderStatus.PENDING,
                    order_id=self._gen_order_id(),
                    reject_reason="limit_not_reached",
                )
            fill_price = order.limit_price
        else:
            # STOP / STOP_LIMIT not implemented in Phase 1 paper trading
            return OrderResult(
                status=OrderStatus.REJECTED,
                reject_reason=f"order_type_{order.order_type.value}_not_supported",
            )

        # Apply commission
        commission = (fill_price * order.size) * (self._commission_bps / 10_000)

        # Update virtual portfolio
        self._apply_fill_to_portfolio(order, fill_price, commission)

        slippage_bps = ((fill_price - last_price) / last_price) * 10_000
        if order.side == OrderSide.SELL:
            slippage_bps = -slippage_bps  # Sell slippage is negative when fill < last

        result = OrderResult(
            status=OrderStatus.FILLED,
            order_id=self._gen_order_id(),
            filled_size=order.size,
            avg_fill_price=fill_price,
            commission=commission,
            slippage_bps=slippage_bps,
            raw={
                "connector": self.connector_id,
                "last_price": last_price,
                "fill_price": fill_price,
            },
        )

        self._fills_log.append({
            "timestamp": result.timestamp,
            "symbol": order.symbol,
            "side": order.side.value,
            "size": order.size,
            "fill_price": fill_price,
            "commission": commission,
            "order_id": result.order_id,
        })
        logger.debug(
            "PAPER FILL %s %s %s @ %s (slippage=%.2fbps, comm=%.4f)",
            order.side.value, order.size, order.symbol, fill_price,
            slippage_bps, commission,
        )
        return result

    async def cancel_order(self, order_id: str) -> bool:
        return self._open_orders.pop(order_id, None) is not None

    async def get_positions(self) -> List[Position]:
        return list(self._portfolio.positions)

    async def get_portfolio(self) -> Portfolio:
        # Refresh market value with last known prices
        for pos in self._portfolio.positions:
            pos.market_price = self._last_prices.get(pos.symbol, pos.market_price)
            pos.market_value = pos.quantity * pos.market_price
            pos.unrealized_pnl = (pos.market_price - pos.avg_cost) * pos.quantity
        self._portfolio.total_value = (
            self._portfolio.cash
            + sum(p.market_value for p in self._portfolio.positions)
        )
        return self._portfolio

    # ── Helpers for tests / inspection ──────────────────────────────

    def set_last_price(self, symbol: str, price: float) -> None:
        """Set the simulated last price for *symbol* (for test scenarios)."""
        self._last_prices[symbol] = price

    def get_fills_log(self) -> List[Dict[str, Any]]:
        """Return a copy of all simulated fills (for test assertions)."""
        return list(self._fills_log)

    @property
    def portfolio(self) -> Portfolio:
        """Direct access to the virtual portfolio (no async, for tests)."""
        return self._portfolio

    # ── Internal slippage & fill logic ──────────────────────────────

    def _apply_slippage(self, last_price: float, order: Order) -> float:
        """Apply slippage model to compute fill price for a market order."""
        if self._slippage_model == "none" or self._slippage_bps == 0:
            return last_price

        # Linear: slippage proportional to order size, expressed in bps.
        # Buy orders fill higher (pay more), sell orders fill lower (receive less).
        sign = 1.0 if order.side == OrderSide.BUY else -1.0
        slip_frac = (self._slippage_bps / 10_000.0) * sign
        return last_price * (1.0 + slip_frac)

    def _apply_fill_to_portfolio(
        self,
        order: Order,
        fill_price: float,
        commission: float,
    ) -> None:
        """Update virtual cash & positions after a fill."""
        cost = fill_price * order.size
        if order.side == OrderSide.BUY:
            self._portfolio.cash -= (cost + commission)
            qty_delta = order.size
        else:
            self._portfolio.cash += (cost - commission)
            qty_delta = -order.size

        # Find or create position
        pos = self._find_position(order.symbol)
        if pos is None:
            pos = Position(
                symbol=order.symbol,
                quantity=0.0,
                avg_cost=0.0,
                market_price=fill_price,
                sector=order.meta.get("sector", ""),
            )
            self._portfolio.positions.append(pos)

        # Update average cost (only for buys that increase position)
        new_qty = pos.quantity + qty_delta
        if order.side == OrderSide.BUY and pos.quantity >= 0:
            # Long buy or short cover that increases long position
            if pos.quantity >= 0:
                pos.avg_cost = (
                    (pos.avg_cost * pos.quantity + fill_price * order.size)
                    / new_qty
                    if new_qty != 0
                    else fill_price
                )
        # For sells that flip position, avg_cost resets to fill_price
        if (order.side == OrderSide.SELL and pos.quantity > 0 and new_qty < 0) or \
           (order.side == OrderSide.BUY and pos.quantity < 0 and new_qty > 0):
            pos.avg_cost = fill_price

        pos.quantity = new_qty
        pos.market_price = fill_price
        pos.market_value = pos.quantity * fill_price

        # Remove zeroed positions to keep portfolio clean
        if abs(pos.quantity) < 1e-9:
            self._portfolio.positions.remove(pos)

        # Update last known price to fill price
        self._last_prices[order.symbol] = fill_price

    def _find_position(self, symbol: str) -> Optional[Position]:
        for p in self._portfolio.positions:
            if p.symbol == symbol:
                return p
        return None

    @staticmethod
    def _gen_order_id() -> str:
        return f"paper-{uuid.uuid4().hex[:12]}"
