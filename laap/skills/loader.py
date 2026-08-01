"""LAAP Skill loader.

Loads a single skill directory containing ``skill.yaml`` and a handler module
(usually ``main.py``).  The handler may expose either a single ``run(**kwargs)``
function that implements every advertised capability, or a mapping from
capability name to callable.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from laap.skills.skill import Skill

logger = logging.getLogger("laap.skills.loader")

REQUIRED_FIELDS = ("name", "capabilities", "handler_path")


def _infer_schema(fn: Callable) -> Dict[str, Any]:
    """Infer an OpenAI-style parameter schema from a callable signature."""
    try:
        from laap.tools.tool_registry import _build_schema

        return _build_schema(fn)
    except Exception as exc:  # pragma: no cover
        logger.debug("Schema inference failed for %s: %s", getattr(fn, "__name__", fn), exc)
        return {"type": "object", "properties": {}}


def load_skill(path: Path) -> Skill:
    """Load a skill from *path* (a directory or a ``skill.yaml`` file)."""
    skill_dir = Path(path)
    if skill_dir.is_file():
        skill_dir = skill_dir.parent

    yaml_path = skill_dir / "skill.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"No skill.yaml found in {skill_dir}")

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyYAML is required to load skill.yaml files") from exc

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError(
            f"Skill {yaml_path} missing required fields: {missing}"
        )

    name = raw["name"]
    capabilities: List[str] = list(raw.get("capabilities", []))
    handler_file = skill_dir / raw.get("handler_path", "main.py")
    if not handler_file.exists():
        raise FileNotFoundError(f"Skill handler not found: {handler_file}")

    module_name = f"laap_skill_{str(name).replace('-', '_')}_handler"
    # Avoid collisions in sys.modules when the same skill is reloaded.
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, handler_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {handler_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    handlers: Dict[str, Callable] = {}
    run_attr = getattr(module, "run", None)
    if callable(run_attr):
        handlers = {cap: run_attr for cap in capabilities}
    elif isinstance(run_attr, dict):
        handlers = {
            cap: run_attr[cap]
            for cap in capabilities
            if cap in run_attr and callable(run_attr[cap])
        }
    else:
        for cap in capabilities:
            fn = getattr(module, cap, None)
            if callable(fn):
                handlers[cap] = fn

    schema = raw.get("schema") or {}
    if not schema and handlers:
        first_handler = next(iter(handlers.values()))
        if callable(first_handler):
            schema = _infer_schema(first_handler)

    skill = Skill(
        name=name,
        version=str(raw.get("version", "0.0.0")),
        description=raw.get("description", ""),
        capabilities=capabilities,
        schema=schema,
        handler_path=str(raw.get("handler_path", "main.py")),
        config=raw.get("config", {}) or {},
        frontmatter=raw,
        path=yaml_path,
        category=raw.get("category", "general"),
        author=raw.get("author", ""),
        tags=raw.get("tags", []) or [],
    )
    # Attach internal handler mapping used by the engine when registering tools.
    skill._handlers = handlers  # type: ignore[attr-defined]
    logger.debug("Loaded skill '%s' from %s", name, skill_dir)
    return skill
