# -*- coding: utf-8 -*-
"""Claw in Chrome 集成验证脚本.

验证项：
    1. claw-in-chrome-mcp CLI 可用
    2. Native Messaging Host 已安装
    3. 扩展源码目录存在
    4. 国产模型预设加载正确
    5. ClawBridge 初始化成功
    6. doctor 诊断运行通过
    7. provider profile 生成正确
    8. storage JSON 格式校验
    9. LAAP MCP 配置注册成功
    10. browser_auto 模式切换正常
"""

import json
import os
import sys
import subprocess
from pathlib import Path

# 确保可导入 laap
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def check_1_cli_available():
    """检查 claw-in-chrome-mcp CLI 是否可用."""
    import shutil
    path = shutil.which("claw-in-chrome-mcp")
    if path:
        return True, f"CLI found: {path}"
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidate = Path(appdata) / "npm" / "claw-in-chrome-mcp.cmd"
        if candidate.exists():
            return True, f"CLI found: {candidate}"
    return False, "claw-in-chrome-mcp not found in PATH"


def check_2_native_host():
    """检查 Native Messaging Host 是否已安装."""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return False, "APPDATA not set"
    manifest = (
        Path(appdata) / "claw-in-chrome-mcp" / "ChromeNativeHost" /
        "com.anthropic.claude_code_browser_extension.json"
    )
    if manifest.exists():
        return True, f"Native Host manifest: {manifest}"
    return False, f"Manifest not found at {manifest}"


def check_3_extension_dir():
    """检查扩展源码目录."""
    ext_dir = Path(r"D:\claw-in-chrome-main\claw-in-chrome-main")
    manifest = ext_dir / "manifest.json"
    if manifest.exists():
        return True, f"Extension dir: {ext_dir}"
    return False, f"manifest.json not found at {ext_dir}"


def check_4_presets():
    """检查国产模型预设."""
    from laap.integrations.claw_in_chrome.providers import (
        PROVIDER_PRESETS, list_presets, get_preset, list_all_models,
    )
    count = len(PROVIDER_PRESETS)
    if count < 10:
        return False, f"Only {count} presets (expected >= 10)"
    presets = list_presets()
    models = list_all_models()
    # 验证关键供应商存在
    required_vendors = ["deepseek", "alibaba", "zhipu", "moonshot", "baidu"]
    found_vendors = [p["vendor"] for p in PROVIDER_PRESETS]
    missing = [v for v in required_vendors if v not in found_vendors]
    if missing:
        return False, f"Missing vendors: {missing}"
    return True, f"{count} presets loaded, {len(models)} vendors with models"


def check_5_bridge_init():
    """检查 ClawBridge 初始化."""
    from laap.integrations.claw_in_chrome.adapter import ClawBridge
    bridge = ClawBridge()
    if bridge.available:
        return True, f"Bridge available, cic_mcp: {bridge.cic_mcp_path}"
    return False, f"Bridge init error: {bridge._init_error}"


def check_6_doctor():
    """运行 doctor 诊断."""
    from laap.integrations.claw_in_chrome.adapter import ClawBridge
    bridge = ClawBridge()
    data = bridge.doctor()
    if data.get("ok"):
        browsers = len(data.get("installedBrowsers", []))
        nh = data.get("nativeHost", {})
        nh_ok = nh.get("wrapperExists", False)
        return True, f"Doctor OK: {browsers} browsers, native_host={nh_ok}"
    return False, f"Doctor failed: {data.get('error', 'unknown')}"


def check_7_profile_build():
    """验证 provider profile 生成."""
    from laap.integrations.claw_in_chrome.providers import build_profile
    profile = build_profile("DeepSeek", "sk-test-123")
    required_fields = ["id", "name", "format", "baseUrl", "apiKey", "defaultModel"]
    missing = [f for f in required_fields if f not in profile]
    if missing:
        return False, f"Missing fields: {missing}"
    if profile["format"] != "openai_chat":
        return False, f"Wrong format: {profile['format']}"
    if profile["apiKey"] != "sk-test-123":
        return False, "API Key mismatch"
    return True, f"Profile OK: {profile['name']} / {profile['defaultModel']}"


def check_8_storage_json():
    """验证 storage JSON 格式."""
    from laap.integrations.claw_in_chrome.adapter import ClawBridge
    bridge = ClawBridge()
    storage_str = bridge.build_storage_json("通义千问 (Qwen)", "sk-qwen-test")
    storage = json.loads(storage_str)
    required_keys = [
        "customProviderProfiles", "customProviderActiveProfileId",
        "customProviderConfig", "customProviderAllowHttp",
    ]
    missing = [k for k in required_keys if k not in storage]
    if missing:
        return False, f"Missing storage keys: {missing}"
    profiles = storage["customProviderProfiles"]
    if not isinstance(profiles, list) or len(profiles) != 1:
        return False, f"Expected 1 profile, got {len(profiles)}"
    return True, f"Storage JSON OK: {profiles[0]['name']}"


def check_9_mcp_config():
    """验证 MCP server 注册."""
    from laap.mcp.config import ensure_default_servers, load_config, get_server
    ensure_default_servers()
    srv = get_server("claw-in-chrome")
    if not srv:
        return False, "claw-in-chrome not in MCP config"
    if srv.get("transport") != "stdio":
        return False, f"Wrong transport: {srv.get('transport')}"
    if srv.get("args") != ["serve"]:
        return False, f"Wrong args: {srv.get('args')}"
    return True, f"MCP config OK: {srv['command']} {srv['args']}"


def check_10_browser_mode():
    """验证 browser_auto 模式切换."""
    from laap.tools.browser_auto import set_browser_mode, get_browser_mode
    # 切换到 real_chrome
    result = set_browser_mode("real_chrome")
    data = json.loads(result)
    if data.get("mode") != "real_chrome":
        return False, f"Failed to switch to real_chrome: {data}"
    # 切换回 sandbox
    set_browser_mode("sandbox")
    if get_browser_mode() != "sandbox":
        return False, "Failed to switch back to sandbox"
    return True, "Mode switch OK: sandbox ↔ real_chrome"


def check_11_tools_register():
    """验证工具注册."""
    from laap.tools.tool_registry import ToolRegistry
    from laap.integrations.claw_in_chrome.tools import register_all
    registry = ToolRegistry()
    register_all(registry)
    # 检查关键工具
    expected = ["claw_doctor", "claw_presets", "claw_build_config",
                "claw_navigate", "claw_screenshot", "claw_evaluate"]
    registered = [t.name for t in registry.list()]
    missing = [t for t in expected if t not in registered]
    if missing:
        return False, f"Missing tools: {missing}"
    return True, f"{len(registered)} tools registered"


def main():
    checks = [
        ("CLI 可用", check_1_cli_available),
        ("Native Host", check_2_native_host),
        ("扩展目录", check_3_extension_dir),
        ("国产模型预设", check_4_presets),
        ("ClawBridge 初始化", check_5_bridge_init),
        ("Doctor 诊断", check_6_doctor),
        ("Profile 生成", check_7_profile_build),
        ("Storage JSON", check_8_storage_json),
        ("MCP 配置注册", check_9_mcp_config),
        ("Browser 模式切换", check_10_browser_mode),
        ("工具注册", check_11_tools_register),
    ]

    print("=" * 60)
    print("Claw in Chrome 集成验证")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, check_fn in checks:
        try:
            ok, msg = check_fn()
            status = "✓ PASS" if ok else "✗ FAIL"
            print(f"\n{status} [{name}]")
            print(f"  {msg}")
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n✗ ERROR [{name}]")
            print(f"  {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败, 共 {len(checks)} 项")

    if failed == 0:
        print("\n🎉 全部验证通过！")
        print("\n下一步:")
        print("  1. 打开 chrome://extensions/")
        print("  2. 开启开发者模式")
        print("  3. 加载已解压的扩展程序: D:\\claw-in-chrome-main\\claw-in-chrome-main")
        print("  4. 在扩展设置中配置国产模型供应商（或使用 claw_build_config 生成配置）")
        print("  5. 使用 browser_set_mode('real_chrome') 切换到真实浏览器模式")
    else:
        print(f"\n⚠ {failed} 项失败，请检查上述输出。")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
