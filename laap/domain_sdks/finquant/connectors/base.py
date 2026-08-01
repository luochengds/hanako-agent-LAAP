"""LAAP FinQuant Domain SDK — Connector base class & data types.

All external financial interfaces (data feeds, brokerages, crypto
exchanges) are abstracted behind the ``FinancialConnector`` base class,
following LAAP's provider pattern. Cognitive actors never directly
depend on any specific API — they always go through a connector.

This module defines the abstract contract and the shared data types
(``Order``, ``OrderResult``, ``Position``, ``Tick``, ``Portfolio``).
Concrete connectors live alongside this file (``paper.py``, ``yahoo.py``,
``akshare.py``, ``binance.py``, ``tushare.py``, ``ibkr.py``, ``ctp.py``).

Usage::

    from laap.domain_sdks.finquant.connectors.base import (
        FinancialConnector, ConnectorCapability, Order, OrderSide,
    )

    class MyConnector(FinancialConnector):
        @property
        def connector_id(self) -> str: return "my_connector"
        @property
        def capabilities(self) -> set: return {ConnectorCapability.MARKET_DATA}
        async def connect(self, credentials): ...
        async def health_check(self): ...
        # + market-data / execution methods as advertised
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, AsyncIterator, Dict, List, Optional, Set

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.base")


# ── Enums ──────────────────────────────────────────────────────────


class ConnectorCapability(Enum):
    """Capability flags advertised by a connector.

    Used by ``resolve_connector()`` to filter candidates by what they
    can do (some connectors only fetch data, others can place orders).
    """

    MARKET_DATA = auto()  # real-time tick streaming
    HISTORICAL_DATA = auto()  # OHLCV / historical bars
    ORDER_EXECUTION = auto()  # place/cancel orders
    PORTFOLIO_QUERY = auto()  # query positions, balances
    NEWS_FEED = auto()  # news & sentiment
    FUNDAMENTAL_DATA = auto()  # financial statements, ratios


class OrderSide(Enum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Order lifecycle status."""

    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class MarketClassification(Enum):
    """Market classification for connector auto-selection."""

    US = "us"
    CN = "cn"  # China A-shares, bonds, futures
    EU = "eu"
    HK = "hk"  # Hong Kong
    CRYPTO = "crypto"
    FUTURES = "futures"
    FOREX = "forex"
    UNKNOWN = "unknown"


class ConnectorHealth(Enum):
    """Health status of a connector instance."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"  # operational but slow / partial outage
    UNHEALTHY = "unhealthy"
    DISCONNECTED = "disconnected"


# ── Tier (cost / latency) ──────────────────────────────────────────


class ConnectorTier(Enum):
    """Tier classification for auto-selection (lower = cheaper).

    Tier 0: free, delayed (15min) — research only
    Tier 1: free/paid, real-time — analysis, dev
    Tier 2: free, low-latency — execution-grade crypto/equities
    Tier 3: enterprise — institutional-grade, lowest latency
    """

    TIER_0_FREE_DELAYED = 0
    TIER_1_REALTIME = 1
    TIER_2_EXECUTION = 2
    TIER_3_INSTITUTIONAL = 3


# ── Data types ─────────────────────────────────────────────────────


@dataclass
class Tick:
    """Real-time market tick.

    Attributes:
        symbol: Ticker symbol (e.g. "AAPL", "000001.SZ", "BTCUSDT").
        price: Last traded price.
        volume: Cumulative day volume (or tick volume for crypto).
        bid: Best bid price (None if not available).
        ask: Best ask price (None if not available).
        timestamp: Unix epoch seconds (float).
        source: Connector ID that produced this tick.
    """

    symbol: str
    price: float
    volume: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""


@dataclass
class OHLCVBar:
    """A single OHLCV bar.

    Attributes:
        timestamp: Bar start time (Unix epoch seconds).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Volume during the bar.
        symbol: Symbol this bar belongs to.
    """

    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    symbol: str = ""


@dataclass
class Order:
    """A trade order.

    Attributes:
        symbol: Ticker symbol.
        side: Buy or sell.
        size: Quantity (shares / contracts / coins).
        order_type: Market / limit / stop / stop_limit.
        limit_price: Required for limit / stop_limit orders.
        stop_price: Required for stop / stop_limit orders.
        time_in_force: "day", "gtc", "ioc", "fok".
        client_order_id: Client-assigned order ID for idempotency.
        meta: Free-form metadata dict.
    """

    symbol: str
    side: OrderSide
    size: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "day"
    client_order_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    """Result of an order submission.

    Attributes:
        status: Final order status.
        order_id: Broker/exchange-assigned order ID.
        filled_size: Quantity filled.
        avg_fill_price: Average fill price (None if not filled).
        commission: Commission paid.
        slippage_bps: Realized slippage in basis points.
        reject_reason: Reason for rejection, if any.
        timestamp: Fill / reject timestamp.
        raw: Raw response from broker (for debugging).
    """

    status: OrderStatus
    order_id: str = ""
    filled_size: float = 0.0
    avg_fill_price: Optional[float] = None
    commission: float = 0.0
    slippage_bps: float = 0.0
    reject_reason: str = ""
    timestamp: float = field(default_factory=time.time)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """A current portfolio position.

    Attributes:
        symbol: Ticker symbol.
        quantity: Signed quantity (positive=long, negative=short).
        avg_cost: Average cost basis per share.
        market_price: Current market price.
        market_value: quantity * market_price.
        unrealized_pnl: (market_price - avg_cost) * quantity.
        sector: Sector classification (for concentration checks).
    """

    symbol: str
    quantity: float
    avg_cost: float = 0.0
    market_price: float = 0.0
    sector: str = ""
    market_value: float = 0.0
    unrealized_pnl: float = 0.0

    def __post_init__(self) -> None:
        if self.market_value == 0.0 and self.market_price:
            self.market_value = self.quantity * self.market_price
        if self.unrealized_pnl == 0.0 and self.avg_cost and self.market_price:
            self.unrealized_pnl = (self.market_price - self.avg_cost) * self.quantity


@dataclass
class Portfolio:
    """Snapshot of the current portfolio.

    Attributes:
        cash: Available cash.
        positions: List of current positions.
        total_value: Total portfolio value (cash + positions).
        currency: Reporting currency code.
        timestamp: Snapshot timestamp.
    """

    cash: float = 0.0
    positions: List[Position] = field(default_factory=list)
    total_value: float = 0.0
    currency: str = "USD"
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.total_value == 0.0:
            self.total_value = self.cash + sum(
                p.market_value for p in self.positions
            )

    def get_position(self, symbol: str) -> Optional[Position]:
        """Return the position for *symbol*, or None if not held."""
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    def sector_exposure(self) -> Dict[str, float]:
        """Return {sector: total_market_value} for concentration checks."""
        exposure: Dict[str, float] = {}
        for p in self.positions:
            sector = p.sector or "unknown"
            exposure[sector] = exposure.get(sector, 0.0) + p.market_value
        return exposure


# ── Abstract connector base ────────────────────────────────────────


class FinancialConnector(ABC):
    """Abstract base for all financial data & execution connectors.

    Concrete connectors implement the abstract methods and override
    whichever capability methods they support. Actors call capability
    methods directly; the base raises ``NotImplementedError`` for
    capabilities a connector does not advertise.

    The auto-selection ``resolve_connector()`` function in
    ``connectors/registry.py`` filters connectors by their advertised
    ``capabilities`` set.
    """

    # Tier — set by subclass for auto-selection ordering
    tier: ConnectorTier = ConnectorTier.TIER_0_FREE_DELAYED

    # Markets supported — set by subclass (set of MarketClassification)
    supported_markets: Set[MarketClassification] = set()

    # Whether connector requires credentials
    requires_credentials: bool = False

    @property
    @abstractmethod
    def connector_id(self) -> str:
        """Unique lowercase identifier (e.g. "yahoo", "binance")."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> Set[ConnectorCapability]:
        """Set of capabilities this connector supports."""
        ...

    @abstractmethod
    async def connect(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        """Establish connection. Validate credentials, open sockets, etc.

        Args:
            credentials: Dict of credential keys (api_key, secret, etc.).
                May be None for free, no-auth connectors.
        """
        ...

    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        """Return the current health status of the connector."""
        ...

    async def disconnect(self) -> None:
        """Optional: cleanup sockets / sessions. Default: no-op."""
        pass

    # ── Market data (override if MARKET_DATA / HISTORICAL_DATA) ──

    async def fetch_ohlcv(
        self,
        symbols: List[str],
        start: str,
        end: str,
        interval: str = "1d",
    ) -> Dict[str, List[OHLCVBar]]:
        """Fetch historical OHLCV bars for *symbols* in [start, end].

        Args:
            symbols: List of ticker symbols.
            start: Start date (ISO format "YYYY-MM-DD" or datetime string).
            end: End date (ISO format).
            interval: Bar interval ("1m", "5m", "15m", "1h", "1d", "1w").

        Returns:
            Dict mapping symbol → list of OHLCVBar sorted by timestamp.

        Raises:
            NotImplementedError: If connector does not support HISTORICAL_DATA.
        """
        raise NotImplementedError(
            f"{self.connector_id} does not support fetch_ohlcv"
        )

    async def stream_ticks(
        self, symbols: List[str]
    ) -> AsyncIterator[Tick]:
        """Stream real-time ticks for *symbols*.

        Args:
            symbols: List of ticker symbols to subscribe to.

        Yields:
            Tick instances as they arrive.

        Raises:
            NotImplementedError: If connector does not support MARKET_DATA.
        """
        raise NotImplementedError(
            f"{self.connector_id} does not support stream_ticks"
        )
        # Make this an async generator for type-checkers
        yield  # pragma: no cover  # type: ignore

    async def get_quote(self, symbols: List[str]) -> Dict[str, Tick]:
        """Fetch a one-shot quote snapshot for *symbols*.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict mapping symbol → Tick (with current price/bid/ask).

        Raises:
            NotImplementedError: If connector does not support MARKET_DATA.
        """
        raise NotImplementedError(
            f"{self.connector_id} does not support get_quote"
        )

    # ── Fundamentals (override if FUNDAMENTAL_DATA) ──

    async def get_financials(
        self,
        symbol: str,
        statement: str = "income",
        period: str = "annual",
    ) -> Dict[str, Any]:
        """Fetch financial statements (income / balance / cashflow)."""
        raise NotImplementedError(
            f"{self.connector_id} does not support get_financials"
        )

    async def get_corporate_actions(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch corporate actions (splits, dividends, mergers)."""
        raise NotImplementedError(
            f"{self.connector_id} does not support get_corporate_actions"
        )

    # ── Execution (override if ORDER_EXECUTION) ──

    async def place_order(self, order: Order) -> OrderResult:
        """Submit an order for execution.

        Args:
            order: The Order to submit.

        Returns:
            OrderResult with fill / reject status.

        Raises:
            NotImplementedError: If connector does not support ORDER_EXECUTION.
        """
        raise NotImplementedError(
            f"{self.connector_id} does not support place_order"
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        raise NotImplementedError(
            f"{self.connector_id} does not support cancel_order"
        )

    async def get_positions(self) -> List[Position]:
        """Return current open positions."""
        raise NotImplementedError(
            f"{self.connector_id} does not support get_positions"
        )

    async def get_portfolio(self) -> Portfolio:
        """Return full portfolio snapshot (cash + positions)."""
        raise NotImplementedError(
            f"{self.connector_id} does not support get_portfolio"
        )

    # ── Introspection helpers ──

    @property
    def is_execution_connector(self) -> bool:
        """True if this connector can place orders."""
        return ConnectorCapability.ORDER_EXECUTION in self.capabilities

    @property
    def is_data_connector(self) -> bool:
        """True if this connector can fetch market data."""
        return bool(
            self.capabilities
            & {
                ConnectorCapability.MARKET_DATA,
                ConnectorCapability.HISTORICAL_DATA,
            }
        )

    def supports_market(self, market: MarketClassification) -> bool:
        """True if connector supports the given market classification."""
        return market in self.supported_markets

    def describe(self) -> Dict[str, Any]:
        """Return a dict describing this connector (for CLI / docs)."""
        return {
            "connector_id": self.connector_id,
            "tier": self.tier.name,
            "capabilities": sorted(c.name for c in self.capabilities),
            "supported_markets": sorted(m.value for m in self.supported_markets),
            "requires_credentials": self.requires_credentials,
            "is_execution": self.is_execution_connector,
            "is_data": self.is_data_connector,
        }

    def __repr__(self) -> str:
        caps = "+".join(sorted(c.name[:4] for c in self.capabilities)) or "none"
        return f"<{self.__class__.__name__} id={self.connector_id} caps={caps}>"
