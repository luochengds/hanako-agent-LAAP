"""LAAP FinQuant Domain SDK — Connector registry & auto-selection.

Implements ``resolve_connector()`` which auto-selects the optimal
connector for given symbols based on:
1. Market classification (CN/US/EU/HK/Crypto/Futures)
2. Required capabilities (data vs execution)
3. Available credentials
4. Latency tier (lowest-cost tier meeting requirements)

The registry maintains a pool of pre-instantiated connectors keyed by
``connector_id``. New connectors are added via ``register_connector()``
or discovered via ``discover_connectors()`` (which instantiates all
known connector classes that can be imported).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

from laap.domain_sdks.finquant.connectors.base import (
    ConnectorCapability,
    ConnectorTier,
    FinancialConnector,
    MarketClassification,
)

logger = logging.getLogger("laap.domain_sdks.finquant.connectors.registry")


# ── Symbol classification ──────────────────────────────────────────

# CN A-share patterns: 6-digit codes with .SH / .SZ / .BJ suffix, or
# pure 6-digit codes like "000001", "600519".
_CN_PATTERN = re.compile(
    r"^[036]\d{5}(\.(SH|SZ|BJ))?$|^sh\d{6}$|^sz\d{6}$|^bj\d{6}$",
    re.IGNORECASE,
)
# HK: 5-digit numeric like "00700" or with .HK suffix
_HK_PATTERN = re.compile(r"^\d{4,5}(\.HK)?$|^hk\d{4,5}$", re.IGNORECASE)
# Crypto: known patterns like BTCUSDT, ETHUSDT, BTC-USD
_CRYPTO_PATTERN = re.compile(
    r"^(BTC|ETH|BNB|SOL|XRP|ADA|DOGE|DOT|MATIC|LTC|AVAX|LINK|UNI|ATOM|XLM|NEAR|APT)"
    r"(USDT|USDC|BUSD|USD|EUR|BTC|ETH)$",
    re.IGNORECASE,
)
# Futures: common patterns like IF2312, RB2312, CLZ3
_FUTURES_PATTERN = re.compile(
    r"^(IF|IC|IH|IM|RB|HC|RU|CU|AL|ZN|PB|NI|SN|AU|AG|FU|BU|RU|MA|TA|SR|CF|OI|AP|CJ|UR|SA|SF|SM|FG|EG|"
    r"CL|NG|GC|SI|ZS|ZM|ZW|KC|CT|SB|CC|OJ|LB|LC|LBS|HE|LE|GD|FESX|FXI|ES|NQ|YM|RTY|ZB|ZN|ZT|GBL|GBM|GBS)"
    r"\d{1,4}$",
    re.IGNORECASE,
)


def classify_market(symbols: List[str]) -> MarketClassification:
    """Classify the market for a list of symbols.

    If all symbols belong to the same market, returns that market.
    If mixed, returns ``UNKNOWN``.

    Args:
        symbols: List of ticker symbols to classify.

    Returns:
        MarketClassification enum value.
    """
    if not symbols:
        return MarketClassification.UNKNOWN

    classifications: Set[MarketClassification] = set()
    for sym in symbols:
        s = sym.strip().upper()
        if _CRYPTO_PATTERN.match(s):
            classifications.add(MarketClassification.CRYPTO)
        elif _CN_PATTERN.match(s):
            classifications.add(MarketClassification.CN)
        elif _HK_PATTERN.match(s):
            classifications.add(MarketClassification.HK)
        elif _FUTURES_PATTERN.match(s):
            classifications.add(MarketClassification.FUTURES)
        else:
            # Default: treat as US equity (letters, 1-5 chars)
            classifications.add(MarketClassification.US)

    if len(classifications) == 1:
        return classifications.pop()
    return MarketClassification.UNKNOWN


# ── Connector registry ────────────────────────────────────────────


class ConnectorRegistry:
    """Registry of available financial connectors.

    Maintains a pool of pre-instantiated connectors and provides
    ``resolve_connector()`` for auto-selection based on symbols,
    required capabilities, and credentials.
    """

    def __init__(self) -> None:
        self._connectors: Dict[str, FinancialConnector] = {}
        self._credentials: Dict[str, Dict[str, Any]] = {}
        # Default paper connector is always available
        self._ensure_paper()

    def _ensure_paper(self) -> None:
        """Ensure the PaperTradingConnector is registered."""
        if "paper" not in self._connectors:
            from laap.domain_sdks.finquant.connectors.paper import PaperTradingConnector
            paper = PaperTradingConnector()
            # Paper trading doesn't need connect() — but mark it ready
            self._connectors["paper"] = paper
            logger.debug("Registered default PaperTradingConnector")

    def register(
        self,
        connector: FinancialConnector,
        credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a connector instance with optional credentials.

        Args:
            connector: A FinancialConnector instance.
            credentials: Optional credentials dict for this connector.
        """
        cid = connector.connector_id
        self._connectors[cid] = connector
        if credentials:
            self._credentials[cid] = dict(credentials)
        logger.debug("Registered connector: %s", cid)

    def set_credentials(self, connector_id: str, credentials: Dict[str, Any]) -> None:
        """Attach credentials to an already-registered connector."""
        self._credentials[connector_id] = dict(credentials)

    def get(self, connector_id: str) -> Optional[FinancialConnector]:
        """Return the connector with *connector_id*, or None."""
        return self._connectors.get(connector_id)

    def list_connectors(self) -> List[FinancialConnector]:
        """Return all registered connectors."""
        return list(self._connectors.values())

    def list_ids(self) -> List[str]:
        """Return all registered connector IDs."""
        return list(self._connectors.keys())

    def clear(self) -> None:
        """Remove all connectors except the default paper connector."""
        self._connectors.clear()
        self._credentials.clear()
        self._ensure_paper()

    # ── Auto-selection ─────────────────────────────────────────────

    async def resolve_connector(
        self,
        symbols: List[str],
        required_capabilities: Optional[Set[ConnectorCapability]] = None,
        preferred: str = "auto",
        require_realtime: bool = False,
        max_latency_tier: Optional[ConnectorTier] = None,
    ) -> FinancialConnector:
        """Auto-select the best connector for the given symbols.

        Selection logic:
        1. If *preferred* is a connector ID and that connector is
           registered, return it (after capability check).
        2. Classify symbols by market.
        3. Filter candidates by market support + required capabilities.
        4. Filter by available credentials.
        5. If realtime required, filter by latency tier.
        6. Select lowest-cost (lowest tier) connector meeting all constraints.
        7. Fallback to PaperTradingConnector.

        Args:
            symbols: Ticker symbols to fetch / trade.
            required_capabilities: Set of required ConnectorCapability values.
                If None, defaults to {HISTORICAL_DATA} for data fetches.
            preferred: "auto" or a specific connector ID.
            require_realtime: If True, exclude delayed (Tier 0) connectors.
            max_latency_tier: If set, exclude connectors above this tier.

        Returns:
            The selected FinancialConnector instance.

        Raises:
            ValueError: If no connector meets the requirements.
        """
        if required_capabilities is None:
            required_capabilities = {ConnectorCapability.HISTORICAL_DATA}

        # ── Explicit preferred ──
        if preferred != "auto":
            conn = self._connectors.get(preferred)
            if conn is None:
                raise ValueError(f"Preferred connector '{preferred}' not registered")
            self._verify_capabilities(conn, required_capabilities)
            return conn

        # ── Auto-selection ──
        market = classify_market(symbols)
        candidates = self._filter_by_market(market)
        candidates = self._filter_by_capabilities(candidates, required_capabilities)
        candidates = self._filter_by_credentials(candidates)

        if require_realtime:
            candidates = [
                c for c in candidates
                if c.tier.value > ConnectorTier.TIER_0_FREE_DELAYED.value
            ]

        if max_latency_tier is not None:
            candidates = [
                c for c in candidates if c.tier.value <= max_latency_tier.value
            ]

        if not candidates:
            # Last resort: paper connector (always available)
            paper = self._connectors.get("paper")
            if paper is None:
                raise ValueError(
                    f"No connector available for symbols={symbols} "
                    f"caps={required_capabilities} market={market.value}"
                )
            logger.warning(
                "No real connector available for %s (market=%s, caps=%s); "
                "falling back to PaperTradingConnector",
                symbols, market.value, [c.name for c in required_capabilities],
            )
            return paper

        # Sort by tier (ascending) — lowest tier (cheapest) wins
        candidates.sort(key=lambda c: c.tier.value)
        selected = candidates[0]
        logger.debug(
            "Resolved connector %s for symbols=%s market=%s caps=%s",
            selected.connector_id, symbols, market.value,
            [c.name for c in required_capabilities],
        )
        return selected

    # ── Filter helpers ────────────────────────────────────────────

    def _filter_by_market(
        self, market: MarketClassification
    ) -> List[FinancialConnector]:
        """Return connectors supporting *market* (or with UNKNOWN market support)."""
        out: List[FinancialConnector] = []
        for c in self._connectors.values():
            # Paper trading supports all markets
            if c.connector_id == "paper":
                out.append(c)
                continue
            if market in c.supported_markets or not c.supported_markets:
                out.append(c)
        return out

    def _filter_by_capabilities(
        self,
        candidates: List[FinancialConnector],
        required: Set[ConnectorCapability],
    ) -> List[FinancialConnector]:
        return [c for c in candidates if required.issubset(c.capabilities)]

    def _filter_by_credentials(
        self, candidates: List[FinancialConnector]
    ) -> List[FinancialConnector]:
        """Filter out connectors that require credentials but have none set."""
        out: List[FinancialConnector] = []
        for c in candidates:
            if not c.requires_credentials:
                out.append(c)
                continue
            if c.connector_id in self._credentials:
                out.append(c)
        return out

    @staticmethod
    def _verify_capabilities(
        conn: FinancialConnector,
        required: Set[ConnectorCapability],
    ) -> None:
        missing = required - conn.capabilities
        if missing:
            raise ValueError(
                f"Connector '{conn.connector_id}' missing required capabilities: "
                f"{[c.name for c in missing]}"
            )


# ── Module-level singleton ────────────────────────────────────────

_global_registry: Optional[ConnectorRegistry] = None


def get_connector_registry() -> ConnectorRegistry:
    """Return the global ConnectorRegistry singleton.

    The global registry is lazily initialized with the default
    PaperTradingConnector.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ConnectorRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (for test isolation)."""
    global _global_registry
    _global_registry = None


async def resolve_connector(
    symbols: List[str],
    required_capabilities: Optional[Set[ConnectorCapability]] = None,
    preferred: str = "auto",
    require_realtime: bool = False,
    max_latency_tier: Optional[ConnectorTier] = None,
) -> FinancialConnector:
    """Module-level convenience: resolve via the global registry."""
    return await get_connector_registry().resolve_connector(
        symbols=symbols,
        required_capabilities=required_capabilities,
        preferred=preferred,
        require_realtime=require_realtime,
        max_latency_tier=max_latency_tier,
    )
