"""LAAP FinQuant Domain SDK — Tool implementations.

Each tool bridges an LLM function-call to the underlying SDK capability:
harness functions (zero-token), cognitive actors (via the CognitiveBus),
connector queries, or platform introspection. Tools return JSON strings
(the OpenAI tool-result convention).

Design rules:
- Tools NEVER bypass the safety policy. ``place_order`` routes through
  the Executor actor's hard gate.
- Tools are defensive: any exception becomes a structured ``{ok:false,
  error}`` result so the LLM can recover.
- Tools are async where the underlying call is async; the dispatcher
  awaits uniformly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

from laap.domain_sdks.finquant.agent.platform_introspection import (
    PlatformIntrospector,
)
from laap.domain_sdks.finquant.topics import (
    ANALYSIS_REQUEST,
    EXECUTION_ORDER,
    MARKET_QUOTE,
    STRATEGY_PROPOSED,
)

logger = logging.getLogger("laap.domain_sdks.finquant.agent.tools")


def _ok(**kw) -> str:
    kw["ok"] = True
    return json.dumps(kw, default=str, ensure_ascii=False)


def _err(error: str, **kw) -> str:
    kw["ok"] = False
    kw["error"] = error
    return json.dumps(kw, default=str, ensure_ascii=False)


class ToolDispatcher:
    """Dispatches tool calls to the right SDK surface.

    Holds references to the same SDK objects the introspector reads, plus
    a memory store for the ``recall`` tool. Stateless across turns except
    for the memory ring buffer.
    """

    def __init__(
        self,
        harness_registry: Any = None,
        actor_system: Any = None,
        cognitive_bus: Any = None,
        connector: Any = None,
        safety_policy: Any = None,
        species_library: Any = None,
        introspector: Optional[PlatformIntrospector] = None,
        voice_interface: Any = None,
    ) -> None:
        self.harness_registry = harness_registry
        self.actor_system = actor_system
        self.cognitive_bus = cognitive_bus
        self.connector = connector
        self.safety_policy = safety_policy
        self.species_library = species_library
        self.introspector = introspector or PlatformIntrospector(
            harness_registry=harness_registry,
            actor_system=actor_system,
            connector=connector,
            safety_policy=safety_policy,
            species_library=species_library,
            cognitive_bus=cognitive_bus,
        )
        self.voice_interface = voice_interface
        # Lightweight conversation memory: list of {ts, role, content, tags}
        self._memory: list = []
        self._max_memory = 200

    # ── Public dispatch ───────────────────────────────────────────

    async def dispatch(self, name: str, args: Dict[str, Any]) -> str:
        """Route a tool call to its handler. Always returns a JSON string."""
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return _err(f"unknown_tool:{name}")
        try:
            result = handler(args)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str):
                return result
            return _ok(result=result)
        except Exception as exc:
            logger.warning("tool %s failed: %s: %s", name, type(exc).__name__, exc)
            return _err(f"{type(exc).__name__}: {exc}", tool=name)

    def remember(self, role: str, content: str, tags: Optional[list] = None) -> None:
        """Record a conversation turn into the agent's local memory."""
        self._memory.append(
            {
                "ts": time.time(),
                "role": role,
                "content": content,
                "tags": tags or [],
            }
        )
        if len(self._memory) > self._max_memory:
            del self._memory[: len(self._memory) - self._max_memory]

    # ── Market data ───────────────────────────────────────────────

    async def _tool_get_market_data(self, args: Dict[str, Any]) -> str:
        symbol = args.get("symbol", "")
        interval = args.get("interval", "1d")
        limit = int(args.get("limit", 100))
        if not symbol:
            return _err("symbol required")
        if self.connector is None:
            return _err("no_connector_configured")
        # Prefer connector.get_ohlcv; fall back to harness function.
        get_ohlcv = getattr(self.connector, "get_ohlcv", None)
        if callable(get_ohlcv):
            import inspect

            if inspect.iscoroutinefunction(get_ohlcv):
                bars = await get_ohlcv(symbol, interval=interval, limit=limit)
            else:
                bars = get_ohlcv(symbol, interval=interval, limit=limit)
        elif self.harness_registry is not None:
            bars = await self.harness_registry.invoke(
                "finquant.data.get_ohlcv",
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
        else:
            return _err("no_market_data_source")
        # Serialize bars (may be dataclasses or dicts)
        out = []
        for b in bars or []:
            if isinstance(b, dict):
                out.append(b)
            else:
                out.append(
                    {
                        "timestamp": getattr(b, "timestamp", None),
                        "open": getattr(b, "open", None),
                        "high": getattr(b, "high", None),
                        "low": getattr(b, "low", None),
                        "close": getattr(b, "close", None),
                        "volume": getattr(b, "volume", None),
                    }
                )
        return _ok(symbol=symbol, interval=interval, bars=out, count=len(out))

    async def _tool_get_quote(self, args: Dict[str, Any]) -> str:
        symbol = args.get("symbol", "")
        if not symbol or self.connector is None:
            return _err("symbol and connector required")
        get_quote = getattr(self.connector, "get_quote", None)
        if not callable(get_quote):
            return _err("connector_does_not_support_quotes")
        import inspect

        if inspect.iscoroutinefunction(get_quote):
            tick = await get_quote(symbol)
        else:
            tick = get_quote(symbol)
        if tick is None:
            return _err("no_quote_returned")
        return _ok(
            symbol=symbol,
            price=getattr(tick, "price", None),
            bid=getattr(tick, "bid", None),
            ask=getattr(tick, "ask", None),
            volume=getattr(tick, "volume", None),
            timestamp=getattr(tick, "timestamp", None),
        )

    # ── Indicators / analysis ─────────────────────────────────────

    async def _tool_compute_indicators(self, args: Dict[str, Any]) -> str:
        data = args.get("data", [])
        indicators = args.get("indicators", [{"name": "sma", "period": 20}])
        if not data:
            return _err("data required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.indicators.compute",
            data=data,
            indicators=indicators,
        )
        return _ok(indicators=indicators, result=result)

    async def _tool_detect_regime(self, args: Dict[str, Any]) -> str:
        data = args.get("data", [])
        window = int(args.get("window", 20))
        if not data:
            return _err("data required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.indicators.detect_regime",
            data=data,
            window=window,
        )
        return _ok(window=window, regime=result)

    # ── Risk ──────────────────────────────────────────────────────

    async def _tool_compute_var(self, args: Dict[str, Any]) -> str:
        returns = args.get("returns", [])
        confidence = float(args.get("confidence", 0.95))
        if not returns:
            return _err("returns required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.risk.var",
            returns=returns,
            confidence=confidence,
        )
        return _ok(confidence=confidence, var=result)

    async def _tool_stress_test(self, args: Dict[str, Any]) -> str:
        positions = args.get("positions", [])
        scenario = args.get("scenario", "market_crash")
        shock_pct = args.get("shock_pct")
        if not positions:
            return _err("positions required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.risk.stress_test",
            positions=positions,
            scenario=scenario,
            shock_pct=shock_pct,
        )
        return _ok(scenario=scenario, result=result)

    async def _tool_kelly_criterion(self, args: Dict[str, Any]) -> str:
        win_prob = float(args.get("win_prob", 0))
        win_loss_ratio = float(args.get("win_loss_ratio", 1))
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.risk.kelly_criterion",
            win_prob=win_prob,
            win_loss_ratio=win_loss_ratio,
        )
        return _ok(win_prob=win_prob, win_loss_ratio=win_loss_ratio, kelly=result)

    # ── Statistics ────────────────────────────────────────────────

    async def _tool_compute_statistics(self, args: Dict[str, Any]) -> str:
        metric = args.get("metric", "sharpe")
        values = args.get("values", [])
        risk_free_rate = float(args.get("risk_free_rate", 0.0))
        if not values:
            return _err("values required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        # Map metric → harness function name.
        metric_to_fn = {
            "sharpe": "finquant.statistics.sharpe_ratio",
            "sortino": "finquant.statistics.sortino_ratio",
            "max_drawdown": "finquant.statistics.max_drawdown",
            "zscore": "finquant.statistics.zscore_test",
            "adf": "finquant.statistics.adf_test",
        }
        fn_name = metric_to_fn.get(metric)
        if fn_name is None:
            return _err(f"unknown_metric:{metric}")
        result = await self.harness_registry.invoke(
            fn_name, values=values, risk_free_rate=risk_free_rate
        )
        return _ok(metric=metric, result=result)

    # ── Backtest ──────────────────────────────────────────────────

    async def _tool_run_backtest(self, args: Dict[str, Any]) -> str:
        strategy_id = args.get("strategy_id", "")
        symbol = args.get("symbol", "")
        data = args.get("data", [])
        params = args.get("params", {})
        initial_capital = float(args.get("initial_capital", 100000))
        commission_bps = float(args.get("commission_bps", 5))
        if not strategy_id or not data:
            return _err("strategy_id and data required")
        if self.harness_registry is None:
            return _err("harness_registry_not_configured")
        result = await self.harness_registry.invoke(
            "finquant.backtest.run",
            strategy_id=strategy_id,
            symbol=symbol,
            data=data,
            params=params,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
        )
        return _ok(strategy_id=strategy_id, symbol=symbol, backtest=result)

    # ── Strategy / species ────────────────────────────────────────

    async def _tool_list_strategies(self, args: Dict[str, Any]) -> str:
        category = args.get("category", "all")
        try:
            from laap.domain_sdks.finquant.species import ALL_SPECIES_TEMPLATES

            out = []
            for t in ALL_SPECIES_TEMPLATES:
                cat = getattr(t, "category", "") or t.get("category", "")
                if category != "all" and cat != category:
                    continue
                out.append(
                    {
                        "id": getattr(t, "id", "") or t.get("id", ""),
                        "category": cat,
                        "description": (getattr(t, "description", "") or t.get("description", ""))[:200],
                        "parameters": getattr(t, "parameters", []) or t.get("parameters", []),
                    }
                )
            return _ok(category=category, strategies=out, count=len(out))
        except Exception as exc:
            return _err(f"list_strategies_failed:{exc}")

    # ── Portfolio / execution ─────────────────────────────────────

    async def _tool_get_portfolio(self, args: Dict[str, Any]) -> str:
        if self.connector is None:
            return _err("no_connector_configured")
        portfolio, positions = await self.introspector.read_portfolio_async()
        return _ok(portfolio=portfolio, positions=positions)

    async def _tool_place_order(self, args: Dict[str, Any]) -> str:
        """Place an order via the Executor actor (with hard safety gate).

        Two paths:
          1. If we have an actor_system + cognitive_bus, publish an
             EXECUTION_ORDER message — the Executor actor picks it up,
             runs the safety gate, and emits EXECUTION_FILL / REJECTED.
             We await the reply with a timeout.
          2. Fallback: call the connector directly (still gated by
             safety_policy.pre_execution_gate if a policy is set).
        """
        symbol = args.get("symbol", "")
        side = args.get("side", "buy")
        size = float(args.get("size", 0))
        order_type = args.get("order_type", "market")
        limit_price = args.get("limit_price")
        stop_price = args.get("stop_price")
        time_in_force = args.get("time_in_force", "day")
        if not symbol or size <= 0:
            return _err("symbol and positive size required")

        order_payload = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "time_in_force": time_in_force,
            "client_order_id": f"agent-{uuid.uuid4().hex[:8]}",
        }

        # Path 1: actor-system route (preferred — full safety gate + bus).
        if self.actor_system is not None and self.cognitive_bus is not None:
            try:
                result = await self._place_via_actor(order_payload)
                return result
            except Exception as exc:
                logger.warning("actor route failed, falling back: %s", exc)

        # Path 2: direct connector + manual safety gate.
        if self.connector is None:
            return _err("no_connector_configured")
        if self.safety_policy is not None:
            try:
                self.safety_policy.pre_execution_gate(order_payload, {})
            except Exception as breach:
                return _err(
                    f"safety_breach:{getattr(breach,'message',str(breach))}",
                    violation=getattr(breach, "violation", ""),
                )
        from laap.domain_sdks.finquant.connectors.base import Order, OrderSide, OrderType
        from laap.domain_sdks.finquant.connectors.base import OrderSide as _OS

        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            size=size,
            order_type=OrderType(order_type),
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            client_order_id=order_payload["client_order_id"],
        )
        try:
            res = await self.connector.place_order(order)
        except Exception as exc:
            return _err(f"connector_error:{exc}")
        status = getattr(res, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status)
        return _ok(
            order_id=getattr(res, "order_id", ""),
            status=status_val,
            filled_size=getattr(res, "filled_size", 0.0),
            avg_fill_price=getattr(res, "avg_fill_price", None),
            commission=getattr(res, "commission", 0.0),
            order=order_payload,
        )

    async def _place_via_actor(self, order_payload: Dict[str, Any]) -> str:
        """Publish EXECUTION_ORDER and await the Executor actor's reply."""
        from laap.orchestration.primitives import AetherMessage, MessageType

        # Set up a one-shot reply listener.
        reply_future: asyncio.Future = asyncio.get_running_loop().create_future()
        reply_topic_map = {
            "finquant.execution.fill": "filled",
            "finquant.execution.rejected": "rejected",
        }

        async def _reply_handler(topic: str, message: Any) -> None:
            if not reply_future.done():
                reply_future.set_result((topic, message))

        # Subscribe to both fill & rejected topics.
        sub = getattr(self.cognitive_bus, "subscribe", None)
        if callable(sub):
            for t in reply_topic_map:
                await sub(t, _reply_handler)

        # Publish the order request.
        msg = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender="finquant_agent",
            payload={"topic": EXECUTION_ORDER, "order": order_payload, "portfolio": {}},
        )
        publish = getattr(self.cognitive_bus, "publish", None)
        if callable(publish):
            await publish(EXECUTION_ORDER, msg)
        else:
            return _err("bus_has_no_publish")

        try:
            topic, reply = await asyncio.wait_for(reply_future, timeout=15.0)
        except asyncio.TimeoutError:
            return _err("execution_timeout_no_actor_reply")
        finally:
            unsub = getattr(self.cognitive_bus, "unsubscribe", None)
            if callable(unsub):
                for t in reply_topic_map:
                    try:
                        await unsub(t, _reply_handler)
                    except Exception:
                        pass

        payload = getattr(reply, "payload", reply) or {}
        outcome = reply_topic_map.get(topic, "unknown")
        if outcome == "filled":
            return _ok(
                status="filled",
                order_id=payload.get("order_id", ""),
                filled_size=payload.get("filled_size", 0.0),
                avg_fill_price=payload.get("avg_fill_price"),
                commission=payload.get("commission", 0.0),
                order=order_payload,
            )
        return _err(
            f"rejected:{payload.get('reason', 'unknown')}",
            violation=payload.get("violation", ""),
            message=payload.get("message", ""),
            order=order_payload,
        )

    # ── Platform introspection ────────────────────────────────────

    async def _tool_get_platform_state(self, args: Dict[str, Any]) -> str:
        # Refresh live portfolio for the snapshot.
        portfolio, positions = await self.introspector.read_portfolio_async()
        snap = self.introspector.snapshot(
            agent_stats={
                "memory_entries": len(self._memory),
            }
        )
        snap.portfolio = portfolio
        snap.positions = positions
        return _ok(snapshot=snap.to_dict())

    # ── Voice ─────────────────────────────────────────────────────

    async def _tool_speak(self, args: Dict[str, Any]) -> str:
        text = args.get("text", "")
        interrupt = args.get("interrupt", True)
        if not text:
            return _err("text required")
        if self.voice_interface is None:
            return _ok(spoken=False, reason="no_voice_interface")
        try:
            await self.voice_interface.speak(text, interrupt=interrupt)
            return _ok(spoken=True, text=text)
        except Exception as exc:
            return _err(f"tts_failed:{exc}")

    # ── Memory ────────────────────────────────────────────────────

    async def _tool_recall(self, args: Dict[str, Any]) -> str:
        query = (args.get("query", "") or "").lower()
        if not query:
            return _ok(memories=self._memory[-20:])
        hits = []
        for m in self._memory:
            content = (m.get("content", "") or "").lower()
            tags = [str(t).lower() for t in m.get("tags", [])]
            if query in content or any(query in t for t in tags):
                hits.append(m)
        return _ok(query=query, matches=hits[-20:], count=len(hits))


__all__ = ["ToolDispatcher"]
