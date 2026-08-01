"""LAAP — 组件热编译预览 MCP 端点桥接（SubTask 2.4 + 2.5）

提供给 aris sidecar 调用的 helper 函数：
- handle_preview_component(component_path, new_content) -> {render_result, diff, old_source, new_source}
- handle_hot_replace(component_path, new_content, confirmed_by) -> {replaced, witness_trail_id, backup_path, skipped?}

本模块不直接修改 sandbox.py（sandbox.py 改动通过 Integration Patch 提供）。
handle_preview_component 优先调用 sandbox.Sandbox.preview_component（若已通过 patch 添加），
否则在 helper 内实现简易预览（读取原文件 + 生成 diff + mock render_result）。

幂等性（spec L432 硬约束）：handle_hot_replace 同 component_path + 同 new_content
重复调用不重复备份（检测内容相同则跳过，仅写一条 skipped 见证迹）。

安全（spec L435 硬约束 + tasks SubTask 2.5）：
- hot_replace 仅允许 laap/ 或 hanako/plugins/ 下文件，不触及 hanako/desktop/src/react/ 核心文件
- 备份原文件到 .bak.{timestamp}，写入见证迹 witness_trail_local（复用 true_rsi.py 建表模式）

风格：dataclass + type hints + lazy import（spec L437 Python 约束）。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.evolution.preview_mcp_endpoints")

# 允许热替换的根目录前缀（相对仓库根）
ALLOWED_ROOTS = ("laap/", "hanako/plugins/")

# 禁止热替换的路径前缀（即使位于允许根下也拒绝）
BLOCKED_PATHS = (
    "hanako/desktop/src/react/",
    "hanako/desktop/src/main",
    "hanako/aris-bridge/",
)


@dataclass
class DiffLine:
    """行级 diff 单元。与 hanako/plugins/hot-compile-preview/DiffViewer.tsx 的 DiffLine 等价。"""

    type: str  # "added" | "removed" | "unchanged"
    content: str
    old_line_no: Optional[int] = None
    new_line_no: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type, "content": self.content}
        if self.old_line_no is not None:
            d["oldLineNo"] = self.old_line_no
        if self.new_line_no is not None:
            d["newLineNo"] = self.new_line_no
        return d


def compute_line_diff(
    old_source: str, new_source: str, max_lines: int = 5000
) -> List[DiffLine]:
    """计算两段文本的行级 diff（基于 LCS 动态规划）。

    与 DiffViewer.tsx computeLineDiff 算法等价。
    时间复杂度 O(m*n)，空间 O(m*n)；冒烟测试用例足够，大文件需预截断。
    """
    old_lines = (old_source or "").split("\n")[:max_lines]
    new_lines = (new_source or "").split("\n")[:max_lines]
    m, n = len(old_lines), len(new_lines)
    dp: List[List[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            if old_lines[i] == new_lines[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    result: List[DiffLine] = []
    i = j = 0
    while i < m and j < n:
        if old_lines[i] == new_lines[j]:
            result.append(DiffLine("unchanged", old_lines[i], i + 1, j + 1))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            result.append(DiffLine("removed", old_lines[i], i + 1, None))
            i += 1
        else:
            result.append(DiffLine("added", new_lines[j], None, j + 1))
            j += 1
    while i < m:
        result.append(DiffLine("removed", old_lines[i], i + 1, None))
        i += 1
    while j < n:
        result.append(DiffLine("added", new_lines[j], None, j + 1))
        j += 1
    return result


def _is_path_allowed(component_path: str) -> bool:
    """校验 component_path 在允许范围内。

    规则：
    - 必须在 laap/ 或 hanako/plugins/ 下
    - 不在 BLOCKED_PATHS 下（防止核心文件被改）
    - 阻止路径穿越（..）和绝对路径 / Windows 盘符
    """
    if not component_path:
        return False
    normalized = component_path.replace("\\", "/")
    if ".." in normalized.split("/"):
        return False
    if normalized.startswith("/"):
        return False
    first_seg = normalized.split("/")[0]
    if ":" in first_seg:  # Windows 盘符如 C:
        return False
    for blocked in BLOCKED_PATHS:
        if normalized.startswith(blocked):
            return False
    return any(normalized.startswith(root) for root in ALLOWED_ROOTS)


def _find_repo_root(component_path: str) -> Optional[str]:
    """根据 component_path 探测仓库根目录。

    sidecar 进程 cwd 可能是 hanako/aris-bridge/aris-engine/，需向上查找
    直到 component_path 相对路径存在。找不到时返回第一个候选（用于新文件创建）。
    """
    candidates: List[str] = []
    cwd = os.getcwd()
    candidates.append(cwd)
    for _ in range(4):
        cwd = os.path.dirname(cwd)
        if cwd:
            candidates.append(cwd)
    # 本文件位于 laap/evolution/preview_mcp_endpoints.py，向上 3 层是仓库根
    try:
        sidecar_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(sidecar_dir)))
        if repo_root not in candidates:
            candidates.append(repo_root)
    except Exception:
        pass
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, component_path)):
            return cand
    return candidates[0] if candidates else os.getcwd()


def _read_file_safe(component_path: str, repo_root: Optional[str]) -> str:
    """安全读取文件，失败返回空字符串。"""
    try:
        root = repo_root or _find_repo_root(component_path)
        full = os.path.join(root, component_path)
        if not os.path.isfile(full):
            return ""
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"read file failed {component_path}: {e}")
        return ""


def handle_preview_component(
    component_path: str,
    new_content: str,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """预览组件：读取原文件 + 生成 diff + mock render_result。

    优先调用 sandbox.Sandbox.preview_component（Integration Patch 添加的方法）；
    若方法不存在或抛异常，在 helper 内实现简易预览。

    Args:
        component_path: 相对仓库根的路径
        new_content: 新组件源码。空字符串时仅返回原文件内容 + 空 diff
        repo_root: 可选仓库根（测试用）

    Returns:
        {render_result: {success, html_preview?, error?}, diff: [], old_source, new_source}
    """
    # 优先调用 sandbox.preview_component（Integration Patch 添加的方法）
    try:
        from laap.evolution.sandbox import Sandbox  # lazy import

        if hasattr(Sandbox, "preview_component"):
            sandbox = Sandbox()
            result = sandbox.preview_component(component_path, new_content or "")
            if isinstance(result, dict):
                old_src = _read_file_safe(component_path, repo_root)
                result.setdefault("old_source", old_src or "")
                result.setdefault("new_source", new_content or "")
                return result
    except Exception as e:
        logger.warning(f"sandbox.preview_component fallback to helper impl: {e}")

    # 简易预览：helper 内实现
    old_source = _read_file_safe(component_path, repo_root)
    new_source = new_content or ""
    if not new_source:
        new_source = old_source
    diff = compute_line_diff(old_source, new_source)
    render_result: Dict[str, Any] = {
        "success": True,
        "html_preview": f"<!-- preview stub for {component_path} -->",
    }
    return {
        "render_result": render_result,
        "diff": [d.to_dict() for d in diff],
        "old_source": old_source,
        "new_source": new_source,
    }


def handle_hot_replace(
    component_path: str,
    new_content: str,
    confirmed_by: str = "user",
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """热替换组件：校验路径 → 备份原文件 → 写入新内容 → 写见证迹。

    幂等：同 component_path + 同 new_content 重复调用不重复备份（spec L432）。

    Args:
        component_path: 相对仓库根的路径
        new_content: 新组件源码
        confirmed_by: 操作者标识，写入见证迹 agent_name
        repo_root: 可选仓库根（测试用）

    Returns:
        {replaced, witness_trail_id, backup_path, skipped?}
        replaced=False 时附 error 字段
    """
    # 1. 路径校验（spec L435 安全硬约束）
    if not _is_path_allowed(component_path):
        return {
            "replaced": False,
            "witness_trail_id": "",
            "backup_path": "",
            "error": f"path '{component_path}' not in allowed roots {ALLOWED_ROOTS} or blocked",
        }
    root = repo_root or _find_repo_root(component_path)
    full_path = os.path.join(root, component_path)
    # 绝对路径再次校验
    normalized_full = full_path.replace("\\", "/")
    for blocked in BLOCKED_PATHS:
        if blocked in normalized_full:
            return {
                "replaced": False,
                "witness_trail_id": "",
                "backup_path": "",
                "error": f"absolute path blocked: {full_path}",
            }

    # 2. 读取原文件
    old_content = ""
    file_exists = os.path.isfile(full_path)
    if file_exists:
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except Exception as e:
            return {
                "replaced": False,
                "witness_trail_id": "",
                "backup_path": "",
                "error": f"read original failed: {e}",
            }

    # 3. 幂等：内容相同则跳过（仅写一条 skipped 见证迹，不备份）
    if old_content == new_content:
        witness_id = _write_witness_trail(
            agent_name=confirmed_by,
            component_path=component_path,
            action="hot_replace_skipped",
            fitness_score=0.0,
        )
        return {
            "replaced": True,
            "witness_trail_id": witness_id,
            "backup_path": "",
            "skipped": True,
        }

    # 4. 备份原文件（仅当文件存在时）
    # 用毫秒时间戳确保同秒内多次替换不会覆盖备份文件（spec L432 幂等：相同内容跳过；
    # 不同内容则每次都要独立备份）
    backup_path = ""
    if file_exists:
        timestamp = int(time.time() * 1000)  # 毫秒，避免同秒覆盖
        backup_path = f"{full_path}.bak.{timestamp}"
        try:
            import shutil  # lazy import

            shutil.copy2(full_path, backup_path)
        except Exception as e:
            return {
                "replaced": False,
                "witness_trail_id": "",
                "backup_path": "",
                "error": f"backup failed: {e}",
            }

    # 5. 写入新内容
    try:
        parent = os.path.dirname(full_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return {
            "replaced": False,
            "witness_trail_id": "",
            "backup_path": backup_path,
            "error": f"write failed: {e}",
        }

    # 6. 写见证迹（复用 true_rsi.py witness_trail_local 建表模式，spec L1587-1602）
    witness_id = _write_witness_trail(
        agent_name=confirmed_by,
        component_path=component_path,
        action="hot_replace",
        fitness_score=0.0,
    )
    logger.info(
        f"hot_replace done: {component_path} backup={backup_path} witness={witness_id}"
    )
    return {
        "replaced": True,
        "witness_trail_id": witness_id,
        "backup_path": backup_path,
        "skipped": False,
    }


def _write_witness_trail(
    agent_name: str,
    component_path: str,
    action: str,
    fitness_score: float = 0.0,
) -> str:
    """写本地见证迹（P4 witness-trail 未实现时的预留）。

    复用 laap/evolution/true_rsi.py 的 witness_trail_local 建表模式（spec L1587-1602）。
    在 agent vault 的 witness_trail_local 表中追加一条记录：
        event_type="hot_replace", candidate_id=component_path, target_module=component_path

    失败不抛异常（仅警告日志），返回 witness_id（即使空也不阻断主流程）。
    """
    witness_id = f"wit_{uuid.uuid4().hex[:12]}"
    try:
        from laap.memory_vault.vault_manager import (  # lazy import
            vault_manager,
            _open_vault_connection,
        )
        db_path, key_hex = vault_manager._get_vault(agent_name)
        conn = _open_vault_connection(db_path, key_hex)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS witness_trail_local (
                    witness_id    TEXT PRIMARY KEY,
                    agent_name    TEXT NOT NULL,
                    event_type    TEXT NOT NULL,
                    candidate_id  TEXT NOT NULL,
                    action        TEXT NOT NULL,
                    target_module TEXT DEFAULT '',
                    fitness_score REAL DEFAULT 0,
                    timestamp     REAL NOT NULL,
                    signature     TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_witness_agent
                    ON witness_trail_local(agent_name);
                CREATE INDEX IF NOT EXISTS idx_witness_candidate
                    ON witness_trail_local(candidate_id);
            """)
            conn.execute(
                """INSERT OR REPLACE INTO witness_trail_local
                   (witness_id, agent_name, event_type, candidate_id,
                    action, target_module, fitness_score, timestamp, signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    witness_id,
                    agent_name,
                    "hot_replace",
                    component_path,
                    action,
                    component_path,
                    fitness_score,
                    time.time(),
                    "",  # P4 落地时填签名
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(
            f"write_witness_trail hot_replace failed for {component_path}: {exc}"
        )
    return witness_id
