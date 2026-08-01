"""LAAP Skill Engine — discover, load, version, and hot-reload skills.

The engine scans skill directories, loads skills described by ``skill.yaml``
files, registers their capabilities with the global tool registry, and can
watch the filesystem for changes and reload skills automatically.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from laap.skills.loader import load_skill
from laap.skills.skill import Skill

logger = logging.getLogger("laap.skills.engine")


# Re-export Skill so existing imports like
# ``from laap.skills.engine import Skill`` keep working.
Skill = Skill


def _make_skill_name(name: str) -> str:
    """Normalize a skill name to a slug."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def _parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from a SKILL.md-style file."""
    content = content.lstrip("\ufeff")
    if not content.startswith("---"):
        return {}, content

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}, content

    yaml_str = content[3:end_idx].strip()
    body = content[end_idx + 3 :].strip()

    try:
        frontmatter = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError as exc:
        logger.warning("YAML parse error: %s", exc)
        frontmatter = {}

    return frontmatter, body


class SkillEngine:
    """Discovers, loads, versions, and hot-reloads skills from disk."""

    def __init__(self, skills_dir: Optional[Union[str, Path, List[Union[str, Path]]]] = None):
        self._skills: Dict[str, Skill] = {}
        self._dirs: List[Path] = []
        self._mtimes: Dict[Path, float] = {}
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        if skills_dir is not None:
            if isinstance(skills_dir, list):
                for d in skills_dir:
                    self.add_dir(d)
            else:
                self.add_dir(skills_dir)

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------
    def add_dir(self, path: Union[str, Path]) -> None:
        """Add a skill directory to scan."""
        resolved = Path(path).resolve()
        if resolved.is_dir() and resolved not in self._dirs:
            self._dirs.append(resolved)
            logger.info("Skill dir added: %s", resolved)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_all(self) -> List[str]:
        """Scan configured directories and load all ``skill.yaml`` skills.

        Returns the list of skill names loaded.
        """
        return self._load_yaml_skills()

    def discover(self) -> List[str]:
        """Scan configured directories and load all skills.

        This is the legacy entry point: it loads new ``skill.yaml`` skills and
        also falls back to parsing ``SKILL.md`` files for backward
        compatibility.
        """
        found = self._load_yaml_skills()
        found += self._load_legacy_skills()
        logger.info("Discovered %d skills", len(found))
        return found

    def _load_yaml_skills(self) -> List[str]:
        found: List[str] = []
        for d in self._dirs:
            if not d.is_dir():
                continue
            for subdir in d.iterdir():
                if not subdir.is_dir():
                    continue
                yaml_path = subdir / "skill.yaml"
                if not yaml_path.exists():
                    continue
                try:
                    skill = load_skill(subdir)
                    self._skills[skill.name] = skill
                    self._mtimes[skill.path] = yaml_path.stat().st_mtime
                    found.append(skill.name)
                except Exception as exc:
                    logger.warning("Failed to load skill from %s: %s", subdir, exc)
        return found

    def _load_legacy_skills(self) -> List[str]:
        """Load old-style SKILL.md skills for backward compatibility."""
        found: List[str] = []
        for d in self._dirs:
            if not d.is_dir():
                continue
            for skill_path in d.rglob("SKILL.md"):
                try:
                    skill = self._load_skill_md(skill_path)
                    if skill:
                        self._skills[skill.name] = skill
                        self._mtimes[skill.path] = skill_path.stat().st_mtime
                        found.append(skill.name)
                except Exception as exc:
                    logger.warning("Failed to load legacy skill %s: %s", skill_path, exc)
        return found

    def _load_skill_md(self, path: Path) -> Optional[Skill]:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        frontmatter, body = _parse_frontmatter(content)
        if not frontmatter or "name" not in frontmatter:
            return None

        name = _make_skill_name(frontmatter.get("name", path.parent.name))
        metadata = frontmatter.get("metadata", {})
        hermes_meta = metadata.get("hermes", {}) if isinstance(metadata, dict) else {}

        return Skill(
            name=name,
            description=frontmatter.get("description", ""),
            version=str(frontmatter.get("version", "1.0.0")),
            body=body,
            frontmatter=frontmatter,
            path=path,
            platform=frontmatter.get("platform", "all"),
            tags=hermes_meta.get("tags", []) if isinstance(hermes_meta, dict)
                  else frontmatter.get("tags", []),
            category=frontmatter.get("category", "general"),
            author=frontmatter.get("author", ""),
            enabled=frontmatter.get("enabled", True),
        )

    # ------------------------------------------------------------------
    # Capability registration
    # ------------------------------------------------------------------
    def register_capabilities(self) -> List[str]:
        """Register every loaded skill capability as a tool.

        Returns the list of capability names that were registered.
        """
        from laap.tools.tool_registry import _register

        registered: List[str] = []
        for skill in list(self._skills.values()):
            handlers = getattr(skill, "_handlers", {}) or {}
            for cap in skill.capabilities:
                handler = handlers.get(cap)
                if not callable(handler):
                    logger.debug(
                        "No handler for capability '%s' of skill '%s'", cap, skill.name
                    )
                    continue
                _register(
                    cap,
                    handler,
                    "skill",
                    skill.description or f"Skill capability: {cap}",
                    overwrite=True,
                )
                registered.append(cap)
                logger.debug("Registered capability '%s' from skill '%s'", cap, skill.name)
        return registered

    def _register_skill_capabilities(self, skill: Skill) -> None:
        """Register capabilities for a single skill (used during hot reload)."""
        from laap.tools.tool_registry import _register

        handlers = getattr(skill, "_handlers", {}) or {}
        for cap in skill.capabilities:
            handler = handlers.get(cap)
            if callable(handler):
                _register(
                    cap,
                    handler,
                    "skill",
                    skill.description or f"Skill capability: {cap}",
                    overwrite=True,
                )

    # ------------------------------------------------------------------
    # Hot-reload watch
    # ------------------------------------------------------------------
    def watch(self) -> None:
        """Start a background thread that polls skill.yaml mtime every second.

        Changed skills are reloaded and re-registered automatically.  Call
        ``stop_watch()`` to terminate the thread.
        """
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return

        self._stop_event.clear()
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("Skill watch thread started")

    def stop_watch(self) -> None:
        """Stop the background watch thread."""
        if self._watch_thread is None:
            return
        self._stop_event.set()
        self._watch_thread.join(timeout=2.0)
        self._watch_thread = None
        logger.info("Skill watch thread stopped")

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._check_for_changes()
            self._stop_event.wait(timeout=1.0)

    def _check_for_changes(self) -> None:
        # Check already loaded skills.
        for skill in list(self._skills.values()):
            if skill.path is None or not skill.path.exists():
                continue
            try:
                mtime = skill.path.stat().st_mtime
            except OSError:
                continue
            previous = self._mtimes.get(skill.path)
            if previous is not None and mtime != previous:
                logger.info("Detected change in skill '%s', reloading", skill.name)
                try:
                    if skill.path.suffix == ".yaml":
                        new_skill = load_skill(skill.path.parent)
                    else:
                        new_skill = self._load_skill_md(skill.path)
                    if new_skill:
                        self._skills[new_skill.name] = new_skill
                        self._mtimes[new_skill.path] = mtime
                        self._register_skill_capabilities(new_skill)
                except Exception as exc:
                    logger.warning("Failed to reload skill '%s': %s", skill.name, exc)
            self._mtimes[skill.path] = mtime

        # Discover brand-new skill.yaml directories.
        for d in self._dirs:
            if not d.is_dir():
                continue
            for subdir in d.iterdir():
                if not subdir.is_dir():
                    continue
                yaml_path = subdir / "skill.yaml"
                if not yaml_path.exists() or yaml_path in self._mtimes:
                    continue
                try:
                    skill = load_skill(subdir)
                    self._skills[skill.name] = skill
                    self._mtimes[skill.path] = yaml_path.stat().st_mtime
                    self._register_skill_capabilities(skill)
                    logger.info("Discovered new skill '%s' during watch", skill.name)
                except Exception as exc:
                    logger.warning("Failed to load new skill %s: %s", subdir, exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a loaded skill by exact name."""
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    # ------------------------------------------------------------------
    # Backward-compatible API
    # ------------------------------------------------------------------
    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name (slug-normalized)."""
        return self._skills.get(_make_skill_name(name))

    def get_all(self) -> List[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def get_by_category(self, category: str) -> List[Skill]:
        """Return skills in the given category."""
        return [s for s in self._skills.values() if s.category == category]

    def search(self, query: str) -> List[Skill]:
        """Search skills by name, description, or tags."""
        q = query.lower()
        results = []
        for s in self._skills.values():
            if (
                q in s.name.lower()
                or q in s.description.lower()
                or any(q in t.lower() for t in s.tags)
            ):
                results.append(s)
        return results

    def remove(self, name: str) -> bool:
        """Remove a skill from the loaded set."""
        key = _make_skill_name(name)
        skill = self._skills.pop(key, None)
        if skill and skill.path:
            self._mtimes.pop(skill.path, None)
        return skill is not None

    def reload(self) -> int:
        """Reload all skills from directories."""
        self._skills.clear()
        self._mtimes.clear()
        return len(self.discover())

    def count(self) -> int:
        """Return the number of loaded skills."""
        return len(self._skills)

    def build_system_prompt(self) -> str:
        """Build a system prompt block listing available skills."""
        if not self._skills:
            return ""
        skills_list = "\n".join(
            f"  /{s.name} — {s.description[:80]}"
            for s in sorted(self._skills.values(), key=lambda x: x.name)
        )
        return f"\n[Available Skills]\nUse /skill-name to invoke a skill.\n{skills_list}"
