"""LAAPRuntime — 独立运行全套 LAAP 数字生命体框架的 Runtime 模式。

使用场景：
    想要在自己的 Python 项目中直接用 LAAP 的 Actor 系统、
    Petri 网工作流引擎、PSI 状态机，而不需要外部 Agent。

用法::

    from laap import LAAPRuntime

    runtime = LAAPRuntime()

    # ── 创建 Actor ──
    actor = runtime.spawn("worker", capabilities=[
        Capability(name="code", confidence=0.9),
    ])
    actor.on(MessageType.INVOKE, my_handler)

    # ── 构建 Petri 网工作流 ──
    workflow = seq(
        act("search_files", {"pattern": "*.py"}, output_key="files"),
        act("read_file", {"path": "{{files.0}}"}, output_key="content"),
    )
    net = runtime.compile(workflow)
    await runtime.run_workflow(net)

    # ── 触发 PSI 认知循环 ──
    result = await runtime.cognize("用户输入")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Callable, Awaitable

from laap.orchestration.actor import (
    ActorSystem,
    AgentCell,
    Capability,
    ActorState,
)
from laap.orchestration.petri import (
    ColoredToken,
    PetriNet,
    PetriPlace,
    PetriTransition,
    TokenColor,
)
from laap.orchestration.primitives import (
    AetherAddress,
    AetherMessage,
    MessageType,
    MessageRouter,
)
from laap.orchestration.kernel import OrchestrationKernel
from laap.orchestration.meta_agent import MetaAgent
from laap.orchestration.psi import PSIAgent
from laap.orchestration.cognitive_bus import ArisCognitiveBus

try:
    from laap.orchestration.dsl import (
        seq, par, act, guard, loop, infer, skill,
        compile_workflow, LAAPBuilder,
    )
    _HAS_DSL = True
except ImportError:
    _HAS_DSL = False
    seq = par = act = guard = loop = infer = skill = None
    compile_workflow = LAAPBuilder = None

logger = logging.getLogger("laap.sdk.runtime")


class LAAPRuntime:
    """LAAP 运行时 — 在自己的 Python 项目中使用完整的 LAAP 框架。

    封装了 ActorSystem, PetriNet, OrchestrationKernel, MetaAgent, PSI,
    以及 DSL 编译器。提供一个统一的入口来管理 LAAP 组件的生命周期。

    Attributes:
        system: 底层 ActorSystem 实例。
        kernel: 绑定的 OrchestrationKernel（如已创建）。
        meta: MetaAgent 实例（如已启用）。
        psi: PSIAgent 实例（如已启用）。
    """

    def __init__(
        self,
        system_id: str = "laap-runtime",
        node_id: str = "local",
        enable_meta: bool = False,
        enable_psi: bool = False,
        enable_remote: bool = False,
        host: str = "127.0.0.1",
        port: int = 7777,
        seed_nodes: Optional[list[str]] = None,
    ):
        self.system_id = system_id
        self.system = ActorSystem(
            system_id=system_id,
            node_id=node_id,
            host=host,
            port=port,
            seed_nodes=seed_nodes,
            enable_remote=enable_remote,
        )
        self.kernel: Optional[OrchestrationKernel] = None
        self.meta: Optional[MetaAgent] = None
        self.psi: Optional[PSIAgent] = None
        self._cognitive_bus: Optional[ArisCognitiveBus] = None
        self._networks: dict[str, PetriNet] = {}
        self._tasks: list[asyncio.Task] = []

        # ── Domain SDK infrastructure ───────────────────────────────
        self._harness_registry = _new_harness_registry()
        self._species_library = _new_species_library()
        self._safety_policies: dict[str, Any] = {}
        self._domain_registry = _new_domain_registry()
        self._mounted_domains: dict[str, Any] = {}

        if enable_meta:
            self.meta = MetaAgent(actor_system=self.system)
        if enable_psi:
            self.psi = PSIAgent("psi_core")

    # ── Actor 管理 ────────────────────────────────────────────────────

    def spawn(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        capabilities: Optional[list[Capability]] = None,
        max_retries: int = 3,
    ) -> AgentCell:
        """创建并启动一个新的 Aether Actor。"""
        return self.system.spawn(
            actor_id=actor_id,
            host=host,
            supervisor=supervisor,
            capabilities=capabilities,
            max_retries=max_retries,
        )

    def send(self, message: AetherMessage) -> None:
        """发送 AetherMessage 到目标 Actor。"""
        asyncio.create_task(self.system.send(message))

    def broadcast(
        self,
        message: AetherMessage,
        capability_filter: Optional[str] = None,
    ) -> None:
        """广播消息到所有匹配的 Actor。"""
        asyncio.create_task(
            self.system.broadcast(message, capability_filter=capability_filter)
        )

    def find_actors(
        self,
        capability: str,
        min_confidence: float = 0.7,
    ) -> list[tuple[AgentCell, float]]:
        """根据能力查找 Actor。"""
        return self.system.find_capable_agents(capability, min_confidence)

    # ── Petri 网工作流 ───────────────────────────────────────────────

    def create_net(self, net_id: str = "workflow") -> PetriNet:
        """创建一个空的 Petri 网。"""
        net = PetriNet(net_id)
        self._networks[net_id] = net
        return net

    def add_place(
        self,
        net: PetriNet,
        place_id: str,
        token_types: Optional[set[TokenColor]] = None,
    ) -> PetriNet:
        """向 Petri 网添加一个 Place。"""
        net.add_place(PetriPlace(place_id, token_types=token_types or {TokenColor.DATA}))
        return net

    def add_transition(
        self,
        net: PetriNet,
        transition_id: str,
        input_places: dict[str, int],
        output_places: dict[str, Any],
        action: Optional[Callable] = None,
    ) -> PetriNet:
        """向 Petri 网添加一个 Transition。"""
        net.add_transition(
            PetriTransition(
                transition_id=transition_id,
                input_places=input_places,
                output_places=output_places,
                action=action,
            )
        )
        return net

    def deposit(self, net: PetriNet, place_id: str, value: Any, color: TokenColor = TokenColor.DATA) -> None:
        """向 Petri 网的某个 Place 存入 Token。"""
        place = net.places.get(place_id)
        if place is None:
            raise ValueError(f"Unknown place: {place_id}")
        place.deposit(ColoredToken(color, value))

    async def step_net(self, net: PetriNet) -> bool:
        """推动 Petri 网前进一步，返回是否有 Transition 触发了。"""
        return await net.step()

    async def run_net(self, net: PetriNet, max_steps: int = 100) -> list[dict]:
        """全速运行 Petri 网直到没有可用 Transition。"""
        trace = []
        for _ in range(max_steps):
            stepped = await net.step()
            if not stepped:
                break
            trace.append({"step": _, "transition": "?"})
        return trace

    # ── DSL 编译（可选） ──────────────────────────────────────────────

    def compile(
        self,
        workflow_expr: Any,
        net_id: Optional[str] = None,
    ) -> tuple[PetriNet, dict, dict]:
        """编译 DSL 表达式为 Petri 网。

        Requires::

            from laap import seq, act, par, compile_workflow

        Returns:
            (net, actor_bindings, output_places) 三元组。
        """
        if not _HAS_DSL:
            raise RuntimeError(
                "DSL compiler not available; install laap with DSL dependencies"
            )
        return compile_workflow(
            workflow_expr,
            net_id=net_id or f"{self.system_id}_compiled",
            actor_system=self.system,
        )

    def build(self) -> LAAPBuilder:
        """返回 LAAPBuilder 用于链式构建工作流。"""
        if not _HAS_DSL or LAAPBuilder is None:
            raise RuntimeError("DSL builder not available")
        return LAAPBuilder()

    # ── 内核绑定 ──────────────────────────────────────────────────────

    def bind_kernel(self, net: PetriNet, kernel_id: Optional[str] = None) -> OrchestrationKernel:
        """将 ActorSystem 绑定到 Petri 网，创建内核。"""
        self.kernel = OrchestrationKernel(
            actor_system=self.system,
            petri_net=net,
            kernel_id=kernel_id,
        )
        return self.kernel

    async def run_kernel(self) -> None:
        """运行绑定的内核循环。"""
        if self.kernel is None:
            raise RuntimeError("No kernel bound; call bind_kernel() first")
        await self.kernel.run()

    # ── 认知循环 ──────────────────────────────────────────────────────

    async def cognize(
        self,
        user_input: str,
        context: Optional[dict] = None,
    ) -> dict[str, Any]:
        """通过认知总线运行完整的 PSI 认知循环。

        首次调用时会自动创建 ArisCognitiveBus。
        """
        if self._cognitive_bus is None:
            self._cognitive_bus = ArisCognitiveBus(system_id=self.system_id)
            await self._cognitive_bus.initialize()

        return await self._cognitive_bus.process(user_input, context=context)

    # ── 拓扑进化 ──────────────────────────────────────────────────────

    async def evolve(self) -> dict[str, Any]:
        """运行 MetaAgent 的进化循环（监控、招募、淘汰）。"""
        if self.meta is None:
            raise RuntimeError("MetaAgent not enabled; pass enable_meta=True")
        return await self.meta.evolve()

    # ── Domain SDK 管理 ──────────────────────────────────────────────

    def mount_domain(self, sdk: Any) -> Any:
        """Mount a domain SDK into this runtime.

        Registers the SDK's harness functions, cognitive actors, species
        templates, CognitiveBus topics, and safety policy.

        Args:
            sdk: A DomainSDKBase instance.

        Returns:
            The SDK instance (for chaining).

        Raises:
            TypeError: If sdk is not a DomainSDKBase instance.
            RuntimeError: If a domain with the same ID is already mounted.
        """
        # Lazy import to avoid circular dependency
        from laap.domain_sdk.base import DomainSDKBase

        if not isinstance(sdk, DomainSDKBase):
            raise TypeError(
                f"Expected DomainSDKBase instance, got {type(sdk).__name__}"
            )

        manifest = sdk.manifest()
        if manifest.domain_id in self._mounted_domains:
            raise RuntimeError(
                f"Domain '{manifest.domain_id}' is already mounted"
            )

        sdk.initialize(self)
        logger.info(
            "Domain SDK mounted into runtime: %s v%s",
            manifest.domain_id, manifest.version,
        )
        return sdk

    def mount_domain_by_id(self, domain_id: str) -> Any:
        """Mount a domain SDK by ID from the domain registry.

        Discovers available SDKs first if the registry is empty.

        Args:
            domain_id: The domain ID to mount (e.g. "finquant").

        Returns:
            The mounted SDK instance.

        Raises:
            KeyError: If the domain ID is not found in the registry.
        """
        if not self._domain_registry.list_domains():
            self._domain_registry.discover_all()

        sdk = self._domain_registry.get(domain_id)
        if sdk is None:
            available = self._domain_registry.list_domains()
            raise KeyError(
                f"Domain SDK '{domain_id}' not found. "
                f"Available: {available}"
            )
        return self.mount_domain(sdk)

    @property
    def harness_registry(self) -> Any:
        """The HarnessFunctionRegistry for this runtime."""
        return self._harness_registry

    @property
    def species_library(self) -> Any:
        """The SpeciesLibrary for this runtime."""
        return self._species_library

    @property
    def domain_registry(self) -> Any:
        """The DomainSDKRegistry for this runtime."""
        return self._domain_registry

    @property
    def mounted_domains(self) -> dict[str, Any]:
        """Dict of mounted domain SDKs (domain_id → sdk)."""
        return dict(self._mounted_domains)

    def list_harness_functions(self, domain: Optional[str] = None) -> list[Any]:
        """List harness functions, optionally filtered by domain."""
        return self._harness_registry.list(domain=domain)

    def list_species_templates(self, domain: Optional[str] = None) -> list[Any]:
        """List species templates, optionally filtered by domain."""
        return self._species_library.list(domain=domain)

    async def invoke_harness(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered harness function by name.

        Args:
            name: Harness function name (e.g. "finquant.indicators.compute").
            **kwargs: Arguments to pass to the function.

        Returns:
            The function's return value.
        """
        return await self._harness_registry.invoke(name, **kwargs)

    # ── 生命周期 ──────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """关闭所有组件。"""
        if self._cognitive_bus is not None:
            await self._cognitive_bus.shutdown()

        for task in self._tasks:
            if not task.done():
                task.cancel()
        await self.system.shutdown()
        logger.info("LAAPRuntime shut down")

    async def __aenter__(self) -> "LAAPRuntime":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    def __repr__(self) -> str:
        return (
            f"<LAAPRuntime system_id={self.system_id!r}"
            f" actors={len(self.system.actors)}"
            f" nets={len(self._networks)}"
            f" meta={self.meta is not None}"
            f" psi={self.psi is not None}>"
        )


# ── Domain SDK lazy-initialization helpers ─────────────────────────
# These functions lazily import the domain_sdk package to avoid circular
# imports. The domain_sdk package depends only on stdlib + laap.orchestration
# (which is already imported above), so there is no true cycle — but the
# import is deferred to keep `from laap import LAAPRuntime` fast.


def _new_harness_registry() -> Any:
    """Create a HarnessFunctionRegistry (lazy import)."""
    from laap.domain_sdk.harness_function import HarnessFunctionRegistry
    return HarnessFunctionRegistry()


def _new_species_library() -> Any:
    """Create a SpeciesLibrary (lazy import)."""
    from laap.domain_sdk.species import SpeciesLibrary
    return SpeciesLibrary()


def _new_domain_registry() -> Any:
    """Create a DomainSDKRegistry (lazy import)."""
    from laap.domain_sdk.registry import DomainSDKRegistry
    return DomainSDKRegistry()
