"""LAAP Lifeform — 可部署、可持久化的数字生命体运行时"""

from laap.lifeform.lifeform import (
    Lifeform, LifeformConfig, LifeformState,
    PSIProfile, MemoryConfig, EngineConfig, GovernanceConfig, LanguageCortexConfig,
    EngineStatus,
)
from laap.lifeform.cli import main as cli_main

__version__ = "0.1.0"
__all__ = [
    "Lifeform", "LifeformConfig", "LifeformState",
    "PSIProfile", "MemoryConfig", "EngineConfig", "GovernanceConfig", "LanguageCortexConfig",
    "EngineStatus",
    "cli_main",
]
