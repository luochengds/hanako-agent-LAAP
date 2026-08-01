# -*- coding: utf-8 -*-
"""Claw in Chrome 桥接层.

连接 LAAP 与 claw-in-chrome-mcp，提供：
    - doctor()         → 环境诊断（浏览器/扩展/Native Host/Socket 状态）
    - serve()          → 启动 MCP stdio server（异步）
    - list_presets()   → 列出国产模型预设
    - build_config()   → 生成可注入扩展的 provider profile
    - call_tool()      → 通过 MCP 调用浏览器工具（navigate/click/type/screenshot 等）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from laap.integrations.claw_in_chrome import providers

logger = logging.getLogger("laap.integrations.claw_in_chrome")

# claw-in-chrome-mcp CLI 可执行文件名
CIC_MCP_BIN = "claw-in-chrome-mcp"
# 扩展源码目录
EXTENSION_DIR = Path(r"D:\claw-in-chrome-main\claw-in-chrome-main")


def _find_cic_mcp() -> str:
    """查找 claw-in-chrome-mcp 可执行文件路径."""
    path = shutil.which(CIC_MCP_BIN)
    if path:
        return path
    # Windows npm global 位置
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidate = Path(appdata) / "npm" / f"{CIC_MCP_BIN}.cmd"
        if candidate.exists():
            return str(candidate)
    return CIC_MCP_BIN  # 回退到 PATH 查找


class ClawBridge:
    """LAAP 侧的 claw-in-chrome 门面.

    提供编程式访问，所有方法均不抛异常（失败时返回带 error 字段的 dict），
    以保证 PSI 内核循环不被工具错误打断。
    """

    def __init__(self) -> None:
        self._cic_mcp_path: Optional[str] = None
        self._mcp_client = None
        self._init_error: Optional[str] = None
        try:
            self._cic_mcp_path = _find_cic_mcp()
        except Exception as e:
            self._init_error = str(e)
            logger.warning("ClawBridge init: %s", e)

    @property
    def available(self) -> bool:
        return self._cic_mcp_path is not None

    @property
    def cic_mcp_path(self) -> str:
        return self._cic_mcp_path or CIC_MCP_BIN

    # ── 环境诊断 ──────────────────────────────────────────────

    def doctor(self) -> Dict[str, Any]:
        """运行 claw-in-chrome-mcp doctor --json，返回诊断结果."""
        if not self.available:
            return {"ok": False, "error": "claw-in-chrome-mcp not found in PATH"}
        try:
            result = subprocess.run(
                [self.cic_mcp_path, "doctor", "--json"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "error": f"doctor exited {result.returncode}",
                    "stderr": result.stderr[:500],
                }
            data = json.loads(result.stdout)
            data["ok"] = True
            return data
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"doctor JSON parse failed: {e}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "doctor timed out (30s)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def doctor_report(self) -> str:
        """生成人类可读的诊断报告."""
        data = self.doctor()
        if not data.get("ok"):
            return f"[Claw] 诊断失败: {data.get('error', 'unknown')}"

        lines = ["[Claw in Chrome 环境诊断]", "=" * 50]

        # 浏览器
        browsers = data.get("installedBrowsers", [])
        lines.append(f"\n浏览器 ({len(browsers)}):")
        for b in browsers:
            lines.append(f"  - {b.get('browser', '?')}: {b.get('path', '?')}")

        # 扩展
        ext = data.get("extension", {})
        lines.append(f"\n扩展已安装: {'是' if ext.get('installed') else '否'}")
        if not ext.get("installed"):
            lines.append("  ⚠ 请在 Chrome 开发者模式加载扩展:")
            lines.append(f"    {EXTENSION_DIR}")

        # Native Host
        nh = data.get("nativeHost", {})
        lines.append(f"\nNative Host:")
        lines.append(f"  wrapper: {'✓' if nh.get('wrapperExists') else '✗'}")
        manifests = nh.get("manifestPaths", [])
        lines.append(f"  manifest: {len(manifests)} 个")
        regs = nh.get("registryEntries", [])
        lines.append(f"  注册表: {len(regs)} 个")

        # Socket
        sock = data.get("socket", {})
        lines.append(f"\nSocket:")
        lines.append(f"  已发现管道: {len(sock.get('discoveredPaths', []))}")
        lines.append(f"  可连接: {len(sock.get('connectablePaths', []))}")

        # 建议
        suggestions = data.get("suggestions", [])
        if suggestions:
            lines.append(f"\n建议:")
            for s in suggestions:
                lines.append(f"  → {s}")

        return "\n".join(lines)

    # ── 国产模型预设 ──────────────────────────────────────────

    @staticmethod
    def list_presets() -> List[str]:
        """返回所有国产模型预设名称."""
        return providers.list_presets()

    @staticmethod
    def list_all_models() -> Dict[str, List[str]]:
        """返回 {供应商: [模型列表]}."""
        return providers.list_all_models()

    @staticmethod
    def get_preset(name: str) -> Optional[Dict[str, Any]]:
        """获取指定预设的详细信息."""
        return providers.get_preset(name)

    @staticmethod
    def build_config(preset_name: str, api_key: str) -> Dict[str, Any]:
        """根据预设和 API Key 生成可注入扩展存储的 profile.

        生成的 JSON 可直接写入 Chrome 扩展的 chrome.storage.local，
        key 为 "customProviderProfiles"（数组）和 "customProviderActiveProfileId"。
        """
        return providers.build_profile(preset_name, api_key)

    @staticmethod
    def build_storage_json(preset_name: str, api_key: str) -> str:
        """生成完整的扩展存储 JSON（用于一键导入）.

        包含 profiles 数组、activeProfileId、legacy config、HTTP 启用等。
        """
        profile = providers.build_profile(preset_name, api_key)
        storage = {
            "customProviderProfiles": [profile],
            "customProviderActiveProfileId": profile["id"],
            "customProviderConfig": {
                "name": profile["name"],
                "format": profile["format"],
                "baseUrl": profile["baseUrl"],
                "apiKey": profile["apiKey"],
                "defaultModel": profile["defaultModel"],
                "fastModel": profile["fastModel"],
                "reasoningEffort": profile["reasoningEffort"],
                "maxOutputTokens": profile["maxOutputTokens"],
                "contextWindow": profile["contextWindow"],
                "fetchedModels": profile["fetchedModels"],
            },
            "customProviderAllowHttp": True,
            "customProviderAllowHttpMigrated": True,
            "selectedModel": profile["defaultModel"],
            "selectedModelQuickMode": profile["fastModel"],
        }
        return json.dumps(storage, ensure_ascii=False, indent=2)

    # ── MCP 工具调用 ──────────────────────────────────────────

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """通过 MCP stdio 调用 claw-in-chrome 浏览器工具.

        直接用 subprocess + JSON-RPC 2.0 与 claw-in-chrome-mcp serve 通信，
        不依赖 Python MCP SDK（避免 laap.mcp 与 PyPI mcp 包命名冲突）。
        """
        return self._call_tool_sync(tool_name, arguments)

    def _call_tool_sync(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """同步调用 MCP 工具（通过 JSON-RPC over stdio）."""
        import threading

        result_holder = {"result": None, "error": None}

        def _worker():
            try:
                proc = subprocess.Popen(
                    [self.cic_mcp_path, "serve"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,  # 行缓冲
                )

                # 1. 发送 initialize 请求
                init_msg = self._build_jsonrpc("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "laap-claw-bridge",
                        "version": "1.0.0",
                    },
                }, req_id=1)
                proc.stdin.write(init_msg + "\n")
                proc.stdin.flush()

                # 读取 initialize 响应
                init_resp = self._read_jsonrpc(proc.stdout, timeout=10)
                if not init_resp:
                    result_holder["error"] = "MCP initialize 超时或无响应"
                    proc.terminate()
                    return

                # 2. 发送 initialized 通知
                notif = self._build_jsonrpc("notifications/initialized", {}, req_id=None)
                proc.stdin.write(notif + "\n")
                proc.stdin.flush()

                # 3. 调用工具
                call_msg = self._build_jsonrpc("tools/call", {
                    "name": tool_name,
                    "arguments": arguments,
                }, req_id=2)
                proc.stdin.write(call_msg + "\n")
                proc.stdin.flush()

                # 读取工具调用响应
                call_resp = self._read_jsonrpc(proc.stdout, timeout=30)
                proc.terminate()

                if not call_resp:
                    # 尝试读取 stderr 获取错误信息
                    stderr_data = ""
                    try:
                        stderr_data = proc.stderr.read(500) or ""
                    except Exception:
                        pass
                    result_holder["error"] = (
                        f"MCP tools/call 超时或无响应。"
                        f"stderr: {stderr_data[:200]}"
                    )
                    return

                if "error" in call_resp:
                    err = call_resp["error"]
                    result_holder["error"] = (
                        f"MCP error {err.get('code', '?')}: "
                        f"{err.get('message', 'unknown')}"
                    )
                    return

                # 提取 result 内容
                result_obj = call_resp.get("result", {})
                content = result_obj.get("content", [])
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                if texts:
                    result_holder["result"] = "\n".join(texts)
                else:
                    result_holder["result"] = json.dumps(result_obj, ensure_ascii=False)

            except FileNotFoundError:
                result_holder["error"] = f"claw-in-chrome-mcp 未找到: {self.cic_mcp_path}"
            except subprocess.TimeoutExpired:
                result_holder["error"] = "MCP 调用超时"
            except Exception as e:
                result_holder["error"] = f"MCP 调用异常: {e}"

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=45)

        if thread.is_alive():
            return json.dumps({"error": "MCP 调用超时 (45s)"})
        if result_holder["error"]:
            return json.dumps({"error": result_holder["error"]})
        return result_holder["result"] or json.dumps({"result": "(empty)"})

    @staticmethod
    def _build_jsonrpc(method: str, params: dict, req_id=None) -> str:
        """构建 JSON-RPC 2.0 消息."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            msg["id"] = req_id
        return json.dumps(msg)

    @staticmethod
    def _read_jsonrpc(stream, timeout=10) -> dict | None:
        """从流中读取一行 JSON-RPC 响应."""
        import select as _select
        start = __import__("time").time()
        while __import__("time").time() - start < timeout:
            line = stream.readline()
            if not line:
                __import__("time").sleep(0.1)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                # 可能是非 JSON 输出（日志行），跳过
                continue
        return None

    # ── 扩展路径 ──────────────────────────────────────────────

    @staticmethod
    def extension_path() -> str:
        """返回扩展源码目录路径（用于 Chrome 开发者模式加载）."""
        return str(EXTENSION_DIR)

    @staticmethod
    def native_host_installed() -> bool:
        """检查 Native Messaging Host 是否已安装."""
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return False
        manifest = (
            Path(appdata) / "claw-in-chrome-mcp" / "ChromeNativeHost" /
            "com.anthropic.claude_code_browser_extension.json"
        )
        return manifest.exists()


def register_mcp_server() -> bool:
    """将 claw-in-chrome 注册到 LAAP 的 MCP 配置中.

    返回 True 表示注册成功（新建或已存在）。
    """
    try:
        from laap.mcp.config import add_server, get_server
        if get_server("claw-in-chrome"):
            return True  # 已存在
        cic_path = _find_cic_mcp()
        return add_server(
            name="claw-in-chrome",
            command=cic_path,
            args=["serve"],
            transport="stdio",
            enabled=True,
        )
    except Exception as e:
        logger.error("Failed to register MCP server: %s", e)
        return False
