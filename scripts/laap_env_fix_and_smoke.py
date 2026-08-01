#!/usr/bin/env python3
"""LAAP Hanako 环境修复 + 冒烟测试脚本.

用法:
    python scripts/laap_env_fix_and_smoke.py

功能:
1. 检测并修复 Windows 特有依赖 pywin32
2. 安装 / 更新 requirements.txt
3. 运行 LAAP 核心模块冒烟测试（不依赖完整 Hanako 启动）
4. 运行关键 unittest 套件
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import List, Tuple

# ── 路径 ──────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"

# ── 颜色输出（兼容 Windows）────────────────────────────────────
class Color:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    INFO = "\033[94m"
    RESET = "\033[0m"


def _supports_color() -> bool:
    return os.environ.get("TERM", "") or os.name != "nt"


def c(level: str, text: str) -> str:
    if _supports_color():
        return f"{getattr(Color, level)}{text}{Color.RESET}"
    return text


# ── 工具函数 ───────────────────────────────────────────────────
def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print(c("INFO", f"  $ {' '.join(cmd)}"))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=(os.name == "nt" and cmd[0].endswith(".cmd")),
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.returncode != 0 and check:
        print(c("FAIL", f"  命令失败 (exit {result.returncode}):"))
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                print(f"    {line}")
        raise RuntimeError(f"command failed: {cmd}")
    return result


def ensure_pywin32() -> None:
    """Windows 下确保 pywin32 已安装."""
    if os.name != "nt":
        print(c("INFO", "[跳过] 非 Windows 系统，不检查 pywin32"))
        return
    print(c("INFO", "[1/5] 检查 pywin32 ..."))
    try:
        import pywintypes  # noqa: F401
        print(c("OK", "  pywin32 已安装"))
        return
    except ImportError:
        print(c("WARN", "  未安装 pywin32，尝试安装 ..."))
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pywin32"])
    try:
        import pywintypes  # noqa: F401
        print(c("OK", "  pywin32 安装成功"))
    except ImportError:
        print(c("FAIL", "  pywin32 安装后仍无法导入，请手动排查"))
        raise


def ensure_requirements() -> None:
    """安装 requirements.txt."""
    print(c("INFO", "[2/5] 安装 Python 依赖 ..."))
    if not REQUIREMENTS.is_file():
        print(c("WARN", f"  未找到 {REQUIREMENTS}，跳过"))
        return
    # 先升级构建工具，避免 editable install 因 setuptools/pip 过旧失败
    run([
        sys.executable, "-m", "pip", "install", "--upgrade",
        "pip", "setuptools", "wheel",
    ])
    run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    print(c("OK", "  Python 依赖安装完成"))


# ── 冒烟测试 ───────────────────────────────────────────────────
def smoke_file_exists(path: Path, desc: str) -> None:
    if path.is_file():
        print(c("OK", f"  {desc}: {path}"))
    else:
        raise AssertionError(f"缺失文件: {path}")


def smoke_contains(path: Path, desc: str, pattern: str) -> None:
    text = path.read_text(encoding="utf-8")
    if re.search(pattern, text):
        print(c("OK", f"  {desc} 包含 '{pattern}'"))
    else:
        raise AssertionError(f"{desc} 未找到 '{pattern}'")


def smoke_import(module: str, attr: str = "") -> object:
    try:
        mod = importlib.import_module(module)
        obj = getattr(mod, attr) if attr else mod
        print(c("OK", f"  import {module}{('.' + attr) if attr else ''}"))
        return obj
    except Exception as exc:
        raise AssertionError(f"import {module} 失败: {exc}") from exc


def run_smoke_tests() -> None:
    """不启动服务的基础冒烟测试."""
    print(c("INFO", "[3/5] 基础冒烟测试 ..."))

    # 关键文件存在
    smoke_file_exists(REPO_ROOT / "ARIS_CHARTER.md", "ARIS 宪章文件")
    smoke_file_exists(REPO_ROOT / "hanako" / "aris-bridge" / "aris-engine" / "sidecar.py", "sidecar 主文件")
    smoke_file_exists(REPO_ROOT / "laap" / "mcp" / "server.py", "MCP server 文件")
    smoke_file_exists(REPO_ROOT / "laap" / "colony" / "protocol.py", "colony protocol")
    smoke_file_exists(REPO_ROOT / "laap" / "skills" / "preset_registry.py", "预设市场注册表")

    # 关键代码存在
    sidecar = REPO_ROOT / "hanako" / "aris-bridge" / "aris-engine" / "sidecar.py"
    smoke_contains(sidecar, "sidecar", r"/guardian/act")
    smoke_contains(sidecar, "sidecar", r"/preset/list")
    smoke_contains(sidecar, "sidecar", r"/charter/text")

    mcp_server = REPO_ROOT / "laap" / "mcp" / "server.py"
    smoke_contains(mcp_server, "MCP server", r"register_guardian_tools")
    smoke_contains(mcp_server, "MCP server", r"register_preset_market_tools")

    # 关键类可导入
    smoke_import("laap.colony.protocol", "GuardianRegistry")
    smoke_import("laap.skills.preset_registry", "PresetRegistry")
    smoke_import("laap.evolution.charter_checker", "CharterChecker")

    # GuardianRegistry 行为
    from laap.colony.protocol import GuardianRegistry
    reg = GuardianRegistry()
    reg.register_guardian("pk-1")
    assert "pk-1" in reg.list_guardians(), "guardian 注册失败"

    # PresetRegistry 行为
    from laap.skills.preset_registry import PresetRegistry
    pr = PresetRegistry()
    assert len(pr.list_presets()) == 4, "预设数量不是 4"
    cloned = pr.clone_preset("aris", "MyAris")
    assert cloned["cloned"] is True, "克隆失败"
    assert cloned["config"]["name"] == "MyAris", "克隆名称错误"

    # CharterChecker 行为
    from laap.evolution.charter_checker import CharterChecker, _load_charter_text
    articles = _load_charter_text()
    assert len(articles) == 8, f"宪章条数不是 8: {len(articles)}"
    checker = CharterChecker()
    result = checker.audit(" harmless patch ")
    assert result["charter_compatible"] is True, "无害 patch 应通过"
    bad = checker.audit("disable_sandbox() and delete_guardian_logs(); bypass_guardian_audit")
    assert bad["charter_compatible"] is False, f"恶意 patch 应被拦截，实际判定: {bad}"

    print(c("OK", "  基础冒烟测试全部通过"))


# ── 单元测试 ───────────────────────────────────────────────────
TEST_SUITES = [
    "laap.evolution.test_aris_charter",
    "laap.skills.test_preset_registry",
    "laap.colony.test_guardian",
]


def run_unit_tests() -> Tuple[int, int]:
    """运行核心 unittest 套件."""
    print(c("INFO", "[4/5] 运行核心单元测试 ..."))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for name in TEST_SUITES:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except Exception as exc:
            print(c("WARN", f"  无法加载 {name}: {exc}"))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    return total, failed


# ── 环境摘要 ───────────────────────────────────────────────────
def print_summary(total: int, failed: int) -> None:
    print()
    print("=" * 56)
    if failed == 0:
        print(c("OK", "  LAAP 环境修复与冒烟测试全部通过"))
    else:
        print(c("FAIL", f"  单元测试未通过: {failed}/{total} 失败"))
    print("=" * 56)
    print("  下一步建议:")
    if failed == 0:
        print("    python installer/launch.py --check")
        print("    python installer/launch.py")
    else:
        print("    查看上方失败详情，修复后重新运行本脚本")


# ── 主入口 ─────────────────────────────────────────────────────
def _laap_importable() -> bool:
    """检查当前进程是否能导入 laap."""
    try:
        importlib.import_module("laap")
        return True
    except Exception:
        return False


def main() -> int:
    print("=" * 56)
    print("  LAAP Hanako 环境修复 + 冒烟测试")
    print("=" * 56)
    print(f"  Python: {sys.version}")
    print(f"  仓库根目录: {REPO_ROOT}")
    print()

    try:
        ensure_pywin32()
        ensure_requirements()

        # editable install 完成后，当前进程可能尚未加载新 .pth 路径，重启一次
        if not _laap_importable():
            print(c("INFO", "  依赖刚安装，重启脚本以加载新环境..."))
            result = subprocess.run([sys.executable, __file__])
            return result.returncode

        run_smoke_tests()
        total, failed = run_unit_tests()
    except Exception as exc:
        print(c("FAIL", f"\n  流程中断: {exc}"))
        return 1

    print_summary(total, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
