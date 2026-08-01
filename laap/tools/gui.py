
"""
LAAP — GUI Control Tools
Mouse movement/click, keyboard input, screenshot, window management.
Uses pyautogui + mss for cross-platform support.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
import logging, os, base64, io, json, time

from laap.tools.base import Tool
from laap.tools.tool_registry import ToolRegistry

logger = logging.getLogger("laap.tools.gui")

def _ensure_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        return pyautogui
    except ImportError:
        raise ImportError("pyautogui not installed. Run: pip install pyautogui")

def _ensure_mss():
    try:
        import mss
        return mss
    except ImportError:
        return None

def _ensure_pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

def gui_mouse_position(**kw) -> str:
    """Get current mouse cursor position (x, y)."""
    pg = _ensure_pyautogui()
    x, y = pg.position()
    return json.dumps({"x": x, "y": y, "success": True})

def gui_mouse_move(x: int = 0, y: int = 0, duration: float = 0.2, **kw) -> str:
    """Move mouse to absolute coordinates (x, y) on screen."""
    pg = _ensure_pyautogui()
    pg.moveTo(x, y, duration=duration)
    return json.dumps({"action": "move", "x": x, "y": y, "success": True})

def gui_mouse_click(x: Optional[int] = None, y: Optional[int] = None,
                     button: str = "left", clicks: int = 1, **kw) -> str:
    """Click mouse at (x, y) or current position. button: left/right/middle."""
    pg = _ensure_pyautogui()
    if x is not None and y is not None:
        pg.click(x, y, button=button, clicks=clicks)
    else:
        pg.click(button=button, clicks=clicks)
    return json.dumps({"action": "click", "button": button, "clicks": clicks, "success": True})

def gui_mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int,
                    button: str = "left", duration: float = 0.5, **kw) -> str:
    """Drag mouse from (start_x, start_y) to (end_x, end_y)."""
    pg = _ensure_pyautogui()
    pg.moveTo(start_x, start_y)
    pg.drag(end_x - start_x, end_y - start_y, button=button, duration=duration)
    return json.dumps({"action": "drag", "from": [start_x, start_y],
                       "to": [end_x, end_y], "success": True})

def gui_scroll(clicks: int = 1, x: Optional[int] = None, y: Optional[int] = None, **kw) -> str:
    """Scroll mouse wheel. Positive=up, negative=down."""
    pg = _ensure_pyautogui()
    if x is not None and y is not None:
        pg.moveTo(x, y)
    pg.scroll(clicks)
    return json.dumps({"action": "scroll", "clicks": clicks, "success": True})

def gui_type_text(text: str = "", interval: float = 0.02, **kw) -> str:
    """Type text at current cursor position. Use {{key}} for special keys: {{enter}}, {{tab}}, {{ctrl+c}}."""
    pg = _ensure_pyautogui()
    import re
    parts = re.split(r'\{\{(\w+)\}\}', text)
    for part in parts:
        if not part:
            continue
        if part in ('enter','tab','escape','backspace','space','delete',
                     'up','down','left','right','home','end','pageup','pagedown',
                     'f1','f2','f3','f4','f5','f6','f7','f8','f9','f10','f11','f12'):
            pg.press(part)
        elif part.startswith('ctrl+') or part.startswith('alt+') or part.startswith('shift+'):
            mod, key = part.split('+', 1)
            pg.hotkey(mod, key)
        else:
            pg.typewrite(part, interval=interval)
    return json.dumps({"action": "type", "chars": len(text), "success": True})

def gui_key_press(key: str = "", **kw) -> str:
    """Press a single keyboard key."""
    pg = _ensure_pyautogui()
    pg.press(key.lower())
    return json.dumps({"action": "key_press", "key": key, "success": True})

def gui_hotkey(keys: str = "", **kw) -> str:
    """Press a keyboard shortcut: 'ctrl+c', 'alt+tab'."""
    pg = _ensure_pyautogui()
    key_list = [k.strip().lower() for k in keys.split('+')]
    pg.hotkey(*key_list)
    return json.dumps({"action": "hotkey", "keys": keys, "success": True})

def gui_screenshot(region: Optional[str] = None, **kw) -> str:
    """Take a screenshot and return base64 PNG. region: 'x,y,w,h' to capture area."""
    mss_lib = _ensure_mss()
    Image = _ensure_pil()
    if mss_lib:
        with mss_lib.mss() as sct:
            if region:
                parts = [int(p.strip()) for p in region.split(',')]
                monitor = {"left": parts[0], "top": parts[1], "width": parts[2], "height": parts[3]} if len(parts)==4 else sct.monitors[1]
            else:
                monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
    else:
        pg = _ensure_pyautogui()
        img = pg.screenshot(region=tuple([int(p.strip()) for p in region.split(',')]) if region else None)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return json.dumps({"success": True, "format": "png", "size": img.size, "mode": img.mode, "data_base64": b64, "data_len": len(b64)})

def gui_get_screen_size(**kw) -> str:
    """Get screen resolution."""
    pg = _ensure_pyautogui()
    w, h = pg.size()
    return json.dumps({"width": w, "height": h, "success": True})

def gui_get_active_window(**kw) -> str:
    """Get active window title and position."""
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win:
            return json.dumps({"title": win.title, "left": win.left, "top": win.top,
                               "width": win.width, "height": win.height, "success": True})
        return json.dumps({"success": False, "error": "No active window"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

def register_all(registry: ToolRegistry):
    tools = [
        ("gui_mouse_position", gui_mouse_position, "Get current mouse cursor position (x, y)."),
        ("gui_mouse_move", gui_mouse_move, "Move mouse to absolute (x, y) screen coordinates."),
        ("gui_mouse_click", gui_mouse_click, "Click at (x,y) or current position. button: left/right/middle. clicks: 1 or 2."),
        ("gui_mouse_drag", gui_mouse_drag, "Drag mouse from (start_x,start_y) to (end_x,end_y)."),
        ("gui_scroll", gui_scroll, "Scroll mouse wheel. Positive=up, negative=down."),
        ("gui_type_text", gui_type_text, "Type text. Use {{key}} for special keys: {{enter}}, {{tab}}, {{ctrl+c}}."),
        ("gui_key_press", gui_key_press, "Press a keyboard key: enter, tab, escape, f5, etc."),
        ("gui_hotkey", gui_hotkey, "Press keyboard shortcut: 'ctrl+c', 'alt+tab'."),
        ("gui_screenshot", gui_screenshot, "Take screenshot. Returns base64 PNG. Optional region: 'x,y,w,h'."),
        ("gui_screen_size", gui_get_screen_size, "Get screen resolution."),
        ("gui_active_window", gui_get_active_window, "Get active window info."),
    ]
    for name, handler, desc in tools:
        registry.register(Tool(name=name, handler=handler, description=desc, category="gui"))
    logger.info(f"Registered {len(tools)} GUI tools")
