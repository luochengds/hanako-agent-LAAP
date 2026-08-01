"""LAAP Domain SDK — Harness Function Registry.

Harness functions are deterministic, token-free computations that the LLM
can invoke via tool-calls. Unlike general tools, harness functions emphasize:

1. **Zero-token execution**: computation happens in Python/Rust, not LLM.
2. **Typed schemas**: explicit parameter and return schemas for validation.
3. **Domain namespacing**: ``{domain}.{module}.{function}`` naming convention.
4. **Async-first**: all harness functions are async for non-blocking execution.

This module follows the pattern established by ``laap.tools.tool_registry``
but is specialized for domain SDK harness functions with schema validation,
async invocation, and zero-token tracking.

Usage::

    from laap.domain_sdk import harness_function, HarnessFunctionRegistry

    registry = HarnessFunctionRegistry()

    @harness_function(
        name="finquant.indicators.compute",
        description="Compute technical indicators",
        zero_token=True,
    )
    async def compute_indicators(data, indicators):
        ...

    registry.register(compute_indicators)
    result = await registry.invoke("finquant.indicators.compute", data=df, indicators=[...])
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.domain_sdk.harness_function")


@dataclass
class HarnessFunction:
    """A registered harness function with metadata and schema.

    Attributes:
        name: Dotted name following ``{domain}.{module}.{function}`` convention.
        fn: The async callable implementing the function.
        description: Human-readable description for LLM tool-call.
        schema: Parameter schema dict (JSON-Schema compatible).
        returns: Return type schema dict.
        zero_token: If True, execution consumes no LLM tokens.
        category: Function category for grouping (e.g. "indicators", "risk").
        domain: Domain ID extracted from name prefix.
        version: Function version for compatibility tracking.
    """

    name: str
    fn: Callable
    description: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    zero_token: bool = True
    category: str = ""
    domain: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.domain:
            parts = self.name.split(".")
            if len(parts) >= 2:
                self.domain = parts[0]
        if not self.category:
            parts = self.name.split(".")
            if len(parts) >= 3:
                self.category = parts[1]

    def to_dict(self, include_fn: bool = False) -> Dict[str, Any]:
        """Serialize to dict for listing / CLI output."""
        d = {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "returns": self.returns,
            "zero_token": self.zero_token,
            "category": self.category,
            "domain": self.domain,
            "version": self.version,
        }
        if include_fn:
            d["fn"] = self.fn
        return d

    def to_tool_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible tool-call schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


class HarnessFunctionRegistry:
    """Registry for domain harness functions.

    Thread-safe registry supporting decorator-based registration, async
    invocation, schema validation, and domain-scoped listing.

    Usage::

        registry = HarnessFunctionRegistry()

        @registry.harness("finquant.data.get_ohlcv", zero_token=True)
        async def get_ohlcv(symbols, start, end, interval="1d"):
            ...

        result = await registry.invoke("finquant.data.get_ohlcv",
                                        symbols=["AAPL"], start="2023-01-01", ...)
    """

    def __init__(self) -> None:
        self._functions: Dict[str, HarnessFunction] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: Optional[str] = None,
        fn: Optional[Callable] = None,
        description: str = "",
        schema: Optional[Dict[str, Any]] = None,
        returns: Optional[Dict[str, Any]] = None,
        zero_token: bool = True,
        category: str = "",
        domain: str = "",
        overwrite: bool = False,
    ) -> Any:
        """Register a harness function.

        Usable as a decorator or plain function:

            @registry.register("finquant.data.get_ohlcv", zero_token=True)
            async def get_ohlcv(...): ...

            registry.register("my.func", my_async_fn)

        Args:
            name: Dotted function name. If None, uses fn.__name__.
            fn: The async callable.
            description: Description for LLM tool-call.
            schema: Parameter schema. If None, inferred from signature.
            returns: Return type schema.
            zero_token: Whether execution is token-free.
            category: Function category.
            domain: Domain ID. If empty, extracted from name.
            overwrite: If True, overwrites existing registration.

        Returns:
            The registered function (for decorator chaining).
        """
        # Decorator form: @register("name") or @register(name="name")
        if fn is None:
            actual_name = name

            def decorator(f: Callable) -> Callable:
                self._do_register(
                    name=actual_name or f.__name__,
                    fn=f,
                    description=description,
                    schema=schema or _infer_schema(f),
                    returns=returns or {},
                    zero_token=zero_token,
                    category=category,
                    domain=domain,
                    overwrite=overwrite,
                )
                return f

            return decorator

        # Direct registration: register("name", fn)
        actual_name = name if isinstance(name, str) else fn.__name__
        self._do_register(
            name=actual_name,
            fn=fn,
            description=description,
            schema=schema or _infer_schema(fn),
            returns=returns or {},
            zero_token=zero_token,
            category=category,
            domain=domain,
            overwrite=overwrite,
        )
        return fn

    def _do_register(
        self,
        name: str,
        fn: Callable,
        description: str,
        schema: Dict[str, Any],
        returns: Dict[str, Any],
        zero_token: bool,
        category: str,
        domain: str,
        overwrite: bool,
    ) -> None:
        if not callable(fn):
            raise TypeError(f"Harness function for '{name}' must be callable")

        if not asyncio.iscoroutinefunction(fn):
            logger.warning(
                "Harness function '%s' is not async; wrapping in async shim", name
            )
            original = fn
            fn = _async_wrap(original)

        desc = description or inspect.getdoc(fn) or ""

        with self._lock:
            if name in self._functions and not overwrite:
                logger.debug("Harness function already registered: %s", name)
                return
            self._functions[name] = HarnessFunction(
                name=name,
                fn=fn,
                description=desc,
                schema=schema,
                returns=returns,
                zero_token=zero_token,
                category=category,
                domain=domain,
            )
        logger.debug("Registered harness function: %s [zero_token=%s]", name, zero_token)

    # Alias for decorator-style usage matching register_tool convention
    harness = register

    def get(self, name: str) -> Optional[HarnessFunction]:
        """Return the HarnessFunction registered under *name*, or None."""
        with self._lock:
            return self._functions.get(name)

    def list(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[HarnessFunction]:
        """List registered harness functions, optionally filtered.

        Args:
            domain: Filter by domain ID (e.g. "finquant").
            category: Filter by category (e.g. "indicators").

        Returns:
            List of matching HarnessFunction instances.
        """
        with self._lock:
            funcs = list(self._functions.values())
        result = []
        for f in funcs:
            if domain is not None and f.domain != domain:
                continue
            if category is not None and f.category != category:
                continue
            result.append(f)
        return result

    def list_names(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[str]:
        """Return function names, optionally filtered."""
        return [f.name for f in self.list(domain=domain, category=category)]

    def to_tool_schemas(
        self,
        domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert all (or domain-filtered) functions to OpenAI tool schemas."""
        return [f.to_tool_schema() for f in self.list(domain=domain)]

    async def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered harness function by name.

        Args:
            name: The registered function name.
            **kwargs: Arguments to pass to the function.

        Returns:
            The function's return value.

        Raises:
            KeyError: If function is not registered.
            TypeError: If argument validation fails.
        """
        with self._lock:
            hf = self._functions.get(name)
        if hf is None:
            raise KeyError(f"Harness function '{name}' is not registered")

        # Basic required-parameter validation
        _validate_args(hf, kwargs)

        try:
            result = await hf.fn(**kwargs)
            return result
        except Exception as e:
            logger.error("Harness function '%s' failed: %s: %s", name, type(e).__name__, e)
            raise

    def invoke_sync(self, name: str, **kwargs: Any) -> Any:
        """Synchronously invoke an async harness function.

        Creates a new event loop if none is running. For use in non-async
        contexts (CLI, tests). Prefer ``invoke()`` in async code.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Already in an async context — cannot use asyncio.run
            future = asyncio.run_coroutine_threadsafe(self.invoke(name, **kwargs), loop)
            return future.result(timeout=300)

        return asyncio.run(self.invoke(name, **kwargs))

    def unregister(self, name: str) -> bool:
        """Remove a harness function from the registry.

        Returns:
            True if the function was found and removed.
        """
        with self._lock:
            if name in self._functions:
                del self._functions[name]
                logger.debug("Unregistered harness function: %s", name)
                return True
            return False

    def clear(self) -> None:
        """Remove all registered harness functions. For test isolation."""
        with self._lock:
            self._functions.clear()

    def __contains__(self, name: object) -> bool:
        if isinstance(name, str):
            with self._lock:
                return name in self._functions
        return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._functions)

    def __iter__(self):
        with self._lock:
            return iter(list(self._functions.values()))

    @property
    def count(self) -> int:
        return len(self)

    @property
    def domains(self) -> List[str]:
        """Return sorted list of domains with registered functions."""
        with self._lock:
            return sorted({f.domain for f in self._functions.values() if f.domain})


# ── Module-level decorator and helpers ─────────────────────────────


def harness_function(
    name: str,
    description: str = "",
    schema: Optional[Dict[str, Any]] = None,
    returns: Optional[Dict[str, Any]] = None,
    zero_token: bool = True,
    category: str = "",
    domain: str = "",
) -> Callable:
    """Decorator to declare a harness function.

    The decorated function carries harness metadata as attributes. It can
    then be registered into a ``HarnessFunctionRegistry`` via ``registry.register(fn)``.

    Usage::

        @harness_function(
            name="finquant.indicators.compute",
            description="Compute technical indicators",
            zero_token=True,
        )
        async def compute_indicators(data, indicators):
            ...

        registry.register(compute_indicators.__laap_harness_name__,
                          compute_indicators)

    Or more commonly, register directly::

        @registry.harness("finquant.indicators.compute", zero_token=True)
        async def compute_indicators(data, indicators): ...
    """

    def decorator(fn: Callable) -> Callable:
        fn.__laap_harness_name__ = name
        fn.__laap_harness_description__ = description or inspect.getdoc(fn) or ""
        fn.__laap_harness_schema__ = schema or _infer_schema(fn)
        fn.__laap_harness_returns__ = returns or {}
        fn.__laap_harness_zero_token__ = zero_token
        fn.__laap_harness_category__ = category
        fn.__laap_harness_domain__ = domain
        return fn

    return decorator


def _infer_schema(fn: Callable) -> Dict[str, Any]:
    """Infer a JSON-Schema parameter schema from function signature.

    Follows the same logic as ``laap.tools.tool_registry._build_schema``
    but simplified for harness functions.
    """
    sig = inspect.signature(fn)
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        ann = param.annotation if param.annotation != inspect.Parameter.empty else "Any"
        ptype = _python_type_to_json_type(ann)

        prop: Dict[str, Any] = {"type": ptype}
        if param.default is not inspect.Parameter.empty and param.default is not None:
            prop["default"] = param.default
        else:
            required.append(pname)

        properties[pname] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _python_type_to_json_type(tp: Any) -> str:
    """Map a Python type hint to a JSON Schema type string."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    if tp in type_map:
        return type_map[tp]

    tp_str = str(tp)
    if "list" in tp_str.lower() or "List" in tp_str:
        return "array"
    if "dict" in tp_str.lower() or "Dict" in tp_str:
        return "object"
    if "int" in tp_str.lower():
        return "integer"
    if "float" in tp_str.lower() or "number" in tp_str.lower():
        return "number"
    if "bool" in tp_str.lower():
        return "boolean"
    return "string"


def _validate_args(hf: HarnessFunction, kwargs: Dict[str, Any]) -> None:
    """Validate that required parameters are present in kwargs.

    Raises:
        TypeError: If a required parameter is missing.
    """
    schema = hf.schema
    if not schema or not isinstance(schema, dict):
        return

    required = schema.get("required", [])
    missing = [p for p in required if p not in kwargs]
    if missing:
        raise TypeError(
            f"Harness function '{hf.name}' missing required parameters: {missing}"
        )


def _async_wrap(fn: Callable) -> Callable:
    """Wrap a sync function in an async shim."""
    async def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
