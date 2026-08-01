from laap.orchestration.kernel import OrchestrationKernel
from laap.orchestration.meta_agent import MetaAgent, sync_skills_as_capabilities
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType
from laap.orchestration.cognitive_bus import ArisCognitiveBus
from laap.orchestration.body import HermesBodyInterface

__all__ = [
    "AetherAddress",
    "AetherMessage",
    "ArisCognitiveBus",
    "HermesBodyInterface",
    "MessageType",
    "MetaAgent",
    "OrchestrationKernel",
    "sync_skills_as_capabilities",
]

# DSL is kept optional: the module may be temporarily incomplete in this
# workspace, so a failed import must not break the rest of the orchestration
# package (actor, kernel, primitives, dst, etc.).
try:
    from laap.orchestration.dsl import (
        LAAPBuilder,
        LAAPExpr,
        ActNode,
        GuardNode,
        InferNode,
        LoopNode,
        ParNode,
        SeqNode,
        SkillNode,
        act,
        compile_workflow,
        guard,
        infer,
        laap_cli_compile,
        loop,
        par,
        seq,
        skill,
    )
except Exception:  # pragma: no cover - dsl may be incomplete during development
    LAAPBuilder = None  # type: ignore[misc, assignment]
    LAAPExpr = None  # type: ignore[misc, assignment]
    ActNode = None  # type: ignore[misc, assignment]
    GuardNode = None  # type: ignore[misc, assignment]
    InferNode = None  # type: ignore[misc, assignment]
    LoopNode = None  # type: ignore[misc, assignment]
    ParNode = None  # type: ignore[misc, assignment]
    SeqNode = None  # type: ignore[misc, assignment]
    SkillNode = None  # type: ignore[misc, assignment]
    act = None  # type: ignore[misc, assignment]
    compile_workflow = None  # type: ignore[misc, assignment]
    guard = None  # type: ignore[misc, assignment]
    infer = None  # type: ignore[misc, assignment]
    laap_cli_compile = None  # type: ignore[misc, assignment]
    loop = None  # type: ignore[misc, assignment]
    par = None  # type: ignore[misc, assignment]
    seq = None  # type: ignore[misc, assignment]
    skill = None  # type: ignore[misc, assignment]
else:
    __all__.extend(
        [
            "LAAPBuilder",
            "LAAPExpr",
            "InferNode",
            "ActNode",
            "SkillNode",
            "SeqNode",
            "ParNode",
            "GuardNode",
            "LoopNode",
            "infer",
            "act",
            "skill",
            "seq",
            "par",
            "guard",
            "loop",
            "compile_workflow",
            "laap_cli_compile",
        ]
    )
