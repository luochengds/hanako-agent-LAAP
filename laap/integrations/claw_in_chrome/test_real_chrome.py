# -*- coding: utf-8 -*-
"""测试脚本: 模拟调用 real_chrome 模式下的 navigate 工具.

验证流程:
    1. 检查环境就绪 (CLI / Native Host / 扩展)
    2. 切换到 real_chrome 模式
    3. 调用 browser_navigate 访问 edge://settings
    4. 验证返回结果
    5. 切换回 sandbox 模式
    6. 输出诊断报告

Usage:
    python -m laap.integrations.claw_in_chrome.test_real_chrome
    python -m laap.integrations.claw_in_chrome.test_real_chrome --url https://www.baidu.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))


def _print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _print_step(step: int, msg: str):
    print(f"\n[Step {step}] {msg}")


def _print_ok(msg: str):
    print(f"  ✓ {msg}")


def _print_fail(msg: str):
    print(f"  ✗ {msg}")


def _print_info(msg: str):
    print(f"  ℹ {msg}")


def check_environment() -> bool:
    """Step 1: 环境检查."""
    _print_step(1, "环境检查")

    # 1a. CLI 可用
    import shutil
    cic_path = shutil.which("claw-in-chrome-mcp")
    if not cic_path:
        appdata = os.environ.get("APPDATA", "")
        candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
        if candidate.exists():
            cic_path = str(candidate)
    if cic_path:
        _print_ok(f"claw-in-chrome-mcp CLI: {cic_path}")
    else:
        _print_fail("claw-in-chrome-mcp CLI 未找到")
        return False

    # 1b. Native Host
    appdata = os.environ.get("APPDATA", "")
    manifest = (
        Path(appdata) / "claw-in-chrome-mcp" / "ChromeNativeHost" /
        "com.anthropic.claude_code_browser_extension.json"
    )
    if manifest.exists():
        _print_ok(f"Native Host manifest: {manifest}")
    else:
        _print_fail(f"Native Host manifest 不存在: {manifest}")
        _print_info("请运行: claw-in-chrome-mcp install-native-host")
        return False

    # 1c. 扩展目录
    ext_dir = Path(r"D:\claw-in-chrome-main\claw-in-chrome-main")
    if (ext_dir / "manifest.json").exists():
        _print_ok(f"扩展目录: {ext_dir}")
    else:
        _print_fail(f"扩展目录不存在: {ext_dir}")
        return False

    # 1d. doctor 诊断
    try:
        result = subprocess.run(
            [cic_path, "doctor", "--json"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            browsers = data.get("installedBrowsers", [])
            ext_installed = data.get("extension", {}).get("installed", False)
            socket_paths = data.get("socket", {}).get("discoveredPaths", [])

            _print_ok(f"Doctor: {len(browsers)} 个浏览器, "
                      f"扩展={'已安装' if ext_installed else '未安装'}, "
                      f"管道={len(socket_paths)}")

            if not ext_installed:
                _print_info("⚠ 扩展尚未在浏览器中加载!")
                _print_info("  请在 Chrome 开发者模式加载扩展目录")
                _print_info("  这不影响 MCP server 启动，但浏览器操作会失败")
            return True
        else:
            _print_fail(f"Doctor 返回码: {result.returncode}")
            return False
    except Exception as e:
        _print_fail(f"Doctor 异常: {e}")
        return False


def test_mode_switch() -> bool:
    """Step 2: 模式切换测试."""
    _print_step(2, "模式切换测试")

    from laap.tools.browser_auto import set_browser_mode, get_browser_mode

    # 切换到 real_chrome
    result = set_browser_mode("real_chrome")
    data = json.loads(result)
    if data.get("mode") != "real_chrome":
        _print_fail(f"切换到 real_chrome 失败: {data}")
        return False
    _print_ok(f"已切换到 real_chrome 模式")
    _print_info(f"当前模式: {get_browser_mode()}")

    return True


def test_navigate_via_mcp(url: str) -> dict:
    """Step 3: 通过 MCP 调用 navigate.

    这会启动 claw-in-chrome-mcp serve 作为 stdio MCP server，
    然后通过 MCP 协议调用 navigate 工具。
    """
    _print_step(3, f"通过 MCP 调用 navigate: {url}")

    from laap.integrations.claw_in_chrome.adapter import ClawBridge

    bridge = ClawBridge()
    if not bridge.available:
        _print_fail("ClawBridge 不可用")
        return {"error": "bridge unavailable"}

    _print_info(f"启动 MCP server: {bridge.cic_mcp_path} serve")
    _print_info("等待 MCP 连接建立...")

    start_time = time.time()
    result_str = asyncio.run(bridge.call_tool("navigate", {"url": url}))
    elapsed = time.time() - start_time

    try:
        result = json.loads(result_str)
    except json.JSONDecodeError:
        result = {"raw": result_str}

    result["_elapsed_seconds"] = round(elapsed, 2)

    if "error" in result:
        _print_fail(f"调用失败 ({elapsed:.1f}s): {result['error']}")
        _print_info("这通常意味着扩展尚未在浏览器中加载或连接超时")
    else:
        _print_ok(f"调用完成 ({elapsed:.1f}s)")
        if result.get("url"):
            _print_ok(f"URL: {result['url']}")
        if result.get("title"):
            _print_ok(f"标题: {result['title']}")
        if result.get("success") is False:
            _print_fail(f"操作未成功: {result.get('error', 'unknown')}")
        elif result.get("success") is True:
            _print_ok("操作成功!")

    return result


def test_direct_dispatch(url: str) -> dict:
    """Step 4: 通过 browser_auto 分发测试（验证模式自动分发）."""
    _print_step(4, "通过 browser_auto 自动分发测试")

    from laap.tools.browser_auto import browser_navigate

    _print_info(f"调用 browser_navigate(url='{url}')")
    _print_info(f"当前模式为 real_chrome，应自动通过 MCP 调用")

    start_time = time.time()
    result_str = browser_navigate(url=url)
    elapsed = time.time() - start_time

    try:
        result = json.loads(result_str)
    except json.JSONDecodeError:
        result = {"raw": result_str}

    result["_elapsed_seconds"] = round(elapsed, 2)

    if "error" in result:
        _print_fail(f"分发调用失败 ({elapsed:.1f}s): {result['error']}")
    else:
        _print_ok(f"分发调用完成 ({elapsed:.1f}s)")

    return result


def restore_mode():
    """Step 5: 恢复 sandbox 模式."""
    _print_step(5, "恢复 sandbox 模式")

    from laap.tools.browser_auto import set_browser_mode
    set_browser_mode("sandbox")
    _print_ok("已恢复到 sandbox 模式")


def generate_report(env_ok, switch_ok, mcp_result, dispatch_result):
    """生成测试报告."""
    _print_header("测试报告")

    checks = [
        ("环境检查", env_ok),
        ("模式切换", switch_ok),
        ("MCP navigate 调用", "error" not in mcp_result),
        ("browser_auto 分发", "error" not in dispatch_result),
    ]

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    for name, ok in checks:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status} — {name}")

    print(f"\n  结果: {passed}/{total} 通过")

    if passed == total:
        print("\n  🎉 real_chrome 模式 navigate 测试全部通过!")
    else:
        print("\n  ⚠ 部分测试失败，请检查以下排查步骤:")
        print("  1. 确认扩展已在 Chrome 中加载 (chrome://extensions/)")
        print("  2. 运行 claw-in-chrome-mcp doctor 检查环境")
        print("  3. 查看扩展 Service Worker 日志 (chrome://extensions/ → 检查视图)")
        print("  4. 确认浏览器已启动且扩展已启用")

    return 0 if passed == total else 1


def main():
    parser = argparse.ArgumentParser(
        description="测试 real_chrome 模式下的 navigate 工具"
    )
    parser.add_argument(
        "--url", default="https://www.baidu.com",
        help="测试访问的 URL (默认: https://www.baidu.com)",
    )
    parser.add_argument(
        "--skip-mcp", action="store_true",
        help="跳过 MCP 直接调用测试",
    )
    args = parser.parse_args()

    _print_header("Claw in Chrome — real_chrome 模式 navigate 测试")

    # Step 1: 环境检查
    env_ok = check_environment()
    if not env_ok:
        print("\n⚠ 环境检查未通过，无法继续测试。")
        return 1

    # Step 2: 模式切换
    switch_ok = test_mode_switch()
    if not switch_ok:
        return 1

    # Step 3: MCP 直接调用
    mcp_result = {}
    if not args.skip_mcp:
        mcp_result = test_navigate_via_mcp(args.url)
    else:
        _print_step(3, "跳过 MCP 调用 (--skip-mcp)")

    # Step 4: browser_auto 自动分发
    dispatch_result = {}
    if not args.skip_mcp:
        dispatch_result = test_direct_dispatch(args.url)
    else:
        _print_step(4, "跳过分发测试 (--skip-mcp)")

    # Step 5: 恢复模式
    restore_mode()

    # 报告
    return generate_report(env_ok, switch_ok, mcp_result, dispatch_result)


if __name__ == "__main__":
    sys.exit(main())
