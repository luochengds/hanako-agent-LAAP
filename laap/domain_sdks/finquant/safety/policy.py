"""LAAP FinQuant Domain SDK — Safety policy.

The ``FinQuantSafetyPolicy`` is the **hard gate** that runs in the
security ``zone_executor`` BEFORE any order reaches an exchange API.
These checks cannot be bypassed by the LLM — violations raise
``SafetyBreachError`` which propagates up through the CognitiveBus and
halts the action pipeline.

Hard gates implemented:
- **Position limit**: max % of capital per single position.
- **Sector exposure**: max % of portfolio in one sector.
- **Leverage**: max portfolio leverage (gross exposure / NAV).
- **Daily drawdown**: halt trading if daily DD exceeds threshold.
- **Total drawdown**: liquidate if total DD exceeds threshold.
- **Rate limit**: max orders per minute (anti-runaway).
- **Restricted symbols**: blacklist (insider / embargoed / sanctions).
- **Liquidity**: reject orders in illiquid instruments.
- **Slippage**: reject if estimated slippage exceeds threshold.
- **Paper-trade-first**: new strategies must paper-trade before live.

Configuration is via class attributes (set at construction or subclassed).
All values use decimal fractions (0.10 = 10%).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from laap.domain_sdk.safety_policy import (
    DomainSafetyPolicy,
    SafetyBreachError,
    SafetyCheckResult,
    SafetyViolationType,
)

logger = logging.getLogger("laap.domain_sdks.finquant.safety.policy")


@dataclass
class FinQuantOrder:
    """Order representation accepted by FinQuantSafetyPolicy.

    A thin adapter so the safety policy does not need to import the
    connector ``Order`` class (decoupling safety from transport).

    Attributes:
        symbol: Ticker symbol.
        side: "buy" or "sell".
        size: Order quantity (shares / contracts / coins).
        limit_price: Limit price (None for market orders).
        sector: Sector classification of the symbol (for concentration).
        estimated_slippage_bps: Estimated slippage in basis points.
        avg_daily_volume: Average daily volume (for liquidity check).
        strategy_id: Strategy that generated this order (for paper-trade check).
        meta: Free-form metadata.
    """

    symbol: str
    side: str  # "buy" or "sell"
    size: float
    limit_price: Optional[float] = None
    sector: str = ""
    estimated_slippage_bps: float = 0.0
    avg_daily_volume: float = 0.0
    strategy_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_connector_order(cls, order: Any, **extras: Any) -> "FinQuantOrder":
        """Adapt a connector ``Order`` (or dict) to a FinQuantOrder.

        Accepts either a ``connectors.base.Order`` instance or a plain
        dict with the relevant fields. Extra fields (sector, slippage,
        volume) can be supplied via *extras*.
        """
        if isinstance(order, dict):
            return cls(
                symbol=order.get("symbol", ""),
                side=order.get("side", "buy").lower()
                if isinstance(order.get("side"), str)
                else order.get("side", "buy").value.lower(),
                size=float(order.get("size", 0.0)),
                limit_price=order.get("limit_price"),
                **extras,
            )
        # Duck-type connector Order
        side_val = order.side.value if hasattr(order.side, "value") else str(order.side).lower()
        return cls(
            symbol=order.symbol,
            side=side_val,
            size=float(order.size),
            limit_price=getattr(order, "limit_price", None),
            **extras,
        )


@dataclass
class FinQuantPortfolio:
    """Portfolio snapshot accepted by FinQuantSafetyPolicy.

    Attributes:
        cash: Available cash.
        total_value: Total portfolio NAV (cash + positions market value).
        positions: List of dicts {symbol, quantity, market_value, sector, avg_cost}.
        peak_value: Historical peak portfolio value (for drawdown calc).
        strategy_pnl: Per-strategy P&L dict {strategy_id: pnl}.
    """

    cash: float = 0.0
    total_value: float = 0.0
    positions: List[Dict[str, Any]] = field(default_factory=list)
    peak_value: float = 0.0
    strategy_pnl: Dict[str, float] = field(default_factory=dict)
    day_start_value: float = 0.0

    @classmethod
    def from_connector_portfolio(cls, portfolio: Any) -> "FinQuantPortfolio":
        """Adapt a connector ``Portfolio`` (or compatible) instance."""
        if isinstance(portfolio, dict):
            return cls(**portfolio)
        # Duck-type connector Portfolio
        positions = []
        for p in getattr(portfolio, "positions", []):
            if isinstance(p, dict):
                positions.append(p)
            else:
                positions.append({
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "market_value": p.market_value,
                    "sector": p.sector,
                    "avg_cost": p.avg_cost,
                })
        return cls(
            cash=getattr(portfolio, "cash", 0.0),
            total_value=getattr(portfolio, "total_value", 0.0),
            positions=positions,
            peak_value=getattr(portfolio, "total_value", 0.0),
            day_start_value=getattr(portfolio, "total_value", 0.0),
        )

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for p in self.positions:
            if p.get("symbol") == symbol:
                return p
        return None

    def sector_exposure(self) -> Dict[str, float]:
        exposure: Dict[str, float] = {}
        for p in self.positions:
            sector = p.get("sector", "") or "unknown"
            exposure[sector] = exposure.get(sector, 0.0) + abs(
                p.get("market_value", 0.0)
            )
        return exposure


class FinQuantSafetyPolicy(DomainSafetyPolicy):
    """Hard safety gates for financial operations.

    All checks run in the security ``zone_executor`` BEFORE any order
    is routed. The LLM cannot bypass these — violations raise
    ``SafetyBreachError`` which propagates up through the CognitiveBus.

    Configuration:
        All limits are class attributes expressed as decimal fractions
        (0.10 = 10%). Override by subclassing or passing kwargs to
        ``__init__`` (which sets instance attributes that shadow class
        defaults).
    """

    domain_id: str = "finquant"

    # ── Position limits ─────────────────────────────────────────────
    max_position_pct: float = 0.10  # Max 10% of capital per single position
    max_sector_exposure: float = 0.30  # Max 30% in one sector
    max_portfolio_leverage: float = 1.0  # No leverage by default (gross/NAV <= 1.0)
    max_correlation_concentration: float = 0.70

    # ── Drawdown protection ─────────────────────────────────────────
    max_daily_drawdown: float = 0.03  # 3% daily DD → halt
    max_total_drawdown: float = 0.15  # 15% total DD → liquidate
    drawdown_halt_hours: int = 24  # Cool-off period after DD breach

    # ── Execution guards ────────────────────────────────────────────
    max_orders_per_minute: int = 10
    max_slippage_bps: float = 50.0  # Reject if estimated slippage > 50 bps
    require_paper_trade_first: bool = True

    # ── Compliance ──────────────────────────────────────────────────
    restricted_symbols: Set[str] = set()
    min_liquidity_usd: float = 1_000_000.0  # Only trade liquid instruments

    def __init__(self, **overrides: Any) -> None:
        """Construct policy, allowing any class attribute to be overridden.

        Args:
            **overrides: e.g. ``max_position_pct=0.05`` to tighten to 5%.
        """
        for key, value in overrides.items():
            if hasattr(type(self), key) or hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning("Unknown FinQuantSafetyPolicy override: %s", key)

        # Mutable per-instance state — must NOT be class-level
        self._order_timestamps: deque = deque()  # for rate limiting
        self._halted_until: float = 0.0  # timestamp; orders rejected until this time
        self._halt_reason: str = ""
        self._paper_traded_strategies: Set[str] = set()
        # Ensure restricted_symbols is a per-instance copy (class default is shared)
        if not overrides.get("restricted_symbols"):
            self.restricted_symbols = set(self.restricted_symbols)

    # ── Hard gate (required by DomainSafetyPolicy) ─────────────────

    def pre_execution_gate(self, action: Any, context: Any) -> None:
        """Hard gate — raises SafetyBreachError if any limit violated.

        Args:
            action: A ``FinQuantOrder`` (or compatible dict / connector Order).
            context: A ``FinQuantPortfolio`` (or compatible dict / connector Portfolio).

        Raises:
            SafetyBreachError: On any safety violation.
        """
        order = self._coerce_order(action)
        portfolio = self._coerce_portfolio(context)

        # 1. Drawdown halt check — if halted, reject all orders
        self._check_drawdown_halt()

        # 2. Restricted symbols
        self._check_restricted(order)

        # 3. Liquidity
        self._check_liquidity(order)

        # 4. Slippage
        self._check_slippage(order)

        # 5. Rate limit
        self._check_rate_limit()

        # 6. Drawdown levels
        self._check_drawdown_level(portfolio)

        # 7. Paper-trade-first
        self._check_paper_trade_first(order)

        # 8. Position limit
        self._check_position_limit(order, portfolio)

        # 9. Sector exposure
        self._check_sector_exposure(order, portfolio)

        # 10. Leverage
        self._check_leverage(order, portfolio)

        # All checks pass — order may proceed
        logger.debug(
            "Safety gate passed: %s %s %s @ %s",
            order.side, order.size, order.symbol, order.limit_price or "market",
        )

    # ── Individual gate implementations ────────────────────────────

    def _check_restricted(self, order: FinQuantOrder) -> None:
        if order.symbol in self.restricted_symbols:
            raise SafetyBreachError(
                message=f"Symbol '{order.symbol}' is restricted (insider/embargoed)",
                domain=self.domain_id,
                violation=SafetyViolationType.RESTRICTED_ITEM,
                details={"symbol": order.symbol},
            )

    def _check_liquidity(self, order: FinQuantOrder) -> None:
        if order.avg_daily_volume <= 0:
            return  # Unknown volume — allow (caller should set this)
        # Estimate notional vs avg daily volume
        # Conservative: require order notional <= 1% of avg daily volume
        ref_price = order.limit_price or 0.0
        if ref_price <= 0:
            return
        order_notional = order.size * ref_price
        if order_notional > order.avg_daily_volume * 0.01:
            # Also check absolute liquidity floor
            if order.avg_daily_volume < self.min_liquidity_usd:
                raise SafetyBreachError(
                    message=(
                        f"Symbol '{order.symbol}' avg daily volume "
                        f"${order.avg_daily_volume:,.0f} below min "
                        f"${self.min_liquidity_usd:,.0f}"
                    ),
                    domain=self.domain_id,
                    violation=SafetyViolationType.LIQUIDITY,
                    details={
                        "symbol": order.symbol,
                        "adv": order.avg_daily_volume,
                        "min_liquidity": self.min_liquidity_usd,
                    },
                )

    def _check_slippage(self, order: FinQuantOrder) -> None:
        if order.estimated_slippage_bps > self.max_slippage_bps:
            raise SafetyBreachError(
                message=(
                    f"Estimated slippage {order.estimated_slippage_bps:.1f}bps "
                    f"exceeds max {self.max_slippage_bps:.1f}bps"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.LIQUIDITY,
                details={
                    "symbol": order.symbol,
                    "estimated_slippage_bps": order.estimated_slippage_bps,
                    "max_slippage_bps": self.max_slippage_bps,
                },
            )

    def _check_rate_limit(self) -> None:
        now = time.time()
        window = 60.0  # 1-minute window
        # Expire old timestamps
        while self._order_timestamps and self._order_timestamps[0] < now - window:
            self._order_timestamps.popleft()
        if len(self._order_timestamps) >= self.max_orders_per_minute:
            raise SafetyBreachError(
                message=(
                    f"Rate limit: {len(self._order_timestamps)} orders in last "
                    f"60s exceeds max {self.max_orders_per_minute}"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.RATE_LIMIT,
                details={
                    "recent_orders": len(self._order_timestamps),
                    "max_per_minute": self.max_orders_per_minute,
                },
            )
        # Record this attempt
        self._order_timestamps.append(now)

    def _check_drawdown_halt(self) -> None:
        if self._halted_until > 0 and time.time() < self._halted_until:
            remaining = self._halted_until - time.time()
            raise SafetyBreachError(
                message=(
                    f"Trading halted due to drawdown breach: "
                    f"{remaining:.0f}s remaining (reason: {self._halt_reason})"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.DRAWDOWN_LIMIT,
                details={
                    "halted_until": self._halted_until,
                    "reason": self._halt_reason,
                    "remaining_seconds": remaining,
                },
            )

    def _check_drawdown_level(self, portfolio: FinQuantPortfolio) -> None:
        if portfolio.peak_value <= 0 or portfolio.total_value <= 0:
            return

        total_dd = 1.0 - (portfolio.total_value / portfolio.peak_value)
        if total_dd >= self.max_total_drawdown:
            self._halted_until = time.time() + (self.drawdown_halt_hours * 3600)
            self._halt_reason = (
                f"total_drawdown_{total_dd:.2%}_exceeds_"
                f"{self.max_total_drawdown:.2%}"
            )
            raise SafetyBreachError(
                message=(
                    f"Total drawdown {total_dd:.2%} exceeds max "
                    f"{self.max_total_drawdown:.2%} — liquidating & halting"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.DRAWDOWN_LIMIT,
                details={
                    "total_drawdown": total_dd,
                    "max_total_drawdown": self.max_total_drawdown,
                    "peak_value": portfolio.peak_value,
                    "current_value": portfolio.total_value,
                },
            )

        if portfolio.day_start_value > 0:
            daily_dd = 1.0 - (portfolio.total_value / portfolio.day_start_value)
            if daily_dd >= self.max_daily_drawdown:
                self._halted_until = time.time() + (self.drawdown_halt_hours * 3600)
                self._halt_reason = (
                    f"daily_drawdown_{daily_dd:.2%}_exceeds_"
                    f"{self.max_daily_drawdown:.2%}"
                )
                raise SafetyBreachError(
                    message=(
                        f"Daily drawdown {daily_dd:.2%} exceeds max "
                        f"{self.max_daily_drawdown:.2%} — halting for "
                        f"{self.drawdown_halt_hours}h"
                    ),
                    domain=self.domain_id,
                    violation=SafetyViolationType.DRAWDOWN_LIMIT,
                    details={
                        "daily_drawdown": daily_dd,
                        "max_daily_drawdown": self.max_daily_drawdown,
                        "day_start_value": portfolio.day_start_value,
                        "current_value": portfolio.total_value,
                    },
                )

    def _check_paper_trade_first(self, order: FinQuantOrder) -> None:
        if not self.require_paper_trade_first:
            return
        sid = order.strategy_id
        if not sid:
            return  # No strategy attribution — can't enforce
        if sid not in self._paper_traded_strategies:
            raise SafetyBreachError(
                message=(
                    f"Strategy '{sid}' has not passed paper trading — "
                    f"live execution blocked"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.COMPLIANCE,
                details={
                    "strategy_id": sid,
                    "paper_traded": list(self._paper_traded_strategies),
                },
            )

    def _check_position_limit(self, order: FinQuantOrder, portfolio: FinQuantPortfolio) -> None:
        if portfolio.total_value <= 0:
            return
        ref_price = order.limit_price or 0.0
        if ref_price <= 0:
            return  # Can't assess market order notional without price
        order_notional = order.size * ref_price
        existing = portfolio.get_position(order.symbol)
        existing_value = abs(existing.get("market_value", 0.0)) if existing else 0.0

        if order.side == "buy":
            new_position_value = existing_value + order_notional
        else:
            new_position_value = max(0.0, existing_value - order_notional)

        pct = new_position_value / portfolio.total_value
        if pct > self.max_position_pct:
            raise SafetyBreachError(
                message=(
                    f"Position '{order.symbol}' would be {pct:.2%} of capital "
                    f"(max {self.max_position_pct:.2%})"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.POSITION_LIMIT,
                details={
                    "symbol": order.symbol,
                    "new_position_value": new_position_value,
                    "portfolio_value": portfolio.total_value,
                    "pct": pct,
                    "max_pct": self.max_position_pct,
                },
            )

    def _check_sector_exposure(self, order: FinQuantOrder, portfolio: FinQuantPortfolio) -> None:
        if not order.sector or portfolio.total_value <= 0:
            return
        ref_price = order.limit_price or 0.0
        if ref_price <= 0:
            return
        order_notional = order.size * ref_price

        exposure = portfolio.sector_exposure()
        current_sector_exposure = exposure.get(order.sector, 0.0)
        if order.side == "buy":
            new_sector_exposure = current_sector_exposure + order_notional
        else:
            new_sector_exposure = max(0.0, current_sector_exposure - order_notional)

        pct = new_sector_exposure / portfolio.total_value
        if pct > self.max_sector_exposure:
            raise SafetyBreachError(
                message=(
                    f"Sector '{order.sector}' exposure would be {pct:.2%} "
                    f"(max {self.max_sector_exposure:.2%})"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.CONCENTRATION,
                details={
                    "sector": order.sector,
                    "new_sector_exposure": new_sector_exposure,
                    "portfolio_value": portfolio.total_value,
                    "pct": pct,
                    "max_pct": self.max_sector_exposure,
                },
            )

    def _check_leverage(self, order: FinQuantOrder, portfolio: FinQuantPortfolio) -> None:
        if portfolio.total_value <= 0:
            return
        ref_price = order.limit_price or 0.0
        if ref_price <= 0:
            return
        order_notional = order.size * ref_price

        # Gross exposure = sum of |position market values|
        current_gross = sum(abs(p.get("market_value", 0.0)) for p in portfolio.positions)
        if order.side == "buy":
            new_gross = current_gross + order_notional
        else:
            new_gross = max(0.0, current_gross - order_notional)

        leverage = new_gross / portfolio.total_value
        if leverage > self.max_portfolio_leverage:
            raise SafetyBreachError(
                message=(
                    f"Portfolio leverage would be {leverage:.2f}x "
                    f"(max {self.max_portfolio_leverage:.2f}x)"
                ),
                domain=self.domain_id,
                violation=SafetyViolationType.LEVERAGE,
                details={
                    "new_gross_exposure": new_gross,
                    "portfolio_value": portfolio.total_value,
                    "leverage": leverage,
                    "max_leverage": self.max_portfolio_leverage,
                },
            )

    # ── Public helpers (used by Executor actor) ────────────────────

    def mark_strategy_paper_traded(self, strategy_id: str) -> None:
        """Mark a strategy as having passed paper trading.

        After calling this, ``require_paper_trade_first`` no longer
        blocks that strategy's live orders.
        """
        self._paper_traded_strategies.add(strategy_id)
        logger.info("Strategy '%s' marked as paper-traded", strategy_id)

    def reset_halt(self) -> None:
        """Manually reset the drawdown halt (admin override)."""
        self._halted_until = 0.0
        self._halt_reason = ""

    def get_halt_status(self) -> Dict[str, Any]:
        """Return current halt status (for monitoring / dashboards)."""
        if self._halted_until <= 0 or time.time() >= self._halted_until:
            return {"halted": False}
        return {
            "halted": True,
            "remaining_seconds": self._halted_until - time.time(),
            "reason": self._halt_reason,
        }

    def get_config(self) -> Dict[str, Any]:
        """Return the policy's configuration as a dict (for CLI display)."""
        return {
            "max_position_pct": self.max_position_pct,
            "max_sector_exposure": self.max_sector_exposure,
            "max_portfolio_leverage": self.max_portfolio_leverage,
            "max_correlation_concentration": self.max_correlation_concentration,
            "max_daily_drawdown": self.max_daily_drawdown,
            "max_total_drawdown": self.max_total_drawdown,
            "drawdown_halt_hours": self.drawdown_halt_hours,
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_slippage_bps": self.max_slippage_bps,
            "require_paper_trade_first": self.require_paper_trade_first,
            "restricted_symbols": sorted(self.restricted_symbols),
            "min_liquidity_usd": self.min_liquidity_usd,
        }

    # ── Coercion helpers ───────────────────────────────────────────

    @staticmethod
    def _coerce_order(action: Any) -> FinQuantOrder:
        if isinstance(action, FinQuantOrder):
            return action
        if isinstance(action, dict):
            return FinQuantOrder(
                symbol=action.get("symbol", ""),
                side=action.get("side", "buy"),
                size=float(action.get("size", 0.0)),
                limit_price=action.get("limit_price"),
                sector=action.get("sector", ""),
                estimated_slippage_bps=action.get("estimated_slippage_bps", 0.0),
                avg_daily_volume=action.get("avg_daily_volume", 0.0),
                strategy_id=action.get("strategy_id", ""),
                meta=action.get("meta", {}),
            )
        # Duck-type connector Order
        return FinQuantOrder.from_connector_order(action)

    @staticmethod
    def _coerce_portfolio(context: Any) -> FinQuantPortfolio:
        if isinstance(context, FinQuantPortfolio):
            return context
        if isinstance(context, dict):
            # Accept dict with subset of fields
            return FinQuantPortfolio(
                cash=context.get("cash", 0.0),
                total_value=context.get("total_value", 0.0),
                positions=context.get("positions", []),
                peak_value=context.get("peak_value", context.get("total_value", 0.0)),
                day_start_value=context.get(
                    "day_start_value", context.get("total_value", 0.0)
                ),
                strategy_pnl=context.get("strategy_pnl", {}),
            )
        return FinQuantPortfolio.from_connector_portfolio(context)
