"""Builtin code templates — the seed species for the code library.

These three templates are intentionally minimal and self-documenting,
intended to be registered into a :class:`TemplateRegistry` on first run.
"""
from __future__ import annotations

from laap.species.code_templates.registry import CodeTemplate

HELLO_WORLD_CODE = '''"""A minimal hello-world function."""
def hello(name: str = "world") -> str:
    """Return a friendly greeting."""
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(hello("LAAP"))
'''


DATACLASS_CODE = '''"""A dataclass template with validation."""
from dataclasses import dataclass, field


@dataclass
class User:
    name: str
    age: int = 0
    tags: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.age, int) or self.age < 0:
            raise ValueError("age must be a non-negative integer")

    def to_dict(self) -> dict:
        return {"name": self.name, "age": self.age, "tags": list(self.tags)}
'''


ASYNC_TASK_CODE = '''"""An async task template with retry logic."""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_with_retry(
    coro_factory,
    *,
    retries: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
):
    """Run an awaitable produced by ``coro_factory`` with exponential backoff.

    ``coro_factory`` is a zero-arg callable returning a coroutine.
    Raises the last exception if all retries fail.
    """
    attempt = 0
    wait = delay
    while True:
        try:
            return await coro_factory()
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                logger.error("task failed after %d retries: %s", retries, exc)
                raise
            logger.warning("task attempt %d failed: %s — retrying in %.2fs",
                           attempt, exc, wait)
            await asyncio.sleep(wait)
            wait *= backoff
'''


def builtin_templates() -> list[CodeTemplate]:
    """Return the three builtin :class:`CodeTemplate` instances."""
    return [
        CodeTemplate(
            template_id="python_hello_world",
            name="Python Hello World",
            description="A minimal Python function returning a greeting string.",
            language="python",
            code=HELLO_WORLD_CODE,
            metadata={
                "scenario": "tutorial",
                "params": {"name": "str (default 'world')"},
                "dependencies": [],
                "test_cases": [
                    {"input": {"name": "LAAP"}, "expected": "Hello, LAAP!"},
                    {"input": {}, "expected": "Hello, world!"},
                ],
            },
        ),
        CodeTemplate(
            template_id="python_dataclass_template",
            name="Python Dataclass with Validation",
            description="A dataclass with __post_init__ validation and to_dict().",
            language="python",
            code=DATACLASS_CODE,
            metadata={
                "scenario": "data_modeling",
                "params": {"name": "str", "age": "int = 0", "tags": "list = []"},
                "dependencies": [],
                "test_cases": [
                    {"input": {"name": "Aris", "age": 18}, "expected_valid": True},
                    {"input": {"name": "", "age": -1}, "expected_valid": False},
                ],
            },
        ),
        CodeTemplate(
            template_id="python_async_task_template",
            name="Python Async Task with Retry",
            description="Async task runner with exponential-backoff retry.",
            language="python",
            code=ASYNC_TASK_CODE,
            metadata={
                "scenario": "concurrency",
                "params": {
                    "coro_factory": "Callable[[], Awaitable]",
                    "retries": "int = 3",
                    "delay": "float = 0.5",
                    "backoff": "float = 2.0",
                },
                "dependencies": ["asyncio", "logging"],
                "test_cases": [
                    {
                        "input": {"retries": 2},
                        "description": "retries failing task twice then raises",
                    },
                ],
            },
        ),
    ]


def register_builtins(registry) -> None:
    """Register all builtin templates into ``registry`` (a TemplateRegistry)."""
    for tpl in builtin_templates():
        registry.register(tpl)
