"""
Skill Tools — Agent-accessible skill management (Hermes-compatible)

Tools:
  skills_list     — List available skills, optionally filtered by category
  skill_view      — View a skill's full content
  skill_manage    — Create, edit, patch, delete skills
  skill_search    — Search skills by name, description, or tags
"""

from __future__ import annotations
import json, logging, os, re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.tools.skills")

_SKILLS_DIR = Path.home() / ".laap" / "skills"


def _get_engine():
    """Get the skill engine (lazy import to avoid circular deps)."""
    from laap.skills.engine import SkillEngine
    engine = SkillEngine()
    builtin = Path(__file__).resolve().parent.parent.parent / "skills" / "builtin"
    if builtin.is_dir():
        engine.add_dir(builtin)
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    engine.add_dir(_SKILLS_DIR)
    engine.discover()
    return engine


def skills_list(category: str = "") -> str:
    """List all available skills, optionally filtered by category."""
    try:
        engine = _get_engine()
        if category:
            skills = [s.to_dict() for s in engine.get_by_category(category)]
        else:
            skills = [s.to_dict() for s in engine.get_all()]
        return json.dumps({
            "skills": skills,
            "total": len(skills),
            "category": category or "all",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def skill_view(name: str) -> str:
    """View a skill's full content including frontmatter and body."""
    try:
        engine = _get_engine()
        skill = engine.get(name)
        if not skill:
            return json.dumps({"error": f"Skill '{name}' not found"})
        result = {
            "name": skill.name,
            "description": skill.description,
            "version": skill.version,
            "category": skill.category,
            "tags": skill.tags,
            "body": skill.body[:5000],
            "body_size": len(skill.body),
            "path": str(skill.path) if skill.path else "",
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def skill_manage(action: str, name: str = "", content: str = "",
                  description: str = "", category: str = "general",
                  tags: str = "") -> str:
    """Create, edit, patch, or delete skills.

    Actions:
      create      — Create a new skill with given name and content
      edit        — Replace skill content entirely
      patch       — Append/update specific sections
      delete      — Remove a skill
    """
    try:
        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        target = _SKILLS_DIR / _slug(name)
        target.mkdir(parents=True, exist_ok=True)

        if action == "delete":
            if target.exists():
                import shutil
                shutil.rmtree(target, ignore_errors=True)
                return json.dumps({"success": True, "action": "delete", "name": name})
            return json.dumps({"error": f"Skill '{name}' not found"})

        if action in ("create", "edit"):
            # Build full SKILL.md with frontmatter
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            fm_lines = ["---", f"name: {name}", f"description: {description or name}",
                        f"category: {category}", f"version: 1.0.0"]
            if tag_list:
                fm_lines.append(f"tags: [{', '.join(tag_list)}]")
            fm_lines.append("---")
            full_content = "\n".join(fm_lines) + "\n\n" + content
            (target / "SKILL.md").write_text(full_content, encoding="utf-8")
            return json.dumps({"success": True, "action": action, "name": name,
                               "path": str(target / "SKILL.md"),
                               "body_size": len(content)}, ensure_ascii=False)

        if action == "patch":
            skill_path = target / "SKILL.md"
            existing = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
            # Append content as new section
            new_content = existing + "\n\n" + content.strip()
            skill_path.write_text(new_content, encoding="utf-8")
            return json.dumps({"success": True, "action": "patch", "name": name}, ensure_ascii=False)

        return json.dumps({"error": f"Unknown action: {action}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def skill_search(query: str) -> str:
    """Search skills by name, description, or tags."""
    try:
        engine = _get_engine()
        results = engine.search(query)
        return json.dumps({
            "query": query,
            "results": [s.to_dict() for s in results],
            "total": len(results),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _slug(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    return re.sub(r"-+", "-", name).strip("-")


TOOL_DEFS = [
    {"name": "skills_list",
     "fn": lambda **kw: skills_list(kw.get("category", "")),
     "desc": "List available skills, optionally filtered by category (use 'all' for everything)",
     "params": {"category": {"type": "string"}}},
    {"name": "skill_view",
     "fn": lambda **kw: skill_view(kw.get("name", "")),
     "desc": "View full content of a specific skill",
     "params": {"name": {"type": "string"}}, "req": ["name"]},
    {"name": "skill_manage",
     "fn": lambda **kw: skill_manage(kw.get("action", ""), kw.get("name", ""),
                                      kw.get("content", ""), kw.get("description", ""),
                                      kw.get("category", "general"), kw.get("tags", "")),
     "desc": "Create, edit, patch, or delete skills (action=create|edit|patch|delete)",
     "params": {"action": {"type": "string", "enum": ["create", "edit", "patch", "delete"]},
                "name": {"type": "string"}, "content": {"type": "string"},
                "description": {"type": "string"}, "category": {"type": "string"},
                "tags": {"type": "string"}}, "req": ["action", "name"]},
    {"name": "skill_search",
     "fn": lambda **kw: skill_search(kw.get("query", "")),
     "desc": "Search skills by name, description, or tags",
     "params": {"query": {"type": "string"}}, "req": ["query"]},
]
