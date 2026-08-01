"""LAAP Memory Engine — Muscle Memory (肌肉记忆/程序记忆)
Procedural memory: automated skills and compiled procedures
"""
from __future__ import annotations
import ast
import time, json, uuid, logging, hashlib, threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("engine.memory.muscle")


# ── Safe sandbox for executing muscle-memory procedures ──────────────────────

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "enumerate": enumerate, "filter": filter,
    "float": float, "format": format, "frozenset": frozenset,
    "int": int, "isinstance": isinstance, "len": len,
    "list": list, "map": map, "max": max, "min": min,
    "range": range, "reversed": reversed, "round": round,
    "set": set, "slice": slice, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "type": type,
    "zip": zip, "True": True, "False": False, "None": None,
    "print": lambda *a, **kw: logger.info(f"[muscle] {' '.join(str(x) for x in a)}"),
}

# AST node types permitted in muscle-memory code.
_ALLOWED_NODES = frozenset({
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Del,
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Expr,
    ast.Call,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.Index,
    ast.ExtSlice,
    ast.IfExp,
    ast.FormattedValue,
    ast.JoinedStr,
    ast.Starred,
    ast.keyword,
    ast.alias,
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv, ast.MatMult,
    ast.UAdd, ast.USub, ast.Not, ast.Invert,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.And, ast.Or,
    ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
})

# Dangerous builtins / special functions that may not be called.
_DISALLOWED_CALL_NAMES = frozenset({
    "__import__", "open", "eval", "exec", "compile", "getattr", "setattr",
    "delattr", "input", "exit", "quit", "help", "vars", "locals", "globals",
    "dir", "super", "staticmethod", "classmethod", "property",
    "hasattr", "callable", "repr", "ascii", "ord", "chr", "bin", "oct", "hex",
    "id", "memoryview", "bytearray", "bytes", "complex", "pow", "divmod",
    "breakpoint",
})

# Dunder attributes that must not be accessed (common sandbox escape paths).
_DISALLOWED_DUNDERS = frozenset({
    "__class__", "__bases__", "__mro__", "__subclasses__", "__globals__",
    "__code__", "__closure__", "__defaults__", "__kwdefaults__", "__dict__",
    "__module__", "__qualname__", "__builtins__", "__import__", "__loader__",
    "__spec__", "__package__", "__weakref__", "__slots__", "__prepare__",
    "__instancecheck__", "__subclasscheck__", "__class_getitem__",
    "__init_subclass__", "__getattribute__",
})


class _UnsafeCodeError(Exception):
    """Raised when muscle code contains constructs outside the sandbox whitelist."""


class _SafeExecValidator(ast.NodeVisitor):
    def __init__(self) -> None:
        self._errors: List[str] = []

    def visit(self, node: ast.AST) -> None:
        if type(node) not in _ALLOWED_NODES:
            self._errors.append(f"Unsafe AST node: {type(node).__name__}")
            return
        super().visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _DISALLOWED_CALL_NAMES:
                self._errors.append(f"Disallowed call: {func.id}")
        elif isinstance(func, ast.Attribute):
            if func.attr in _DISALLOWED_DUNDERS or func.attr in _DISALLOWED_CALL_NAMES:
                self._errors.append(f"Disallowed attribute call: {func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _DISALLOWED_DUNDERS:
            self._errors.append(f"Disallowed attribute access: {node.attr}")
        self.generic_visit(node)


def safe_exec(code: str, sandbox_globals: Dict[str, Any], filename: str = "<sandbox>") -> None:
    """Execute ``code`` inside a restricted sandbox.

    The code is first parsed and validated against an AST node whitelist;
    imports, class/lambda/async definitions, and calls to dangerous builtins
    are rejected.  Execution uses a locked-down globals namespace with no
    access to the real ``__builtins__``.
    """
    try:
        tree = ast.parse(code, filename=filename, mode="exec")
    except SyntaxError as exc:
        raise SyntaxError(f"Invalid muscle code: {exc}") from exc

    validator = _SafeExecValidator()
    validator.visit(tree)
    if validator._errors:
        raise _UnsafeCodeError(f"Unsafe code blocked: {'; '.join(validator._errors)}")

    sandbox_globals.setdefault("__builtins__", _SAFE_BUILTINS)
    compiled = compile(tree, filename, "exec")
    exec(compiled, sandbox_globals)  # nosec B102 — input validated & globals restricted

class SkillStage(str, Enum):
    COGNITIVE = "cognitive"
    ASSOCIATIVE = "associative"
    AUTONOMOUS = "autonomous"

@dataclass
class CompiledProcedure:
    id: str = field(default_factory=lambda: f"sk_{uuid.uuid4().hex[:10]}")
    name: str = ""
    description: str = ""
    code: str = ""
    signature: str = ""
    avg_execution_time: float = 0.0
    invocation_count: int = 0
    last_invoked: float = field(default_factory=time.time)
    stage: SkillStage = SkillStage.COGNITIVE
    confidence: float = 0.3
    dependencies: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "stage": self.stage.value,
                "invocations": self.invocation_count, "confidence": self.confidence}

class SkillCache:
    def __init__(self, max_size: int = 100):
        self._cache: OrderedDict[str, CompiledProcedure] = OrderedDict()
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[CompiledProcedure]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None
    
    def put(self, key: str, proc: CompiledProcedure):
        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        self._cache[key] = proc
    
    def remove(self, key: str):
        self._cache.pop(key, None)
    
    def clear(self):
        self._cache.clear()
    
    def get_stats(self) -> dict:
        return {"size": len(self._cache), "max_size": self.max_size}

class MuscleMemory:
    def __init__(self):
        self._procedures: Dict[str, CompiledProcedure] = {}
        self._cache = SkillCache()
        self._lock = threading.RLock()
    
    def learn(self, name: str, code: str, description: str = "") -> str:
        sig = hashlib.sha256(code.encode()).hexdigest()[:16]
        with self._lock:
            for pid, proc in self._procedures.items():
                if proc.signature == sig:
                    return pid
            proc = CompiledProcedure(name=name, code=code, signature=sig, description=description)
            self._procedures[proc.id] = proc
            self._cache.put(name, proc)
        return proc.id
    
    def execute(self, proc_id_or_name: str, *args, **kwargs) -> Any:
        proc = self._procedures.get(proc_id_or_name) or self._cache.get(proc_id_or_name)
        if not proc:
            raise KeyError(f"Procedure not found: {proc_id_or_name}")
        start = time.time()
        try:
            namespace: Dict[str, Any] = {}
            safe_exec(proc.code, namespace, filename=f"<muscle_{proc.id}>")
            result = None
            if "execute" in namespace:
                result = namespace["execute"](*args, **kwargs)
            proc.invocation_count += 1
            proc.last_invoked = time.time()
            elapsed = time.time() - start
            proc.avg_execution_time = (proc.avg_execution_time * (proc.invocation_count - 1) + elapsed) / proc.invocation_count
            if proc.invocation_count > 10:
                proc.stage = SkillStage.ASSOCIATIVE
            if proc.invocation_count > 50:
                proc.stage = SkillStage.AUTONOMOUS
            proc.confidence = min(1.0, proc.confidence + 0.02)
            return result
        except Exception as e:
            logger.error(f"Muscle execution failed: {e}")
            raise
    
    def get_skill(self, name: str) -> Optional[CompiledProcedure]:
        for proc in self._procedures.values():
            if proc.name == name:
                return proc
        return self._cache.get(name)
    
    def list_skills(self, stage: Optional[SkillStage] = None) -> List[CompiledProcedure]:
        if stage:
            return [p for p in self._procedures.values() if p.stage == stage]
        return list(self._procedures.values())
    
    def forget_unused(self, days_threshold: float = 30) -> int:
        cutoff = time.time() - days_threshold * 86400
        to_remove = [pid for pid, p in self._procedures.items() if p.last_invoked < cutoff]
        for pid in to_remove:
            del self._procedures[pid]
        return len(to_remove)
    
    def get_stats(self) -> dict:
        stages = {s.value: 0 for s in SkillStage}
        for p in self._procedures.values():
            stages[p.stage.value] += 1
        return {"total": len(self._procedures), "stages": stages}
