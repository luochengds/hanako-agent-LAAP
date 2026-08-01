"""
LAAP — Browser Automation Tools
Full browser control using Playwright: navigate, click, type, screenshot, extract.

支持两种模式：
    - sandbox (默认): Playwright 启动独立 Chromium（隔离沙箱，无登录态）
    - real_chrome: 通过 claw-in-chrome MCP 控制用户真实 Chrome（保留 Cookie/登录态）
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging
import json
import base64
import threading
import time
import re
import tempfile
import os
from urllib.parse import urlparse

from laap.tools.base import Tool, ToolResult
from laap.tools.tool_registry import ToolRegistry

logger = logging.getLogger("laap.tools.browser")

# 保留旧的全局变量作为 CDP / 测试兼容占位，实际会话由 _BrowserSessionManager 管理
_browser = None
_page = None

# 浏览器模式：sandbox (Playwright) 或 real_chrome (claw-in-chrome MCP)
_browser_mode = "sandbox"
_headless = True

# 反检测开关
_stealth_enabled = False

# 对话框策略
_dialog_policy: str = "dismiss"  # dismiss | accept | prompt
_dialog_timeout: float = 5.0

# 会话过期时间（秒）
_SESSION_TTL_SECONDS = 300
_REAPER_INTERVAL_SECONDS = 60

_USER_AGENT_STEALTH = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# 简单规则：拦截 URL 中疑似硬编码凭据的参数
_EMBEDDED_SECRET_RE = re.compile(
    r"[?&](token|api[_-]?key|secret|password|passwd|auth|access_token|private_key)=",
    re.IGNORECASE,
)


def _ok(data: Dict[str, Any]) -> ToolResult:
    """Return a successful ToolResult whose output is a JSON string."""
    return ToolResult(success=True, output=json.dumps(data, ensure_ascii=False), metadata=data)


def _err(error: str, data: Optional[Dict[str, Any]] = None) -> ToolResult:
    """Return a failed ToolResult."""
    return ToolResult(success=False, output="", error=error, metadata=data or {})


def _tool_result_from_json(raw: str) -> ToolResult:
    """Convert a JSON string (e.g. from real_chrome dispatch) into a ToolResult."""
    try:
        data = json.loads(raw)
    except Exception:
        return ToolResult(success=True, output=raw)
    success = data.get("success", True) and data.get("error") is None
    return ToolResult(
        success=success,
        output=raw,
        error=data.get("error"),
        metadata=data,
    )


# ═══════════════════════════════════════════════════════════
# 任务级会话管理
# ═══════════════════════════════════════════════════════════

class _BrowserSessionManager:
    """按 task_id 管理 Playwright 页面/浏览器/上下文生命周期。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._reaper: Optional[threading.Thread] = None

    def _start_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return

        def reap_loop() -> None:
            while True:
                time.sleep(_REAPER_INTERVAL_SECONDS)
                self._reap_inactive()

        self._reaper = threading.Thread(target=reap_loop, daemon=True)
        self._reaper.start()

    def _reap_inactive(self) -> None:
        now = time.time()
        stale: List[str] = []
        with self._lock:
            for task_id, session in self._sessions.items():
                if now - session.get("last_used", now) > _SESSION_TTL_SECONDS:
                    stale.append(task_id)
        for task_id in stale:
            logger.info("[INFO] Reaping inactive browser session for task_id=%s", task_id)
            self.cleanup_session(task_id)

    def get_session(self, task_id: str = "default", headless: Optional[bool] = None) -> Dict[str, Any]:
        """获取或创建指定 task_id 的浏览器会话。"""
        if headless is None:
            headless = _headless

        with self._lock:
            session = self._sessions.get(task_id)
            if session is not None:
                page = session.get("page")
                if page is not None and not page.is_closed():
                    session["last_used"] = time.time()
                    return session
                # 页面已关闭，清理后重建
                self._close_session(session)
                self._sessions.pop(task_id, None)

        # 创建新会话
        session = self._create_session(headless)
        session["task_id"] = task_id
        with self._lock:
            self._sessions[task_id] = session
        self._start_reaper()
        return session

    def _create_session(self, headless: bool) -> Dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright is not installed") from exc

        playwright = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        browser = playwright.chromium.launch(headless=headless, args=args)

        context_kwargs: Dict[str, Any] = {}
        if _stealth_enabled:
            context_kwargs["user_agent"] = _USER_AGENT_STEALTH

        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_viewport_size({"width": 1280, "height": 800})
        page.on("dialog", _handle_dialog)

        if _stealth_enabled:
            try:
                page.add_init_script(
                    "() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); }"
                )
            except Exception as exc:
                logger.warning("[WARN] Failed to inject stealth init script: %s", exc)

        logger.info("[INFO] Browser session launched (headless=%s, stealth=%s)", headless, _stealth_enabled)
        return {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page,
            "created_at": time.time(),
            "last_used": time.time(),
            "last_snapshot": None,
        }

    def _close_session(self, session: Dict[str, Any]) -> None:
        for key in ("page", "context", "browser", "playwright"):
            obj = session.get(key)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            try:
                if hasattr(obj, "stop"):
                    obj.stop()
            except Exception:
                pass

    def cleanup_session(self, task_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(task_id, None)
        if session is not None:
            self._close_session(session)
            logger.info("[OK] Cleaned up browser session for task_id=%s", task_id)

    def cleanup_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        for task_id, session in sessions:
            self._close_session(session)
            logger.info("[OK] Cleaned up browser session for task_id=%s", task_id)

    def list_task_ids(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())


_session_manager = _BrowserSessionManager()


def _get_session(task_id: str = "default", headless: Optional[bool] = None) -> Dict[str, Any]:
    return _session_manager.get_session(task_id, headless)


def _get_page(task_id: str = "default") -> Optional[Any]:
    session = _get_session(task_id)
    page = session.get("page")
    if page is not None and not page.is_closed():
        return page
    return None


def cleanup_session(task_id: str) -> None:
    """关闭指定 task_id 的浏览器会话。"""
    _session_manager.cleanup_session(task_id)


def cleanup_all_sessions() -> None:
    """关闭所有浏览器会话。"""
    global _browser, _page
    _session_manager.cleanup_all()
    _browser = None
    _page = None


def _cleanup_browser():
    """旧版清理入口，代理到会话管理器。"""
    cleanup_all_sessions()


# ═══════════════════════════════════════════════════════════
# 基础工具函数
# ═══════════════════════════════════════════════════════════


def set_browser_mode(mode: str = "sandbox") -> ToolResult:
    """切换浏览器模式.

    Args:
        mode: "sandbox" = Playwright 隔离沙箱, "real_chrome" = 真实 Chrome

    Returns:
        ToolResult 确认消息
    """
    global _browser_mode
    mode = mode.lower().strip()
    if mode not in ("sandbox", "real_chrome"):
        return _err(f"无效模式 '{mode}'，可选: sandbox, real_chrome")
    _browser_mode = mode
    return _ok({
        "mode": _browser_mode,
        "description": (
            "Playwright 隔离沙箱（无登录态）" if _browser_mode == "sandbox"
            else "真实 Chrome（保留 Cookie/登录态，通过 claw-in-chrome MCP）"
        ),
    })


def get_browser_mode() -> str:
    """返回当前浏览器模式."""
    return _browser_mode


def set_browser_visible(visible: bool) -> ToolResult:
    """Set whether the browser should be launched in visible (non-headless) mode.

    The setting takes effect the next time a session is created.

    Args:
        visible: True 表示非 headless 模式。
    """
    global _headless
    _headless = not visible
    return _ok({"visible": visible, "headless": _headless})


def set_browser_stealth(enabled: bool = True) -> ToolResult:
    """开启/关闭反检测模式（下次启动会话时生效）。

    Args:
        enabled: True 启用 stealth 参数与真实 UA。
    """
    global _stealth_enabled
    _stealth_enabled = bool(enabled)
    return _ok({"stealth_enabled": _stealth_enabled})


def _dispatch_real_chrome(tool_name: str, arguments: dict) -> str:
    """在 real_chrome 模式下，通过 claw-in-chrome MCP 调用真实浏览器工具."""
    try:
        from laap.integrations.claw_in_chrome.adapter import ClawBridge
        import asyncio
        bridge = ClawBridge()
        return asyncio.run(bridge.call_tool(tool_name, arguments))
    except Exception as e:
        return json.dumps({
            "error": f"real_chrome dispatch failed: {e}",
            "tool": tool_name,
            "mode": "real_chrome",
        })


def _is_url_safe(url: str) -> bool:
    """检查 URL 是否安全：拦截内网、回环、云元数据与疑似含凭据的 URL。"""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme == "about":
        # Allow internal browser pages (e.g. about:blank) for tests/initialization.
        return True

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname or ""
    if hostname == "169.254.169.254":
        return False

    import ipaddress
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass

    if _EMBEDDED_SECRET_RE.search(url):
        return False

    return True


def _resolve_task_id(kw: Dict[str, Any]) -> str:
    return kw.pop("task_id", "default")


def _navigate_with_retry(page: Any, url: str) -> None:
    """导航并超时后重试一次。"""
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        return
    except Exception as first_exc:
        logger.warning("[WARN] Navigation timeout for %s, retrying once: %s", url, first_exc)
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            # 如果刷新也失败，至少再尝试一次原始导航
            page.goto(url, wait_until="domcontentloaded", timeout=30000)


def _retry_action(action_fn, retries: int = 1, delay: float = 0.5):
    """对元素操作执行一次重试。"""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return action_fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                logger.warning("[WARN] Action failed, retrying in %.1fs: %s", delay, exc)
                time.sleep(delay)
    raise last_exc


def _resolve_locator(page: Any, selector: str, ref: str, task_id: str):
    """根据 selector 或 ref 返回可操作的 CSS selector。"""
    if ref:
        ref_id = ref[1:] if ref.startswith("@") else ref
        return f'[data-laap-ref="{ref_id}"]'
    if selector:
        return selector
    raise ValueError("Either selector or ref must be provided")


# ═══════════════════════════════════════════════════════════
# 核心浏览器工具
# ═══════════════════════════════════════════════════════════


def browser_navigate(url: str = "", task_id: str = "default", **kw) -> ToolResult:
    """Navigate browser to a URL."""
    if not _is_url_safe(url):
        return _err(f"[ERROR] URL blocked by safety policy: {url}", {"url": url})

    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("navigate", {"url": url}))
    try:
        session = _get_session(task_id)
        page = session["page"]
        _navigate_with_retry(page, url)
        return _ok({
            "url": url,
            "title": page.title(),
            "status": page.evaluate("document.readyState"),
            "task_id": task_id,
        })
    except Exception as e:
        return _err(str(e), {"url": url, "task_id": task_id})


def browser_click(selector: str = "", ref: str = "", task_id: str = "default", **kw) -> ToolResult:
    """Click an element by CSS selector or ref ID."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("click", {"selector": selector}))
    try:
        session = _get_session(task_id)
        page = session["page"]
        target = _resolve_locator(page, selector, ref, task_id)
        _retry_action(lambda: page.click(target, timeout=10000))
        return _ok({"action": "click", "selector": selector, "ref": ref, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"action": "click", "selector": selector, "ref": ref, "task_id": task_id})


def browser_type(selector: str = "", text: str = "", ref: str = "", task_id: str = "default", **kw) -> ToolResult:
    """Type text into an input field by CSS selector or ref ID."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("type", {"selector": selector, "text": text}))
    try:
        session = _get_session(task_id)
        page = session["page"]
        target = _resolve_locator(page, selector, ref, task_id)
        _retry_action(lambda: page.fill(target, text, timeout=10000))
        return _ok({"action": "type", "selector": selector, "ref": ref, "text_len": len(text), "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"action": "type", "selector": selector, "ref": ref, "task_id": task_id})


def browser_get_text(selector: str = "", task_id: str = "default", **kw) -> ToolResult:
    """Get text content of element(s) by CSS selector."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("get_text", {"selector": selector}))
    try:
        page = _get_page(task_id)
        els = page.query_selector_all(selector)
        results = [el.text_content() or "" for el in els[:50]]
        return _ok({"selector": selector, "count": len(results), "results": results[:20], "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"selector": selector, "task_id": task_id})


def browser_get_html(selector: str = "body", task_id: str = "default", **kw) -> ToolResult:
    """Get inner HTML of an element. Default: entire body."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("get_html", {"selector": selector}))
    try:
        page = _get_page(task_id)
        html = page.inner_html(selector, timeout=10000)
        if len(html) > 100000:
            html = html[:100000] + "\n... (truncated)"
        return _ok({"selector": selector, "html_len": len(html), "html": html, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"selector": selector, "task_id": task_id})


def browser_title(task_id: str = "default", **kw) -> ToolResult:
    """Get current page title and URL."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("get_title", {}))
    try:
        page = _get_page(task_id)
        return _ok({"title": page.title(), "url": page.url, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_get_title(task_id: str = "default", **kw) -> ToolResult:
    """Alias for browser_title."""
    return browser_title(task_id=task_id, **kw)


def browser_screenshot(full_page: bool = False, task_id: str = "default", **kw) -> ToolResult:
    """Take screenshot of current page. Returns base64 PNG."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("screenshot", {"full_page": full_page}))
    try:
        page = _get_page(task_id)
        img_bytes = page.screenshot(full_page=full_page)
        b64 = base64.b64encode(img_bytes).decode()
        return _ok({"format": "png", "data_base64": b64, "data_len": len(b64), "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_evaluate(js_code: str = "", task_id: str = "default", **kw) -> ToolResult:
    """Execute JavaScript in the page."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("evaluate", {"script": js_code}))
    try:
        page = _get_page(task_id)
        result = page.evaluate(js_code)
        return _ok({"result": str(result)[:5000], "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_scroll(direction: str = "down", amount: int = 500, task_id: str = "default", **kw) -> ToolResult:
    """Scroll page: up/down/left/right."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("scroll", {"direction": direction, "amount": amount}))
    try:
        page = _get_page(task_id)
        dx, dy = {
            "down": (0, amount),
            "up": (0, -amount),
            "left": (-amount, 0),
            "right": (amount, 0),
        }.get(direction, (0, amount))
        page.evaluate(f"window.scrollBy({dx}, {dy})")
        return _ok({"action": "scroll", "direction": direction, "amount": amount, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_get_links(task_id: str = "default", **kw) -> ToolResult:
    """Get all links (href + text) on current page."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("get_links", {}))
    try:
        page = _get_page(task_id)
        links = page.evaluate(
            """() => Array.from(document.querySelectorAll("a[href]")).slice(0,100).map(a => ({
                href: a.href,
                text: a.textContent.trim().slice(0,100)
            }))"""
        )
        return _ok({"count": len(links), "links": links[:50], "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_get_visible_text(task_id: str = "default", **kw) -> ToolResult:
    """Get all visible text on page (truncated to 50K)."""
    if _browser_mode == "real_chrome":
        return _tool_result_from_json(_dispatch_real_chrome("get_visible_text", {}))
    try:
        page = _get_page(task_id)
        text = (page.evaluate("() => document.body.innerText") or "")[:50000]
        return _ok({"url": page.url, "title": page.title(), "text_len": len(text), "text": text, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_new_tab(url: str = "about:blank", task_id: str = "default", **kw) -> ToolResult:
    """Open a new browser tab."""
    try:
        session = _get_session(task_id)
        context = session["context"]
        new_page = context.new_page()
        new_page.set_viewport_size({"width": 1280, "height": 800})
        new_page.on("dialog", _handle_dialog)
        if url != "about:blank":
            _navigate_with_retry(new_page, url)
        session["page"] = new_page
        return _ok({"url": new_page.url, "title": new_page.title(), "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_list_tabs(task_id: str = "default", **kw) -> ToolResult:
    """List all open browser tabs."""
    try:
        session = _get_session(task_id)
        browser = session["browser"]
        tabs = [{"url": p.url, "title": p.title()} for ctx in browser.contexts for p in ctx.pages]
        return _ok({"count": len(tabs), "tabs": tabs, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"tabs": [], "task_id": task_id})


def browser_switch_tab(index: int = 0, task_id: str = "default", **kw) -> ToolResult:
    """Switch to a tab by index."""
    try:
        session = _get_session(task_id)
        browser = session["browser"]
        pages = [p for ctx in browser.contexts for p in ctx.pages]
        if index < 0 or index >= len(pages):
            return _err(f"Tab index {index} out of range ({len(pages)} tabs)")
        session["page"] = pages[index]
        page = session["page"]
        return _ok({"action": "switch_tab", "index": index, "url": page.url, "title": page.title(), "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_close(task_id: str = "default", **kw) -> ToolResult:
    """Close browser and clean up."""
    cleanup_session(task_id)
    return _ok({"action": "close", "task_id": task_id})


# ═══════════════════════════════════════════════════════════
# 高级浏览器功能（Hermes 级别）
# ═══════════════════════════════════════════════════════════

_SNAPSHOT_SCRIPT = r"""
() => {
    const interactiveRoles = new Set([
        "button", "link", "textbox", "checkbox", "radio", "combobox",
        "menuitem", "tab", "searchbox", "spinbutton", "slider", "switch"
    ]);

    function isInteractive(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === "a" && el.href) return true;
        if (["button", "input", "textarea", "select"].includes(tag)) return true;
        const role = el.getAttribute("role");
        if (role && interactiveRoles.has(role)) return true;
        if (el.onclick || el.getAttribute("onclick")) return true;
        return false;
    }

    function getRole(el) {
        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute("role");
        if (role) return role;
        if (tag === "a") return "link";
        if (tag === "button") return "button";
        if (tag === "input") return el.type || "textbox";
        if (tag === "textarea") return "textbox";
        if (tag === "select") return "combobox";
        if (tag === "img") return "img";
        return tag;
    }

    function getName(el) {
        return (
            el.getAttribute("aria-label") ||
            el.getAttribute("placeholder") ||
            el.getAttribute("title") ||
            el.getAttribute("name") ||
            el.id ||
            el.textContent.trim().slice(0, 80) ||
            ""
        );
    }

    // 清理旧的 ref 标记
    document.querySelectorAll("[data-laap-ref]").forEach(el => el.removeAttribute("data-laap-ref"));

    const refs = {};
    let refCounter = 0;
    const lines = [];

    function walk(node, depth) {
        if (!node) return;
        if (node.nodeType === Node.TEXT_NODE) {
            const txt = node.textContent.trim();
            if (txt) {
                lines.push("  ".repeat(depth) + txt.slice(0, 120));
            }
            return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;

        const el = node;
        const tag = el.tagName.toLowerCase();
        if (["script", "style", "noscript"].includes(tag)) return;

        const role = getRole(el);
        const name = getName(el);
        let refMarker = "";

        if (isInteractive(el)) {
            refCounter += 1;
            const refId = "e" + refCounter;
            el.setAttribute("data-laap-ref", refId);
            const selector = tag +
                (el.id ? "#" + el.id : "") +
                (el.className ? "." + el.className.split(/\s+/)[0] : "");
            refs["@" + refId] = {
                tag: tag,
                role: role,
                name: name,
                type: el.type || "",
                value: el.value || "",
                placeholder: el.getAttribute("placeholder") || "",
                id: el.id || "",
                class: el.className || "",
                selector: selector,
            };
            refMarker = "[@" + refId + "] ";
        }

        const label = (role + (name ? ' "' + name + '"' : "")).trim();
        lines.push("  ".repeat(depth) + refMarker + label);

        for (const child of el.childNodes) {
            walk(child, depth + 1);
        }
    }

    if (document.body) {
        walk(document.body, 0);
    }

    return {
        url: location.href,
        title: document.title,
        element_count: refCounter,
        snapshot: lines.join("\n"),
        refs: refs,
    };
}
"""


def browser_snapshot(full: bool = False, task_id: str = "default", **kw) -> ToolResult:
    """获取页面可访问性快照，返回结构化树与交互元素 ref ID。

    Args:
        full: 是否包含完整页面树（当前仅影响输出截断）。
        task_id: 浏览器会话 ID。
    """
    try:
        session = _get_session(task_id)
        page = session["page"]
        data = page.evaluate(_SNAPSHOT_SCRIPT)
        session["last_snapshot"] = data
        snapshot_text = data["snapshot"]
        if not full and len(snapshot_text) > 20000:
            snapshot_text = snapshot_text[:20000] + "\n... (truncated)"
        return _ok({
            "url": data["url"],
            "title": data["title"],
            "element_count": data["element_count"],
            "snapshot": snapshot_text,
            "refs": data["refs"],
            "task_id": task_id,
        })
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_vision(question: str = "", task_id: str = "default", annotate: bool = False, **kw) -> ToolResult:
    """截取当前页面截图并返回视觉分析信封。

    Args:
        question: 希望针对截图回答的问题。
        task_id: 浏览器会话 ID。
        annotate: 是否在截图上标注交互元素（当前为占位开关）。
    """
    try:
        session = _get_session(task_id)
        page = session["page"]
        suffix = ".png"
        fd, path = tempfile.mkstemp(prefix="laap_browser_vision_", suffix=suffix)
        os.close(fd)
        page.screenshot(path=path, full_page=False)

        # 读取截图并生成 base64；可选复用 vision 工具获取元数据/OCR
        with open(path, "rb") as f:
            img_bytes = f.read()
        b64 = base64.b64encode(img_bytes).decode()

        metadata: Dict[str, Any] = {}
        try:
            from laap.tools.vision import screenshot_analyze
            vision_result = screenshot_analyze(image_path=path)
            if vision_result.success:
                try:
                    metadata = json.loads(vision_result.output)
                except Exception:
                    pass
                metadata.update(vision_result.metadata or {})
        except Exception as exc:
            logger.debug("[INFO] screenshot_analyze not available for browser_vision: %s", exc)

        supports_vision = _llm_supports_vision()

        payload = {
            "task_id": task_id,
            "question": question,
            "screenshot_path": path,
            "screenshot_base64": b64,
            "format": metadata.get("format"),
            "size": metadata.get("size"),
            "vision_supported": supports_vision,
        }

        if supports_vision:
            payload["analysis"] = "Vision model envelope ready; pass screenshot_base64 to multimodal LLM."
        else:
            payload["analysis"] = "Text placeholder: configure a vision-capable LLM to analyze the screenshot."

        if annotate:
            payload["annotate"] = "Annotation not implemented in this version."

        return _ok(payload)
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def _llm_supports_vision() -> bool:
    """探测当前配置的 LLM 是否支持视觉输入（保守默认 False）。"""
    if os.environ.get("LAAP_LLM_VISION", "").lower() in ("1", "true", "yes"):
        return True
    try:
        from laap.config import settings
        return bool(getattr(settings, "LLM_VISION", False))
    except Exception:
        pass
    return False


def browser_wait_for_selector(selector: str, timeout: float = 10.0, task_id: str = "default", **kw) -> ToolResult:
    """等待元素出现。

    Args:
        selector: CSS 选择器。
        timeout: 超时时间（秒）。
        task_id: 浏览器会话 ID。
    """
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        page.wait_for_selector(selector, timeout=timeout * 1000)
        return _ok({"waited": True, "selector": selector, "task_id": task_id})
    except Exception as e:
        return _err(f"[ERROR] Wait timed out: {e}", {"selector": selector, "task_id": task_id})


def register_all(registry: ToolRegistry):
    tools = [
        ("browser_set_mode", set_browser_mode,
         "切换浏览器模式: sandbox (Playwright沙箱) 或 real_chrome (真实Chrome, 保留登录态)"),
        ("browser_navigate", browser_navigate, "Navigate browser to a URL."),
        ("browser_click", browser_click, "Click element by CSS selector or ref ID."),
        ("browser_type", browser_type, "Type text into input field by CSS selector or ref ID."),
        ("browser_get_text", browser_get_text, "Get text content of element(s) by CSS selector."),
        ("browser_get_html", browser_get_html, "Get inner HTML of element by CSS selector."),
        ("browser_title", browser_title, "Get current page title and URL."),
        ("browser_get_title", browser_get_title, "Get current page title and URL (alias)."),
        ("browser_screenshot", browser_screenshot, "Take screenshot of current page (base64 PNG)."),
        ("browser_evaluate", browser_evaluate, "Execute JavaScript in the page."),
        ("browser_scroll", browser_scroll, "Scroll page: up/down/left/right."),
        ("browser_get_links", browser_get_links, "Get all links on current page."),
        ("browser_get_visible_text", browser_get_visible_text, "Get all visible text on page."),
        ("browser_close", browser_close, "Close browser session."),
        ("browser_new_tab", browser_new_tab, "Open a new browser tab."),
        ("browser_list_tabs", browser_list_tabs, "List all open browser tabs."),
        ("browser_switch_tab", browser_switch_tab, "Switch to a tab by index."),
        ("browser_snapshot", browser_snapshot, "Get accessibility snapshot with element refs."),
        ("browser_vision", browser_vision, "Take screenshot and return vision analysis envelope."),
        ("browser_wait_for_selector", browser_wait_for_selector, "Wait for an element to appear."),
        ("set_browser_stealth", set_browser_stealth, "Enable/disable anti-detection mode."),
    ]
    for name, handler, desc in tools:
        registry.register(Tool(name=name, handler=handler, description=desc, category="browser"))
    logger.info("[OK] Registered %s Browser tools", len(tools))


# ═══════════════════════════════════════════════════════════
# 遗留 / 内部兼容层
# ═══════════════════════════════════════════════════════════

import json as _json, os, subprocess
from pathlib import Path

# ─── CDP 连接管理 ──────────────────────────────────

_cdp_sessions: Dict[str, Any] = {}
_cdp_lock = threading.Lock()


def set_cdp_endpoint(url: str) -> ToolResult:
    """设置 CDP 端点（用于远程浏览器控制）。"""
    global _CDP_URL
    _CDP_URL = url
    return _ok({"cdp_url": url})


def get_cdp_endpoint() -> Optional[str]:
    return _CDP_URL


def _ensure_page_cdp(url: Optional[str] = None) -> Any:
    """通过 CDP 连接远程浏览器。"""
    global _browser, _page
    cdp_url = url or _CDP_URL
    if not cdp_url:
        return None
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        browser = p.chromium.connect_over_cdp(cdp_url)
        if browser.contexts:
            page = browser.contexts[0].pages[0] if browser.contexts[0].pages else browser.contexts[0].new_page()
        else:
            ctx = browser.new_context()
            page = ctx.new_page()
        _browser = browser
        _page = page
        return page
    except Exception:
        return None


# ─── 浏览器引擎选择 ────────────────────────────────

_BrowserEngine = "playwright"


def set_browser_engine(engine: str) -> ToolResult:
    """切换浏览器引擎: playwright | lightpanda | cdp"""
    global _BrowserEngine
    valid = ["playwright", "lightpanda", "cdp"]
    if engine not in valid:
        return _err(f"不支持引擎: {engine}，可选: {valid}")
    _BrowserEngine = engine
    return _ok({"engine": engine})


def get_browser_engine() -> str:
    return _BrowserEngine


# ─── 对话框策略 ────────────────────────────────────


def set_dialog_policy(policy: str, timeout: float = 5.0) -> ToolResult:
    """设置对话框策略: dismiss=关闭, accept=接受, prompt=询问用户。"""
    global _dialog_policy, _dialog_timeout
    valid = ["dismiss", "accept", "prompt"]
    if policy not in valid:
        return _err(f"策略无效: {policy}")
    _dialog_policy = policy
    _dialog_timeout = timeout
    return _ok({"policy": policy, "timeout": timeout})


def _handle_dialog(dialog) -> None:
    """根据策略处理浏览器对话框。"""
    try:
        if _dialog_policy == "accept":
            dialog.accept()
        elif _dialog_policy == "prompt":
            logger.warning("[WARN] Browser dialog requires user attention: %s", dialog.message)
            dialog.dismiss()
        else:
            dialog.dismiss()
    except Exception:
        pass


# ─── 页面交互增强（旧实现，保留兼容）─────────────────────────────────


def browser_get_viewport(task_id: str = "default", **kw) -> ToolResult:
    """获取当前视口大小。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        vp = page.viewport_size
        return _ok({"width": vp["width"], "height": vp["height"], "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_set_viewport(width: int = 1280, height: int = 720, task_id: str = "default", **kw) -> ToolResult:
    """设置视口大小。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        page.set_viewport_size({"width": width, "height": height})
        return _ok({"width": width, "height": height, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_get_cookies(task_id: str = "default", **kw) -> ToolResult:
    """获取当前页面 cookies。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        ctx = page.context
        cookies = ctx.cookies()
        return _ok({"cookies": cookies, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_clear_cookies(task_id: str = "default", **kw) -> ToolResult:
    """清除浏览器 cookies。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        ctx = page.context
        ctx.clear_cookies()
        return _ok({"cleared": True, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_get_local_storage(task_id: str = "default", **kw) -> ToolResult:
    """获取 localStorage 内容。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        data = page.evaluate("JSON.stringify(window.localStorage)")
        return _ok({"localStorage": json.loads(data), "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


def browser_take_screenshot(full_page: bool = False, task_id: str = "default", **kw) -> ToolResult:
    """截取页面截图（返回 base64）。"""
    try:
        page = _get_page(task_id)
        if not page:
            return _err("[ERROR] Browser session not started", {"task_id": task_id})
        b64 = base64.b64encode(page.screenshot(full_page=full_page)).decode()
        return _ok({"screenshot_base64": b64, "full_page": full_page, "task_id": task_id})
    except Exception as e:
        return _err(str(e), {"task_id": task_id})


# ─── 云浏览器支持 ──────────────────────────────────

_CLOUD_PROVIDER = None


def set_cloud_browser(provider: str, api_key: str = "", **kwargs) -> ToolResult:
    """配置云浏览器提供商: browserbase | ..."""
    global _CLOUD_PROVIDER
    _CLOUD_PROVIDER = {"provider": provider, "api_key": api_key, **kwargs}
    return _ok({"provider": provider})


def _ensure_cloud_browser() -> Optional[Any]:
    """启动云浏览器会话。"""
    if not _CLOUD_PROVIDER:
        return None
    provider = _CLOUD_PROVIDER.get("provider", "")
    if provider == "browserbase":
        try:
            api_key = _CLOUD_PROVIDER.get("api_key", os.environ.get("BROWSERBASE_API_KEY", ""))
            project_id = _CLOUD_PROVIDER.get("project_id", os.environ.get("BROWSERBASE_PROJECT_ID", ""))
            if not api_key:
                return None
            import requests
            r = requests.post(
                "https://connect.browserbase.com/v1/sessions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"project_id": project_id},
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("connectUrl")
        except Exception:
            pass
    return None
