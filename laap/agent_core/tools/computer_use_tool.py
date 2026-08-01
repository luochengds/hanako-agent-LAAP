"""
Computer Use Tool — 屏幕操作(截图/鼠标/键盘/浏览器)
Fixes: full base64 screenshot, proper browser automation via Playwright
"""
from __future__ import annotations

import logging

import time, json, logging, os, io, base64
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.tools.computer")


def _screenshot() -> dict:
    """Capture full screen to base64 PNG. Returns {width, height, data}."""
    try:
        import mss
        from PIL import Image as PILImage
        with mss.mss() as sct:
            mon = sct.monitors[1]
            img = sct.grab(mon)
            pil = PILImage.frombytes("RGB", img.size, img.rgb)
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {"width": img.size[0], "height": img.size[1], "data": b64, "format": "png"}
    except ImportError:
        return {"error": "mss/PIL not installed", "hint": "pip install mss Pillow"}
    except Exception as e:
        return {"error": str(e)}


def mouse_click(x: int, y: int, button: str = "left") -> dict:
    """Click mouse at (x, y)."""
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        return {"success": True, "x": x, "y": y, "button": button}
    except ImportError:
        return {"error": "pyautogui not installed"}
    except Exception as e:
        return {"error": str(e)}


def type_text(text: str) -> dict:
    """Type text via keyboard."""
    try:
        import pyautogui
        pyautogui.write(text, interval=0.05)
        return {"success": True, "chars": len(text)}
    except ImportError:
        return {"error": "pyautogui not installed"}
    except Exception as e:
        return {"error": str(e)}


def scroll(clicks: int = 3) -> dict:
    """Scroll mouse."""
    try:
        import pyautogui
        pyautogui.scroll(clicks)
        return {"success": True, "clicks": clicks}
    except ImportError:
        return {"error": "pyautogui not installed"}
    except Exception as e:
        return {"error": str(e)}


def get_screen_size() -> dict:
    """Get screen resolution."""
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            return {"width": mon["width"], "height": mon["height"]}
    except ImportError:
        return {"width": 1920, "height": 1080}
    except Exception as e:
        return {"error": str(e)}


def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", duration: float = 0.5) -> dict:
    """Drag mouse from (start_x,start_y) to (end_x,end_y)."""
    try:
        import pyautogui
        pyautogui.moveTo(start_x, start_y)
        pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
        return {"success": True, "from": {"x": start_x, "y": start_y}, "to": {"x": end_x, "y": end_y}}
    except ImportError:
        return {"error": "pyautogui not installed"}
    except Exception as e:
        return {"error": str(e)}


def key_press(key: str) -> dict:
    """Press a keyboard key (e.g. 'enter', 'escape', 'ctrl+c')."""
    try:
        import pyautogui
        pyautogui.press(key)
        return {"success": True, "key": key}
    except ImportError:
        return {"error": "pyautogui not installed"}
    except Exception as e:
        return {"error": str(e)}


# ── Playwright Browser (Hermes-style) ──

_browser = None
_page = None


async def _ensure_browser():
    """Lazy-init Playwright browser."""
    global _browser, _page
    if _page is not None:
        return _page
    try:
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        _browser = await p.chromium.launch(headless=True)
        _page = await _browser.new_page()
        await _page.set_viewport_size({"width": 1280, "height": 720})
        logger.info("Playwright browser launched")
        return _page
    except ImportError:
        raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
    except Exception as e:
        raise RuntimeError(f"Browser launch failed: {e}")


async def browser_navigate(url: str) -> dict:
    """Navigate to a URL."""
    try:
        page = await _ensure_browser()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"url": url, "title": await page.title(), "status": "loaded"}
    except Exception as e:
        return {"error": str(e)}


async def browser_snapshot() -> dict:
    """Get page title, URL, and visible text snapshot."""
    try:
        page = await _ensure_browser()
        title = await page.title()
        url = page.url
        text = await page.inner_text("body") if await page.query_selector("body") else ""
        text = text[:3000]
        return {"title": title, "url": url, "text": text, "text_length": len(text)}
    except Exception as e:
        return {"error": str(e)}


async def browser_screenshot() -> dict:
    """Capture browser viewport screenshot as base64."""
    try:
        page = await _ensure_browser()
        buf = await page.screenshot(full_page=False)
        b64 = base64.b64encode(buf).decode()
        return {"data": b64, "format": "png", "width": 1280, "height": 720}
    except Exception as e:
        return {"error": str(e)}


async def browser_click(selector: str) -> dict:
    """Click an element by CSS selector."""
    try:
        page = await _ensure_browser()
        await page.click(selector, timeout=5000)
        return {"selector": selector, "success": True}
    except Exception as e:
        return {"error": str(e)}


async def browser_type(selector: str, text: str) -> dict:
    """Type text into an element."""
    try:
        page = await _ensure_browser()
        await page.fill(selector, text, timeout=5000)
        return {"selector": selector, "chars": len(text), "success": True}
    except Exception as e:
        return {"error": str(e)}


async def browser_scroll(delta_x: int = 0, delta_y: int = 300) -> dict:
    """Scroll the page."""
    try:
        page = await _ensure_browser()
        await page.evaluate(f"window.scrollBy({delta_x}, {delta_y})")
        return {"delta_x": delta_x, "delta_y": delta_y, "success": True}
    except Exception as e:
        return {"error": str(e)}


async def browser_extract_links() -> dict:
    """Extract all links from current page."""
    try:
        page = await _ensure_browser()
        links = await page.evaluate("""() => Array.from(document.querySelectorAll('a[href]')).map(a => ({text: a.innerText.trim(), href: a.href})).filter(x => x.href.startsWith('http')).slice(0, 100)""")
        return {"links": links, "total": len(links)}
    except Exception as e:
        return {"error": str(e)}


async def browser_back() -> dict:
    """Navigate back."""
    try:
        page = await _ensure_browser()
        await page.go_back()
        return {"url": page.url, "title": await page.title()}
    except Exception as e:
        return {"error": str(e)}


async def browser_close():
    """Close browser."""
    global _browser, _page
    try:
        if _page:
            await _page.close()
        if _browser:
            await _browser.close()
    except Exception as e:
        logger.debug(f"操作失败: {e}")
    _browser = None
    _page = None


# ── Tool definitions for the registry ──

TOOL_DEFS = [
    {"name": "screenshot", "fn": lambda: json.dumps(_screenshot()),
     "desc": "Capture full screen as base64 PNG (usable by vision LLMs)", "params": {}, "req": []},
    {"name": "mouse_click", "fn": lambda **kw: json.dumps(mouse_click(int(kw.get("x", 0)), int(kw.get("y", 0)), kw.get("button", "left"))),
     "desc": "Click mouse at coordinates (x, y)", "params": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}}, "req": ["x", "y"]},
    {"name": "type_text", "fn": lambda **kw: json.dumps(type_text(kw.get("text", ""))),
     "desc": "Type text via keyboard", "params": {"text": {"type": "string"}}, "req": ["text"]},
    {"name": "scroll", "fn": lambda **kw: json.dumps(scroll(int(kw.get("clicks", 3)))),
     "desc": "Scroll mouse (positive=down, negative=up)", "params": {"clicks": {"type": "integer"}}},
    {"name": "get_screen_size", "fn": lambda: json.dumps(get_screen_size()),
     "desc": "Get screen resolution", "params": {}},
    {"name": "mouse_drag", "fn": lambda **kw: json.dumps(mouse_drag(int(kw.get("start_x", 0)), int(kw.get("start_y", 0)), int(kw.get("end_x", 0)), int(kw.get("end_y", 0)), kw.get("button", "left"), float(kw.get("duration", 0.5)))),
     "desc": "Drag mouse from one point to another", "params": {"start_x": {"type": "integer"}, "start_y": {"type": "integer"}, "end_x": {"type": "integer"}, "end_y": {"type": "integer"}, "button": {"type": "string"}, "duration": {"type": "number"}}, "req": ["start_x", "start_y", "end_x", "end_y"]},
    {"name": "key_press", "fn": lambda **kw: json.dumps(key_press(kw.get("key", "enter"))),
     "desc": "Press a keyboard key", "params": {"key": {"type": "string"}}, "req": ["key"]},
]
