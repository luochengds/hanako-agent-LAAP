"""LAAP Skills System

Components:
- skill: Skill dataclass
- loader: load_skill() — load a single skill directory
- engine: SkillEngine — discover, load, version, and hot-reload skills
- manager: SkillManager — high-level CRUD for skills
- system_prompt: build_system_prompt() — Hermes-style tiered prompt assembly
- hub: discover remote skills from GitHub registries
- registry: SkillRegistry — lightweight registration
"""

from laap.skills.engine import SkillEngine
from laap.skills.skill import Skill
from laap.skills.manager import SkillManager
from laap.skills.system_prompt import build_system_prompt, build_initial_system_prompt

__all__ = [
    "Skill",
    "SkillEngine",
    "SkillManager",
    "build_system_prompt",
    "build_initial_system_prompt",
]
