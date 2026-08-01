# -*- coding: utf-8 -*-
"""Claw in Chrome 连接故障排查诊断脚本.

当 real_chrome 模式连接失败时，按以下顺序排查:
    1. claw-in-chrome-mcp serve 能否启动
    2. Native Messaging Host 注册表是否正确
    3. 扩展是否已在浏览器中加载
    4. Socket 管道是否可连接
    5. 扩展 Service Worker 日志检查
    6. 常见错误码对照表

Usage:
    python -m laap.integrations.claw_in_chrome.troubleshoot
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))


def _ok(msg: str):
    print(f"  ✓ {msg}")

def _fail(msg: str):
    print(f"  ✗ {msg}")

def _info(msg: str):
    print(f"  ℹ {msg}")

def _warn(msg: str):
    print(f"  ⚠ {msg}")


def check_1_mcp_serve_startup():
    """检查 1: claw-in-chrome-mcp serve 能否启动."""
    print("\n[检查 1] MCP serve 启动测试")
    import shutil
    cic = shutil.which("claw-in-chrome-mcp")
    if not cic:
        appdata = os.environ.get("APPDATA", "")
        candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
        if candidate.exists():
            cic = str(candidate)
    if not cic:
        _fail("claw-in-chrome-mcp 未找到")
        return False

    try:
        # 启动 serve，3 秒后终止（它应该是长驻进程）
        proc = subprocess.Popen(
            [cic, "serve"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
        time.sleep(2)
        if proc.poll() is None:
            _ok(f"serve 进程启动成功 (PID={proc.pid})")
            proc.terminate()
            proc.wait(timeout=5)
            return True
        else:
            stdout = proc.stdout.read()[:500] if proc.stdout else ""
            stderr = proc.stderr.read()[:500] if proc.stderr else ""
            _fail(f"serve 进程异常退出 (code={proc.returncode})")
            if stderr:
                _info(f"stderr: {stderr}")
            return False
    except Exception as e:
        _fail(f"启动异常: {e}")
        return False


def check_2_native_host_registry():
    """检查 2: Native Messaging Host 注册表."""
    print("\n[检查 2] Native Messaging Host 注册表")

    appdata = os.environ.get("APPDATA", "")
    manifest_path = (
        Path(appdata) / "claw-in-chrome-mcp" / "ChromeNativeHost" /
        "com.anthropic.claude_code_browser_extension.json"
    )

    if not manifest_path.exists():
        _fail(f"Manifest 文件不存在: {manifest_path}")
        return False

    _ok(f"Manifest 文件存在: {manifest_path}")

    # 读取 manifest 内容
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _ok(f"Manifest JSON 有效")
        wrapper = manifest.get("path", "")
        if wrapper and Path(wrapper).exists():
            _ok(f"Wrapper 脚本存在: {wrapper}")
        else:
            _fail(f"Wrapper 脚本不存在: {wrapper}")
            return False
    except Exception as e:
        _fail(f"Manifest JSON 解析失败: {e}")
        return False

    # 检查注册表（使用 reg query）
    reg_paths = [
        r"HKCU\Software\Google\Chrome\NativeMessagingHosts\com.anthropic.claude_code_browser_extension",
        r"HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.anthropic.claude_code_browser_extension",
    ]
    for reg_path in reg_paths:
        browser = "Chrome" if "Chrome" in reg_path else "Edge"
        try:
            result = subprocess.run(
                ["reg", "query", reg_path, "/ve"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                _ok(f"{browser} 注册表项存在")
            else:
                _fail(f"{browser} 注册表项不存在")
        except Exception as e:
            _warn(f"{browser} 注册表检查失败: {e}")

    return True


def check_3_extension_loaded():
    """检查 3: 扩展是否已在浏览器中加载."""
    print("\n[检查 3] 扩展加载状态")

    import shutil
    cic = shutil.which("claw-in-chrome-mcp")
    if not cic:
        appdata = os.environ.get("APPDATA", "")
        candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
        if candidate.exists():
            cic = str(candidate)

    if not cic:
        _fail("无法执行 doctor 检查（CLI 不可用）")
        return False

    try:
        result = subprocess.run(
            [cic, "doctor", "--json"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            _fail(f"doctor 返回码: {result.returncode}")
            return False

        data = json.loads(result.stdout)
        ext = data.get("extension", {})
        browsers_checked = data.get("extension", {}).get("checkedPaths", [])

        if ext.get("installed"):
            _ok(f"扩展已在 {ext.get('browser', '?')} 中安装")
            return True
        else:
            _fail("扩展未在任何浏览器中检测到")
            _info(f"已检查 {len(browsers_checked)} 个浏览器路径")
            _info("请按以下步骤加载扩展:")
            _info("  1. 打开 chrome://extensions/")
            _info("  2. 开启右上角「开发者模式」")
            _info("  3. 点击「加载已解压的扩展程序」")
            _info("  4. 选择目录: D:\\claw-in-chrome-main\\claw-in-chrome-main")
            _info("  5. 完全退出并重启 Chrome")
            return False
    except Exception as e:
        _fail(f"doctor 异常: {e}")
        return False


def check_4_socket_connectable():
    """检查 4: Socket 管道可连接性."""
    print("\n[检查 4] Socket 管道诊断")

    import shutil
    cic = shutil.which("claw-in-chrome-mcp")
    if not cic:
        appdata = os.environ.get("APPDATA", "")
        candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
        if candidate.exists():
            cic = str(candidate)

    try:
        result = subprocess.run(
            [cic, "doctor", "--json"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        data = json.loads(result.stdout)
        sock = data.get("socket", {})
        discovered = sock.get("discoveredPaths", [])
        connectable = sock.get("connectablePaths", [])

        _info(f"已发现管道: {len(discovered)}")
        for p in discovered:
            _info(f"  → {p}")

        _info(f"可连接管道: {len(connectable)}")
        for p in connectable:
            _ok(f"  → {p}")

        if discovered and not connectable:
            _warn("管道已发现但不可连接 — 通常表示扩展未运行或浏览器已关闭")
            _info("解决: 重启浏览器，确认扩展已启用")
        elif not discovered:
            _warn("未发现任何管道 — 扩展可能未加载或 Native Host 未运行")
            _info("解决: 1) 加载扩展 2) 运行 claw-in-chrome-mcp install-native-host")
        elif connectable:
            _ok("管道可连接，通信正常")
            return True
    except Exception as e:
        _fail(f"Socket 诊断异常: {e}")

    return False


def check_5_browser_processes():
    """检查 5: 浏览器进程状态."""
    print("\n[检查 5] 浏览器进程状态")

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5,
        )
        chrome_count = result.stdout.count("chrome.exe")
        if chrome_count > 0:
            _ok(f"Chrome 进程运行中 ({chrome_count} 个)")
        else:
            _warn("Chrome 未运行 — 请启动 Chrome 浏览器")
    except Exception:
        _warn("无法检查 Chrome 进程")

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
            capture_output=True, text=True, timeout=5,
        )
        edge_count = result.stdout.count("msedge.exe")
        if edge_count > 0:
            _ok(f"Edge 进程运行中 ({edge_count} 个)")
        else:
            _info("Edge 未运行")
    except Exception:
        pass


def print_error_reference():
    """打印常见错误码对照表."""
    print("\n" + "=" * 60)
    print("常见错误排查指南")
    print("=" * 60)

    errors = [
        ("MCP server 连接超时",
         "serve 进程启动但 MCP 握手失败",
         "1. 检查扩展是否已加载\n"
         "  2. 重启浏览器\n"
         "  3. 运行 claw-in-chrome-mcp doctor"),
        ("'Not connected' 错误",
         "MCP client 未建立连接",
         "1. 确认 claw-in-chrome-mcp serve 可启动\n"
         "  2. 检查 stdio 管道是否被占用\n"
         "  3. 尝试手动运行: claw-in-chrome-mcp serve"),
        ("Native Host 未找到",
         "注册表中 Native Messaging Host 路径错误",
         "1. 重新运行: claw-in-chrome-mcp install-native-host\n"
         "  2. 检查 %APPDATA%\\claw-in-chrome-mcp\\ChromeNativeHost\\ 目录\n"
         "  3. 确认 reg query 注册表项存在"),
        ("Socket 管道不可连接",
         "扩展未运行或浏览器已关闭",
         "1. 完全退出浏览器后重启\n"
         "  2. 在 chrome://extensions/ 确认扩展已启用\n"
         "  3. 打开扩展侧边栏触发 Service Worker"),
        ("navigate 返回 error",
         "浏览器操作执行失败",
         "1. 检查扩展 Service Worker 日志\n"
         "  2. 确认目标 URL 可访问\n"
         "  3. 尝试先手动在浏览器中访问该 URL"),
        ("API Key 认证失败 (401/403)",
         "供应商 API Key 无效或额度不足",
         "1. 检查 API Key 是否正确\n"
         "  2. 确认 API Key 有余额/额度\n"
         "  3. 使用 import_config.html 重新配置"),
    ]

    for i, (error, cause, fix) in enumerate(errors, 1):
        print(f"\n  错误 {i}: {error}")
        print(f"  原因: {cause}")
        print(f"  修复:")
        for line in fix.split("\n"):
            print(f"    {line}")


def print_debug_commands():
    """打印常用诊断命令."""
    print("\n" + "=" * 60)
    print("常用诊断命令")
    print("=" * 60)

    commands = [
        ("环境诊断 (JSON)", "claw-in-chrome-mcp doctor --json"),
        ("环境诊断 (文本)", "claw-in-chrome-mcp doctor"),
        ("安装 Native Host", "claw-in-chrome-mcp install-native-host"),
        ("启动 MCP Server", "claw-in-chrome-mcp serve"),
        ("查看版本", "claw-in-chrome-mcp --version"),
        ("检查 Chrome 注册表",
         'reg query "HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.anthropic.claude_code_browser_extension" /ve'),
        ("检查 Edge 注册表",
         'reg query "HKCU\\Software\\Microsoft\\Edge\\NativeMessagingHosts\\com.anthropic.claude_code_browser_extension" /ve'),
        ("查看 Native Host Manifest",
         'type "%APPDATA%\\claw-in-chrome-mcp\\ChromeNativeHost\\com.anthropic.claude_code_browser_extension.json"'),
        ("查看 Chrome 进程", "tasklist /FI \"IMAGENAME eq chrome.exe\""),
        ("查看命名管道", 'powershell "Get-ChildItem \\\\.\\pipe\\ | Where-Object {$_.Name -like \'*claw*\'}"'),
        ("查看扩展 Service Worker 日志",
         "chrome://extensions/ → 找到 Claw → 点击「检查视图: Service Worker」"),
        ("查看扩展存储",
         "chrome://extensions/ → 找到 Claw → 详细信息 → 检查视图 → chrome.storage.local"),
        ("LAAP 集成验证", "python -m laap.integrations.claw_in_chrome.verify"),
        ("real_chrome 模式测试", "python -m laap.integrations.claw_in_chrome.test_real_chrome"),
        ("配置导入工具", "在浏览器中打开 D:\\claw-in-chrome-main\\claw-in-chrome-main\\import_config.html"),
    ]

    for name, cmd in commands:
        print(f"\n  {name}:")
        print(f"    {cmd}")


def main():
    print("=" * 60)
    print("  Claw in Chrome 连接故障排查诊断")
    print("=" * 60)

    all_ok = True

    all_ok &= check_1_mcp_serve_startup()
    all_ok &= check_2_native_host_registry()
    all_ok &= check_3_extension_loaded()
    all_ok &= check_4_socket_connectable()
    check_5_browser_processes()

    print_error_reference()
    print_debug_commands()

    print("\n" + "=" * 60)
    if all_ok:
        print("  ✓ 所有检查通过，环境正常")
    else:
        print("  ⚠ 部分检查未通过，请按上述指南排查")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
