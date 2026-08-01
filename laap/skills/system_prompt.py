"""
System Prompt Builder — Hermes-style tiered system prompt assembly

Three tiers:
1. STABLE — Core identity, personality, constraints
2. CONTEXT — Skills, memory, platform hints (changes per session)
3. VOLATILE — Current turn context, file attachments

Inspired by Hermes agent/system_prompt.py and agent/prompt_builder.py
"""

from __future__ import annotations
import logging, platform, sys
from typing import Optional

logger = logging.getLogger("laap.skills.system_prompt")

DEFAULT_IDENTITY = """You are LAAP (Lifeform Autonomous Adaptive Protocol) Gamma — a powerful AI agent with tool-use capabilities. You are built on an adaptive cognitive architecture with autonomous tool selection, context-aware reasoning, and multi-turn ReAct planning.

CORE PRINCIPLES:
1. When asked to perform an action, USE THE APPROPRIATE TOOL. Don't just describe what you'd do — do it.
2. For complex tasks, break them down into steps using the think tool, then execute.
3. Always read files before editing them. Show the user what you're changing.
4. Write complete, working code. Test your changes when appropriate.
5. Respond in the user's language (Chinese if not specified otherwise).
6. Use the finish tool when the task is complete, providing a clear summary.

TOOL USAGE:
- File operations: read_file, write_file, edit_file, search_files
- Code: execute_command, code_execute
- Web: web_search, browser_navigate, browser_click, browser_type
- System: system_info, get_time
- Skills: skills_list, skill_view, skill_manage (create/edit skills for reuse)
- Vision: screenshot, analyze_image, ocr_image
- Planning: think, finish"""


def build_system_prompt(
    identity: str = "",
    skills_block: str = "",
    memory_block: str = "",
    platform_hints: str = "",
    additional_instructions: str = "",
) -> str:
    """Assemble a complete system prompt from parts."""
    parts = []
    parts.append(identity or DEFAULT_IDENTITY)
    if skills_block:
        parts.append(f"\n\n[AVAILABLE SKILLS]\n{skills_block}")
    if memory_block:
        parts.append(f"\n\n[CONTEXT & MEMORY]\n{memory_block}")
    if platform_hints:
        parts.append(f"\n\n[ENVIRONMENT]\n{platform_hints}")
    if additional_instructions:
        parts.append(f"\n\n[ADDITIONAL INSTRUCTIONS]\n{additional_instructions}")
    return "\n\n".join(parts)


def build_platform_hints() -> str:
    hints = [
        f"Platform: {sys.platform}",
        f"Python: {sys.version}",
        f"Host: {platform.node()}",
    ]
    try:
        import os
        terminal = os.environ.get("TERM", os.environ.get("TERM_PROGRAM", "unknown"))
        hints.append(f"Terminal: {terminal}")
    except Exception as e:
        logger.debug(f"操作失败: {e}")
    return "\n".join(hints)


def build_skills_block(engine) -> str:
    try:
        skills = engine.get_all()
        if not skills:
            return ""
        lines = ["You have the following skills available:"]
        for s in sorted(skills, key=lambda x: x.name):
            lines.append(f"  - {s.name}: {s.description[:100]}")
        lines.append("\nUse skills_list and skill_view tools to explore them.")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to build skills block: {e}")
        return ""


def build_initial_system_prompt(engine=None) -> str:
    skills_block = build_skills_block(engine) if engine else ""
    return build_system_prompt(
        skills_block=skills_block,
        platform_hints=build_platform_hints(),
    )
