"""Code species registry — reusable, versioned code templates.

The "species" metaphor: each template is a self-contained unit of code
that can be selected, instantiated, mutated, and evolved. The registry
provides persistence (JSON on disk) and lookup by id / language / scenario.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CodeTemplate:
    """A reusable code template (a "species" of code).

    Attributes:
        template_id: stable identifier chosen by the author (e.g. ``python_hello_world``).
        name: human-readable name.
        description: short description of what the template does.
        language: target language (e.g. ``python``).
        code: the actual code body.
        metadata: arbitrary metadata — recommended keys are
            ``scenario``, ``params``, ``dependencies``, ``test_cases``.
        created_at: unix timestamp (seconds).
        species_id: auto-generated unique id combining timestamp + random variant.
    """
    template_id: str
    name: str
    description: str
    language: str
    code: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    species_id: str = ""

    def __post_init__(self) -> None:
        if not self.species_id:
            self.species_id = self._generate_species_id()

    @staticmethod
    def _generate_species_id() -> str:
        """Generate ``species_<timestamp>_<random>`` id."""
        return f"species_{int(time.time() * 1000)}_{random.randint(0, 0xFFFFFF):06x}"


class TemplateRegistry:
    """Persistent registry of :class:`CodeTemplate` instances.

    Persists to ``~/.laap/species/code_templates.json`` as a list of
    template dicts. The registry is loaded lazily on first access and
    flushed to disk on every mutation.
    """

    DEFAULT_PATH = os.path.expanduser("~/.laap/species/code_templates.json")

    def __init__(self, path: str = ""):
        self.path = path or self.DEFAULT_PATH
        self._templates: dict[str, CodeTemplate] = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        for item in data:
            try:
                tpl = CodeTemplate(**item)
            except TypeError:
                continue
            self._templates[tpl.species_id] = tpl

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = [asdict(t) for t in self._templates.values()]
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ── public API ────────────────────────────────────────────────
    def register(self, template: CodeTemplate) -> str:
        """Register a template. Returns the ``species_id``.

        If a template with the same ``species_id`` already exists, it is
        overwritten (re-registration is idempotent).
        """
        if not isinstance(template, CodeTemplate):
            raise TypeError(f"Expected CodeTemplate, got {type(template).__name__}")
        self._templates[template.species_id] = template
        self._save()
        return template.species_id

    def get(self, species_id: str) -> CodeTemplate | None:
        """Return the template with ``species_id`` or ``None``."""
        return self._templates.get(species_id)

    def search(
        self,
        language: str | None = None,
        scenario: str | None = None,
    ) -> list[CodeTemplate]:
        """Search templates by language and/or scenario (metadata key).

        Either argument may be ``None`` to skip that filter. The search
        is case-insensitive and matches ``scenario`` against
        ``metadata['scenario']`` (substring match).
        """
        results: list[CodeTemplate] = []
        for tpl in self._templates.values():
            if language is not None and tpl.language.lower() != language.lower():
                continue
            if scenario is not None:
                tpl_scenario = str(tpl.metadata.get("scenario", ""))
                if scenario.lower() not in tpl_scenario.lower():
                    continue
            results.append(tpl)
        return results

    def list_all(self) -> list[CodeTemplate]:
        """Return every registered template."""
        return list(self._templates.values())
