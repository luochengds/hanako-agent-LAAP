"""LAAP Protocol Layer — 数字生命体协议栈"""
from __future__ import annotations

from laap.protocol.laap_ui import (
    Component, ComponentType, ComponentFactory, LayoutTree, RenderEngine, 
    ThemeDefinition, UIComponent, UILayout, UIRenderer
)
from laap.protocol.laap_sync import (
    CRDTDocument, VersionVector, ConflictResolver, StateSynchronizer
)
from laap.protocol.laap_com import Message, MessageBus
from laap.protocol.laap_id import IdentityDocument, IdentityRegistry
from laap.protocol.laap_life import LifecycleStateMachine, StateMachine
from laap.protocol.laap_mem import ForgettingCurve
from laap.protocol.memory_curve import MemoryCurve, MemoryCurvePoint
from laap.protocol.laap_evo import (
    EvolutionProtocol, MutationProposal, MutationType,
    ExperiencePacket, SelectionReport, SelectionStatus,
)
from laap.protocol.laap_coop import (
    CooperationProtocol, TaskAssignment, SharedFact, FactScope,
    NegotiationResult, NegotiationOutcome, TaskStatus,
)
from laap.protocol.laap_tool import (
    ToolProtocol, LaapTool, ToolPermissions, PermissionLevel,
    ToolCategory, ToolInvocationResult,
)
