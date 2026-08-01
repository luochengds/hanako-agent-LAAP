"""LAAP — Memory System"""

import logging
logger = logging.getLogger(__name__)

try:
    from laap.memory.hierarchical import HierarchicalMemory, MemoryItem, Skill, Reflection
except ImportError:
    pass  # 可选模块，降级处理
from laap.memory.persistent import PersistentMemoryEngine, MemoryEntry
from laap.memory.provider import MemoryProvider
from laap.memory.manager import MemoryManager
from laap.memory.long_term import (
    LongTermMemory, MemoryEntry as LTMMemoryEntry, 
    MemoryType, ProceduralMemory, ProceduralStep
)
try:
    from laap.memory.providers.builtin import BuiltinMemoryProvider
except ImportError:
    pass  # 可选模块，降级处理

# ── Phase 3: 记忆生命周期（遗忘/巩固） ──
try:
    from laap.memory.forgetting import (
        ForgettingEngine, ForgettingScheduler, ForgettingAudit,
        ActivationCalculator, ForgettingCurve,
        LifecyclePolicy, MemoryLifecycle, LifecycleTransition,
    )
    from laap.memory.consolidation import ConsolidationEngine, ConsolidationReport
except ImportError:
    pass  # 可选模块，降级处理

# ── Phase 3: 时间锚定 / 知识图谱 / 多模态 / 夜间周期 ──
try:
    from laap.memory.temporal import (
        TemporalAnchor, TemporalType,
        anchor_entry, get_anchor,
        filter_active, filter_by_time_window, sort_by_time, build_timeline,
    )
    from laap.memory.knowledge_graph import KnowledgeGraph, Triple, extract_triples
    from laap.memory.multimodal import MultimodalMemoryStore, MultimodalMemory, Modality
    from laap.memory.nightly_cycle import NightlyCycleScheduler
except ImportError:
    pass  # 可选模块，降级处理

# ── 生命周期集成层（LongTermMemory × 遗忘引擎） ──
try:
    from laap.memory.lifecycle_integration import (
        LifecycleAwareLongTermMemory,
        migrate_schema,
        memory_loader, memory_saver,
        attach_nightly_cycle,
    )
except ImportError:
    pass  # 可选模块，降级处理

__all__ = [
    # Hierarchical Memory
    "HierarchicalMemory", "MemoryItem", "Skill", "Reflection",
    # Persistent Memory
    "PersistentMemoryEngine", "MemoryEntry",
    # Provider & Manager
    "MemoryProvider", "MemoryManager",
    # Long-Term Memory (Phase 2)
    "LongTermMemory", "LTMMemoryEntry", "MemoryType", "ProceduralMemory", "ProceduralStep",
    # Builtin Provider
    "BuiltinMemoryProvider",
    # Phase 3: 遗忘/巩固
    "ForgettingEngine", "ForgettingScheduler", "ForgettingAudit",
    "ActivationCalculator", "ForgettingCurve",
    "LifecyclePolicy", "MemoryLifecycle", "LifecycleTransition",
    "ConsolidationEngine", "ConsolidationReport",
    # Phase 3: 时间/图谱/多模态/周期
    "TemporalAnchor", "TemporalType",
    "anchor_entry", "get_anchor",
    "filter_active", "filter_by_time_window", "sort_by_time", "build_timeline",
    "KnowledgeGraph", "Triple", "extract_triples",
    "MultimodalMemoryStore", "MultimodalMemory", "Modality",
    "NightlyCycleScheduler",
    # Phase 3: 生命周期集成层
    "LifecycleAwareLongTermMemory",
    "migrate_schema",
    "memory_loader", "memory_saver",
    "attach_nightly_cycle",
]
