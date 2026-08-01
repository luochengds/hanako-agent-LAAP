"""LAAP FinQuant Domain SDK — Domain SDK entry point.

The ``FinQuantDomainSDK`` is the concrete implementation of
``DomainSDKBase`` for the financial quantitative domain. It wires
together the FinQuant subpackages (connectors, harness, species,
actors, safety, topics) into a single mountable SDK.

Mount into a LAAPRuntime::

    from laap import LAAPRuntime
    from laap.domain_sdks.finquant import FinQuantDomainSDK

    runtime = LAAPRuntime()
    runtime.mount_domain(FinQuantDomainSDK())

    # Invoke a harness function
    result = await runtime.invoke_harness(
        "finquant.indicators.compute",
        data=[{"close": 100}, {"close": 101}, ...],
        indicators=[{"name": "sma", "period": 2}],
    )

The SDK registers:
    - 14 harness functions (finquant.* namespace)
    - 9 species templates (4 strategies + 3 analyses + 2 risk models)
    - 5 cognitive actors (MarketWatcher, Analyst, RiskManager, Strategist, Executor)
    - 15 CognitiveBus topics (finquant.* namespace)
    - FinQuantSafetyPolicy hard-gate enforcer
    - PaperTradingConnector as the default execution connector
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from laap.domain_sdk.base import DomainManifest, DomainSDKBase
from laap.domain_sdk.harness_function import HarnessFunctionRegistry
from laap.domain_sdk.species import SpeciesLibrary

from laap.domain_sdks.finquant.actors import spawn_all as _spawn_all_actors
from laap.domain_sdks.finquant.connectors import (
    PaperTradingConnector,
    get_connector_registry,
)
from laap.domain_sdks.finquant.harness import register_all as _register_harness
from laap.domain_sdks.finquant.safety.policy import FinQuantSafetyPolicy
from laap.domain_sdks.finquant.species import register_all as _register_species
from laap.domain_sdks.finquant.topics import ALL_TOPICS, TOPIC_DESCRIPTIONS

# Lazy import helpers for the financial agent (avoid hard dependency on
# an LLM API key at SDK-mount time — the agent is opt-in).
try:
    from laap.domain_sdks.finquant.agent import (
        AgentConfig as _AgentConfig,
        FinQuantAgent as _FinQuantAgent,
    )
    from laap.domain_sdks.finquant.agent.config import (
        LLMConfig as _LLMConfig,
        VoiceConfig as _VoiceConfig,
    )
    _AGENT_AVAILABLE = True
except Exception as _agent_import_exc:  # pragma: no cover - optional dep
    _AGENT_AVAILABLE = False
    _FinQuantAgent = None  # type: ignore[assignment]
    _AgentConfig = None  # type: ignore[assignment]
    _LLMConfig = None  # type: ignore[assignment]
    _VoiceConfig = None  # type: ignore[assignment]

logger = logging.getLogger("laap.domain_sdks.finquant.sdk")


class FinQuantDomainSDK(DomainSDKBase):
    """Financial Quantitative Domain SDK.

    Implements the 6 abstract methods of ``DomainSDKBase``:
        - ``manifest()``: Return FinQuant domain manifest.
        - ``register_harness_functions()``: Register 14 deterministic harness functions.
        - ``register_cognitive_actors()``: Spawn 5 cognitive actors.
        - ``register_species_templates()``: Register 9 species templates.
        - ``register_bus_topics()``: Register 15 finquant.* topics.
        - ``get_safety_policy()``: Return FinQuantSafetyPolicy.

    Args:
        safety_policy_overrides: Dict of overrides passed to
            ``FinQuantSafetyPolicy(**overrides)``. e.g.
            ``{"max_position_pct": 0.05}`` to tighten position limits.
        connector: Optional pre-configured connector instance. If None,
            a default ``PaperTradingConnector`` is used.
        auto_connect_connector: If True (default), the connector is
            connected during ``register_cognitive_actors``.
    """

    def __init__(
        self,
        safety_policy_overrides: Optional[dict] = None,
        connector: Any = None,
        auto_connect_connector: bool = True,
    ) -> None:
        self._safety_policy_overrides = dict(safety_policy_overrides or {})
        self._connector = connector
        self._auto_connect = auto_connect_connector
        self._safety_policy: Optional[FinQuantSafetyPolicy] = None
        self._harness_registry: Optional[HarnessFunctionRegistry] = None
        self._spawned_cells: dict = {}
        # References captured during registration, exposed to the agent.
        self._actor_system: Any = None
        self._cognitive_bus: Any = None
        self._species_library: Any = None

    # ── 1. Manifest ────────────────────────────────────────────────

    def manifest(self) -> DomainManifest:
        return DomainManifest(
            domain_id="finquant",
            domain_name="Financial Quantitative",
            version="1.0.0",
            description=(
                "Financial quantitative digital life agent SDK — real-time "
                "market analysis, quantitative modeling, risk assessment, "
                "and trade execution with hard safety gates."
            ),
            cognitive_actors=[
                "finquant_market_watcher",
                "finquant_analysis_analyst",
                "finquant_risk_manager",
                "finquant_strategy_strategist",
                "finquant_execution_executor",
            ],
            harness_functions=[
                "finquant.data.get_ohlcv",
                "finquant.indicators.compute",
                "finquant.indicators.detect_regime",
                "finquant.risk.var",
                "finquant.risk.stress_test",
                "finquant.risk.kelly_criterion",
                "finquant.factors.fama_french",
                "finquant.factors.cointegration",
                "finquant.statistics.zscore_test",
                "finquant.statistics.adf_test",
                "finquant.statistics.sharpe_ratio",
                "finquant.statistics.sortino_ratio",
                "finquant.statistics.max_drawdown",
                "finquant.backtest.run",
            ],
            bus_topics=list(ALL_TOPICS),
            species_categories=["strategy", "analysis", "risk_model"],
            data_sources=[
                "paper", "yahoo", "akshare", "tushare",
                "binance", "ibkr", "ctp",
            ],
            safety_policy_class=(
                "laap.domain_sdks.finquant.safety.policy.FinQuantSafetyPolicy"
            ),
            min_laap_version="1.0.0",
        )

    # ── 2. Harness functions ───────────────────────────────────────

    def register_harness_functions(self, registry: HarnessFunctionRegistry) -> None:
        """Register all 14 FinQuant harness functions into *registry*."""
        _register_harness(registry)
        self._harness_registry = registry
        logger.info(
            "Registered %d FinQuant harness functions",
            len(registry.list_names(domain="finquant")),
        )

    # ── 3. Cognitive actors ────────────────────────────────────────

    def register_cognitive_actors(self, actor_system: Any) -> None:
        """Spawn all 5 FinQuant cognitive actors into *actor_system*.

        Because ``spawn_all`` is async (actors' ``start()`` methods are
        async for forward-compatibility with async-only actor systems),
        this method handles both async and sync calling contexts:
        - If no event loop is running, uses ``asyncio.run()``.
        - If a loop is running, schedules spawn as a coroutine task
          and logs a warning (actors will attach shortly).
        """
        self._actor_system = actor_system
        connector = self._get_connector()
        if self._auto_connect and connector is not None:
            self._ensure_connector_connected(connector)

        safety_policy = self.get_safety_policy()
        harness_registry = self._harness_registry

        coro = _spawn_all_actors(
            actor_system,
            harness_registry=harness_registry,
            safety_policy=safety_policy,
            connector=connector,
        )

        try:
            asyncio.get_running_loop()
            # A loop is already running — schedule spawn in background.
            # We can't await here (this method is sync), so fire-and-forget.
            task = asyncio.ensure_future(coro)
            task.add_done_callback(self._on_spawn_done)
            logger.info(
                "FinQuant actor spawn scheduled (event loop running); "
                "actors will attach asynchronously."
            )
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            try:
                self._spawned_cells = asyncio.run(coro)
                spawned = sum(1 for c in self._spawned_cells.values() if c is not None)
                logger.info(
                    "Spawned %d/%d FinQuant cognitive actors",
                    spawned, len(self._spawned_cells),
                )
            except Exception as exc:
                logger.warning("Failed to spawn FinQuant actors: %s: %s",
                               type(exc).__name__, exc)

    @staticmethod
    def _on_spawn_done(task: asyncio.Task) -> None:
        """Callback for background spawn task completion."""
        try:
            task.result()
        except Exception as exc:
            logger.warning("Background FinQuant actor spawn failed: %s", exc)

    # ── 4. Species templates ───────────────────────────────────────

    def register_species_templates(self, library: SpeciesLibrary) -> None:
        """Register all 9 FinQuant species templates into *library*."""
        self._species_library = library
        count = _register_species(library)
        logger.info("Registered %d FinQuant species templates", count)

    # ── 5. CognitiveBus topics ─────────────────────────────────────

    def register_bus_topics(self, cognitive_bus: Any) -> None:
        """Register the finquant.* topic namespace with *cognitive_bus*.

        The CognitiveBus in LAAP doesn't have an explicit topic registry
        — topics are created implicitly when actors subscribe/publish.
        This method therefore records the FinQuant topic map on the bus
        instance (as ``_finquant_topics``) for introspection, and tries
        a best-effort registration if the bus exposes a ``register_topic``
        or ``subscribe`` method.
        """
        self._cognitive_bus = cognitive_bus
        # Always record the topic map for introspection / CLI listing
        try:
            if not hasattr(cognitive_bus, "_domain_topics"):
                cognitive_bus._domain_topics = {}
            cognitive_bus._domain_topics["finquant"] = {
                topic: TOPIC_DESCRIPTIONS.get(topic, "")
                for topic in ALL_TOPICS
            }
        except Exception:
            pass

        # Best-effort: some bus implementations support register_topic()
        if hasattr(cognitive_bus, "register_topic"):
            for topic in ALL_TOPICS:
                try:
                    cognitive_bus.register_topic(topic, TOPIC_DESCRIPTIONS.get(topic, ""))
                except Exception as exc:
                    logger.debug("register_topic(%s) failed: %s", topic, exc)

        # Best-effort: some bus implementations support subscribe()
        # — we don't subscribe here because actors handle their own
        # subscriptions in their start() methods.

        logger.info("Registered %d finquant.* CognitiveBus topics", len(ALL_TOPICS))

    # ── 6. Safety policy ───────────────────────────────────────────

    def get_safety_policy(self) -> FinQuantSafetyPolicy:
        """Return the FinQuantSafetyPolicy (lazily instantiated)."""
        if self._safety_policy is None:
            self._safety_policy = FinQuantSafetyPolicy(**self._safety_policy_overrides)
        return self._safety_policy

    # ── Public helpers ─────────────────────────────────────────────

    @property
    def connector(self) -> Any:
        """The active execution connector (default: PaperTradingConnector)."""
        return self._get_connector()

    @property
    def spawned_actors(self) -> dict:
        """Dict of {actor_id: AgentCell} from the last spawn_all call."""
        return dict(self._spawned_cells)

    def get_connector_registry(self):
        """Return the global ConnectorRegistry (for inspection / CLI)."""
        return get_connector_registry()

    # ── Financial agent (LLM-driven, opt-in) ───────────────────────

    def create_agent(
        self,
        agent_config: Optional[Any] = None,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
        persona: Optional[str] = None,
        asr_callable: Optional[Any] = None,
        tts_provider: Optional[str] = None,
        voice_interface: Optional[Any] = None,
    ) -> Any:
        """Create a :class:`FinQuantAgent` wired to this SDK's live state.

        The agent gets direct references to this SDK's harness registry,
        actor system, cognitive bus, connector, safety policy, and
        species library — so it can answer questions about the platform's
        internal state with ground truth, and execute orders through the
        same hard safety gate as the rest of the SDK.

        Args:
            agent_config: Optional pre-built :class:`AgentConfig`. If
                None, one is built from the keyword args below.
            api_key: LLM API key (required for the agent to function).
            model: LLM model name (default 'gpt-4o').
            provider: LLM provider name (default 'openai').
            base_url: LLM base URL (default OpenAI).
            persona: Optional persona text appended to the system prompt.
            asr_callable: Optional async callable for voice ASR.
            tts_provider: TTS provider name (default 'local').
            voice_interface: Optional pre-built VoiceInterface.

        Returns:
            A :class:`FinQuantAgent` instance (not yet started — call
            ``await agent.start()``).

        Raises:
            RuntimeError: if the agent subpackage failed to import.
        """
        if not _AGENT_AVAILABLE:
            raise RuntimeError(
                f"FinQuant agent subpackage is not available: {_agent_import_exc}"
            )
        cfg = agent_config or _build_agent_config(
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
            persona=persona,
            tts_provider=tts_provider,
        )
        return _FinQuantAgent(
            config=cfg,
            harness_registry=self._harness_registry,
            actor_system=self._actor_system,
            cognitive_bus=self._cognitive_bus,
            connector=self._get_connector(),
            safety_policy=self.get_safety_policy(),
            species_library=self._species_library,
            connector_registry=get_connector_registry(),
            voice_interface=voice_interface,
            asr_callable=asr_callable,
        )

    # ── Internal ───────────────────────────────────────────────────

    def _get_connector(self) -> Any:
        """Return the configured connector, defaulting to paper trading."""
        if self._connector is not None:
            return self._connector
        # Use the global registry's default paper connector
        registry = get_connector_registry()
        paper = registry.get("paper")
        if paper is None:
            paper = PaperTradingConnector()
            registry.register(paper)
        self._connector = paper
        return paper

    @staticmethod
    def _ensure_connector_connected(connector: Any) -> None:
        """Connect *connector* if it's not already connected.

        Uses asyncio.run() if no loop is running; otherwise schedules
        the connect as a background task.
        """
        async def _do_connect():
            try:
                health = await connector.health_check()
                from laap.domain_sdks.finquant.connectors.base import ConnectorHealth
                if health == ConnectorHealth.DISCONNECTED:
                    await connector.connect()
            except Exception as exc:
                logger.warning("Connector connect failed: %s: %s",
                               type(exc).__name__, exc)

        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(_do_connect())
        except RuntimeError:
            try:
                asyncio.run(_do_connect())
            except Exception as exc:
                logger.warning("Connector connect failed: %s: %s",
                               type(exc).__name__, exc)

    def __repr__(self) -> str:
        return "<FinQuantDomainSDK v1.0.0>"


def _build_agent_config(
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    persona: Optional[str] = None,
    tts_provider: Optional[str] = None,
) -> Any:
    """Build an :class:`AgentConfig` from convenience kwargs."""
    llm = _LLMConfig(
        provider=provider or "openai",
        model=model or "gpt-4o",
        api_key=api_key or "",
        base_url=base_url or "https://api.openai.com/v1",
        persona=persona or "",
    )
    voice = _VoiceConfig(
        tts_provider=tts_provider or "local",
    )
    return _AgentConfig(llm=llm, voice=voice)

