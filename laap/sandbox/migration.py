"""laap/sandbox/migration.py — CognitiveSandbox 导出/导入迁移工具

提供 .laapsnap 文件格式的序列化/反序列化能力，支持 CognitiveSandbox
8 个认知子系统的完整状态持久化，含 SHA256 完整性校验。

支持两种文件格式：
1. 二进制格式（export_sandbox / import_sandbox）：header(json) + payload(pickle)
2. JSON 格式（export_sandbox_json / import_sandbox_json）：纯 JSON 文档
   - CognitiveSandbox.export_to / import_from 使用 JSON 格式，便于调试与跨平台
"""
from __future__ import annotations

import hashlib
import json
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

# .laapsnap 文件格式版本
LAAPSNAP_VERSION = "1.0"
LAAPSNAP_MAGIC = "LAAPSNAP"
# JSON 格式专用扩展名（与二进制格式共用 .laapsnap 扩展名）
LAAPSNAP_EXTENSION = ".laapsnap"


@dataclass
class SnapHeader:
    """ .laapsnap 文件头 """
    magic: str = LAAPSNAP_MAGIC
    version: str = LAAPSNAP_VERSION
    timestamp: float = field(default_factory=time.time)
    sha256: str = ""  # payload 的 SHA256 校验和
    sandbox_id: str = ""
    role: str = ""


def export_sandbox(sandbox: "CognitiveSandbox", path: str | Path) -> None:
    """导出 CognitiveSandbox 到 .laapsnap 文件

    序列化 8 个认知子系统状态，含 SHA256 完整性校验。

    Args:
        sandbox: 要导出的 CognitiveSandbox 实例
        path: 目标文件路径（推荐 .laapsnap 扩展名）
    """
    path = Path(path)
    # 收集各子系统状态
    payload: Dict[str, Any] = {
        "sandbox_id": getattr(sandbox, "sandbox_id", ""),
        "name": getattr(sandbox, "name", ""),
        "role": getattr(sandbox, "role", ""),
        "identity": _safe_state(getattr(sandbox, "identity", None)),
        "self_model": _safe_state(getattr(sandbox, "self_model", None)),
        "world_model": _safe_state(getattr(sandbox, "world_model", None)),
        "memory_stream": _safe_state(getattr(sandbox, "memory_stream", None)),
        "goal_keeper": _safe_state(getattr(sandbox, "goal_keeper", None)),
        "resource_budget": _safe_state(getattr(sandbox, "resource_budget", None)),
        "boundary": _safe_state(getattr(sandbox, "boundary", None)),
        # skill_library 为全局只读共享，不导出私有状态
        "skill_library_ref": getattr(getattr(sandbox, "skill_library", None), "name", "default"),
    }
    # 序列化 payload
    payload_bytes = pickle.dumps(payload)
    sha256 = hashlib.sha256(payload_bytes).hexdigest()
    header = SnapHeader(
        sandbox_id=payload["sandbox_id"],
        role=payload["role"],
        sha256=sha256,
    )
    # 写入文件：header(json) + payload(pickle)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        header_json = json.dumps(header.__dict__).encode("utf-8")
        # 写入 header 长度 + header + payload
        f.write(len(header_json).to_bytes(8, "big"))
        f.write(header_json)
        f.write(payload_bytes)


def import_sandbox(
    path: str | Path,
    skill_library: Optional[Any] = None,
    event_bus: Optional[Any] = None,
) -> "CognitiveSandbox":
    """从 .laapsnap 文件导入并重建 CognitiveSandbox

    Args:
        path: .laapsnap 文件路径
        skill_library: 可选的 SkillLibrary 实例（导入时注入）
        event_bus: 可选的 ColonyEventBus 实例（导入时注入，若未提供则新建）

    Returns:
        重建后的 CognitiveSandbox 实例

    Raises:
        ValueError: 文件格式不正确或 SHA256 校验失败
    """
    path = Path(path)
    with path.open("rb") as f:
        header_len = int.from_bytes(f.read(8), "big")
        header_json = f.read(header_len).decode("utf-8")
        header = SnapHeader(**json.loads(header_json))
        payload_bytes = f.read()
    # 校验 magic
    if header.magic != LAAPSNAP_MAGIC:
        raise ValueError(f"Invalid .laapsnap magic: {header.magic}")
    # 校验 SHA256
    actual_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    if actual_sha256 != header.sha256:
        raise ValueError(
            f"SHA256 mismatch: expected {header.sha256}, got {actual_sha256}"
        )
    # 反序列化 payload
    payload: Dict[str, Any] = pickle.loads(payload_bytes)
    # 延迟导入避免循环依赖
    from laap.sandbox.colony import ColonyEventBus
    from laap.sandbox.container import CognitiveSandbox
    # event_bus 若未提供则新建
    if event_bus is None:
        event_bus = ColonyEventBus()
    # skill_library 若未提供则新建默认实例
    if skill_library is None:
        from laap.sandbox.skill_library import SkillLibrary
        skill_library = SkillLibrary()
    sandbox = CognitiveSandbox(
        sandbox_id=payload["sandbox_id"],
        name=payload.get("name", payload["sandbox_id"]),
        role=payload["role"],
        skill_library=skill_library,
        event_bus=event_bus,
    )
    # 恢复各子系统状态
    _restore_state(getattr(sandbox, "identity", None), payload.get("identity"))
    _restore_state(getattr(sandbox, "self_model", None), payload.get("self_model"))
    _restore_state(getattr(sandbox, "world_model", None), payload.get("world_model"))
    _restore_state(getattr(sandbox, "memory_stream", None), payload.get("memory_stream"))
    _restore_state(getattr(sandbox, "goal_keeper", None), payload.get("goal_keeper"))
    _restore_state(getattr(sandbox, "resource_budget", None), payload.get("resource_budget"))
    _restore_state(getattr(sandbox, "boundary", None), payload.get("boundary"))
    return sandbox


def _safe_state(obj: Any) -> Any:
    """安全提取对象状态（优先 __getstate__，否则 __dict__）

    对不可 pickle 的属性（如 threading.RLock）降级为 repr 字符串或 stats()。
    总是返回 dict 状态（对于有 __dict__ 的对象），便于 _restore_state 逐属性恢复。
    """
    if obj is None:
        return None

    # 尝试 __getstate__ 获取状态
    state = None
    if hasattr(obj, "__getstate__"):
        try:
            state = obj.__getstate__()
        except Exception:
            state = None

    if state is None and hasattr(obj, "__dict__"):
        state = obj.__dict__.copy()

    if state is None:
        # 无状态可提取，降级到 stats() 或 repr
        return _fallback_state(obj)

    # 如果 state 是 dict，过滤不可 pickle 的项
    if isinstance(state, dict):
        safe = {}
        for k, v in state.items():
            try:
                pickle.dumps(v)
                safe[k] = v
            except Exception:
                # 嵌套对象不可 pickle，尝试 stats() 或 repr
                if hasattr(v, "stats"):
                    try:
                        stats = v.stats()
                        pickle.dumps(stats)
                        safe[k] = stats
                    except Exception:
                        safe[k] = repr(v)
                else:
                    safe[k] = repr(v)
        # 验证过滤后的 dict 可 pickle
        try:
            pickle.dumps(safe)
            return safe
        except Exception:
            # 仍然不可 pickle，降级到 stats() 或 repr
            return _fallback_state(obj)

    # 非 dict 状态，尝试直接 pickle
    try:
        pickle.dumps(state)
        return state
    except Exception:
        return _fallback_state(obj)


def _fallback_state(obj: Any) -> Any:
    """降级状态提取：优先 stats()，否则 repr()"""
    if hasattr(obj, "stats"):
        try:
            stats = obj.stats()
            # 验证 stats 可 pickle
            pickle.dumps(stats)
            return stats
        except Exception:
            pass
    return repr(obj)


def _restore_state(obj: Any, state: Any) -> None:
    """安全恢复对象状态"""
    if obj is None or state is None:
        return
    if hasattr(obj, "__setstate__"):
        try:
            obj.__setstate__(state)
            return
        except Exception:
            pass
    if isinstance(state, dict) and hasattr(obj, "__dict__"):
        for k, v in state.items():
            try:
                setattr(obj, k, v)
            except Exception:
                pass


# ----------------------------------------------------------------------
# JSON 格式（CognitiveSandbox.export_to / import_from 使用）
# ----------------------------------------------------------------------

def export_sandbox_json(sandbox: "CognitiveSandbox", path: str | Path) -> str:
    """导出 CognitiveSandbox 到 JSON 格式 .laapsnap 文件

    文件结构：``{"hash": "<sha256>", "data": {inner_data}}``
    SHA256 基于 ``json.dumps(inner_data, ensure_ascii=False, indent=2)`` 计算，
    与 tests/sandbox/test_container.py 中的校验逻辑保持一致。

    Args:
        sandbox: 要导出的 CognitiveSandbox 实例
        path: 目标文件路径（自动追加 .laapsnap 扩展名）

    Returns:
        实际写入的文件路径（含 .laapsnap 扩展名）
    """
    path = Path(path)
    # 自动追加 .laapsnap 扩展名
    if path.suffix != LAAPSNAP_EXTENSION:
        path = path.with_suffix(LAAPSNAP_EXTENSION)

    # 收集各子系统状态（全部转换为 JSON 可序列化结构）
    inner_data: Dict[str, Any] = {
        "version": LAAPSNAP_VERSION,
        "sandbox_id": getattr(sandbox, "sandbox_id", ""),
        "name": getattr(sandbox, "name", ""),
        "role": getattr(sandbox, "role", ""),
        "timestamp": time.time(),
        "identity": _to_jsonable(getattr(sandbox, "identity", None)),
        "self_model": _to_jsonable(getattr(sandbox, "self_model", None)),
        "world_model": _to_jsonable(getattr(sandbox, "world_model", None)),
        "memory_stream": _to_jsonable(getattr(sandbox, "memory_stream", None)),
        "goal_keeper": _to_jsonable(getattr(sandbox, "goal_keeper", None)),
        "resource_budget": _to_jsonable(getattr(sandbox, "resource_budget", None)),
        "boundary_log": _to_jsonable(getattr(sandbox, "boundary", None)),
    }

    # 计算 SHA256（与测试期望一致：基于 json.dumps(indent=2) 的字节流）
    json_str = json.dumps(inner_data, ensure_ascii=False, indent=2)
    sha256 = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    # 写入 JSON 文件
    path.parent.mkdir(parents=True, exist_ok=True)
    export_data: Dict[str, Any] = {"hash": sha256, "data": inner_data}
    with path.open("w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    return str(path)


def import_sandbox_json(
    path: str | Path,
    skill_library: Optional[Any] = None,
    event_bus: Optional[Any] = None,
) -> "CognitiveSandbox":
    """从 JSON 格式 .laapsnap 文件导入并重建 CognitiveSandbox

    Args:
        path: .laapsnap 文件路径（JSON 格式）
        skill_library: 可选的 SkillLibrary 实例
        event_bus: 可选的 ColonyEventBus 实例

    Returns:
        重建后的 CognitiveSandbox 实例

    Raises:
        ValueError: SHA256 校验失败（"SHA256 verification failed"）或版本不匹配（"Version mismatch"）
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        export_data = json.load(f)

    stored_hash = export_data.get("hash", "")
    inner_data = export_data.get("data", {})

    # 校验 SHA256（与测试期望一致：基于 json.dumps(indent=2) 的字节流）
    json_str = json.dumps(inner_data, ensure_ascii=False, indent=2)
    computed_hash = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
    if stored_hash != computed_hash:
        raise ValueError(
            f"SHA256 verification failed: expected {stored_hash}, got {computed_hash}"
        )

    # 校验版本
    version = inner_data.get("version", "")
    if version != LAAPSNAP_VERSION:
        raise ValueError(
            f"Version mismatch: expected {LAAPSNAP_VERSION}, got {version}"
        )

    # 延迟导入避免循环依赖
    from laap.sandbox.colony import ColonyEventBus
    from laap.sandbox.container import CognitiveSandbox
    from laap.sandbox.skill_library import SkillLibrary

    # event_bus 若未提供则新建
    if event_bus is None:
        event_bus = ColonyEventBus()
    # skill_library 若未提供则新建默认实例
    if skill_library is None:
        skill_library = SkillLibrary()

    sandbox = CognitiveSandbox(
        sandbox_id=inner_data["sandbox_id"],
        name=inner_data.get("name", inner_data["sandbox_id"]),
        role=inner_data["role"],
        skill_library=skill_library,
        event_bus=event_bus,
    )

    # 恢复各子系统状态（goal_keeper.goals 等关键字段会被还原）
    _restore_state(getattr(sandbox, "identity", None), inner_data.get("identity"))
    _restore_state(getattr(sandbox, "self_model", None), inner_data.get("self_model"))
    _restore_state(getattr(sandbox, "world_model", None), inner_data.get("world_model"))
    _restore_state(getattr(sandbox, "memory_stream", None), inner_data.get("memory_stream"))
    _restore_state(getattr(sandbox, "goal_keeper", None), inner_data.get("goal_keeper"))
    _restore_state(getattr(sandbox, "resource_budget", None), inner_data.get("resource_budget"))
    _restore_state(getattr(sandbox, "boundary", None), inner_data.get("boundary_log"))

    return sandbox


def _to_jsonable(obj: Any, _depth: int = 0) -> Any:
    """递归转换为 JSON 可序列化结构

    处理 set / 自定义对象 / 嵌套容器，确保结果可被 ``json.dumps`` 序列化。
    加深 _depth 防止自引用对象导致无限递归。
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, set):
        return sorted(_to_jsonable(x, _depth + 1) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v, _depth + 1) for k, v in obj.items()}
    # 防止无限递归
    if _depth > 5:
        return repr(obj)
    # 自定义对象：优先 __dict__，其次 stats()
    if hasattr(obj, "__dict__"):
        try:
            return {str(k): _to_jsonable(v, _depth + 1) for k, v in obj.__dict__.items()}
        except Exception:
            pass
    if hasattr(obj, "stats"):
        try:
            return _to_jsonable(obj.stats(), _depth + 1)
        except Exception:
            pass
    return repr(obj)


def is_json_laapsnap(path: str | Path) -> bool:
    """检测 .laapsnap 文件是否为 JSON 格式（首字节为 '{'）

    用于 CognitiveSandbox.import_from 自动分派到正确的导入函数。
    """
    try:
        with Path(path).open("rb") as f:
            first_byte = f.read(1)
        return first_byte == b"{"
    except OSError:
        return False
