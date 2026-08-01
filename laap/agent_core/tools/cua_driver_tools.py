r"""
LAAP CUA-Driver Tools — 通过 MCP 协议调用 cua-driver 实现计算机自动化

cua-driver 是一个跨平台的计算机使用 MCP 服务器，提供:
- 鼠标操作（点击、拖拽、移动）
- 键盘输入（打字、按键）
- 窗口管理
- 应用程序控制
- 无障碍树获取

在 Windows 上，cua-driver 使用命名管道通信: \\.\pipe\cua-driver
协议格式: {"method":"call","name":"tool_name","args":{}}

使用前请确保 cua-driver 已安装并运行:
  cua-driver serve
或配置自动启动:
  cua-driver autostart enable

工作流:
1. start_session(session_id) — 开始会话
2. launch_app(bundle_id/name) — 启动应用
3. get_window_state(pid, window_id) — 获取窗口状态和元素索引
4. click/type_text/press_key — 使用元素索引进行操作
5. end_session(session_id) — 结束会话
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("agent_core.tools.cua_driver")

_CUA_PIPE_PATH = r"\\.\pipe\cua-driver"


def _ensure_cua_driver() -> bool:
    """确保 cua-driver 服务正在运行。"""
    if sys.platform != "win32":
        return False
    import win32file
    try:
        handle = win32file.CreateFile(
            _CUA_PIPE_PATH,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None
        )
        win32file.CloseHandle(handle)
        return True
    except Exception:
        logger.info("cua-driver not running, starting...")
        try:
            subprocess.Popen(
                ["cua-driver", "serve"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            for _ in range(10):
                time.sleep(0.5)
                try:
                    handle = win32file.CreateFile(
                        _CUA_PIPE_PATH,
                        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0,
                        None,
                        win32file.OPEN_EXISTING,
                        0,
                        None
                    )
                    win32file.CloseHandle(handle)
                    logger.info("cua-driver started successfully")
                    return True
                except Exception:
                    continue
            logger.error("cua-driver failed to start")
            return False
        except Exception as e:
            logger.error(f"Failed to start cua-driver: {e}")
            return False


def _call_mcp(tool_name: str, args: Dict[str, Any] = None) -> Dict[str, Any]:
    """调用 cua-driver MCP API。"""
    try:
        return _call_mcp_pipe(tool_name, args)
    except Exception as e:
        if _ensure_cua_driver():
            try:
                return _call_mcp_pipe(tool_name, args)
            except Exception as e2:
                return {"error": str(e2)}
        return {"error": f"cua-driver service not available: {e}"}


def _call_mcp_pipe(tool_name: str, args: Dict[str, Any] = None) -> Dict[str, Any]:
    """通过 Windows 命名管道调用 MCP API。"""
    import win32file
    import pywintypes
    
    request_data = json.dumps({
        "method": "call",
        "name": tool_name,
        "args": args or {}
    }).encode("utf-8") + b"\n"
    
    handle = None
    try:
        handle = win32file.CreateFile(
            _CUA_PIPE_PATH,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None
        )
        
        win32file.WriteFile(handle, request_data)
        
        response = b""
        while True:
            try:
                result, data = win32file.ReadFile(handle, 8192)
                response += data
                if b"\n" in response:
                    break
            except pywintypes.error as e:
                if e.winerror == 109:
                    break
                raise
        
        if response:
            result = json.loads(response.decode("utf-8").strip())
            if "result" in result:
                return result["result"]
            elif "error" in result:
                return {"error": result["error"]}
            return result
        return {"error": "Empty response"}
    except Exception as e:
        return {"error": f"Pipe error: {str(e)}"}
    finally:
        if handle:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass


def mouse_click(x: int, y: int, pid: Optional[int] = None, button: str = "left", element_index: Optional[int] = None, window_id: Optional[int] = None, session: Optional[str] = None) -> Dict[str, Any]:
    """在指定坐标或元素索引处点击鼠标。"""
    args: Dict[str, Any] = {"x": x, "y": y, "button": button}
    if pid is not None:
        args["pid"] = pid
    if element_index is not None:
        args["element_index"] = element_index
    if window_id is not None:
        args["window_id"] = window_id
    if session:
        args["session"] = session
    return _call_mcp("click", args)


def mouse_double_click(x: int, y: int, pid: Optional[int] = None, button: str = "left", element_index: Optional[int] = None, window_id: Optional[int] = None, session: Optional[str] = None) -> Dict[str, Any]:
    """在指定坐标或元素索引处双击鼠标。"""
    args: Dict[str, Any] = {"x": x, "y": y, "button": button}
    if pid is not None:
        args["pid"] = pid
    if element_index is not None:
        args["element_index"] = element_index
    if window_id is not None:
        args["window_id"] = window_id
    if session:
        args["session"] = session
    return _call_mcp("double_click", args)


def mouse_right_click(x: int, y: int, pid: Optional[int] = None, element_index: Optional[int] = None, window_id: Optional[int] = None, session: Optional[str] = None) -> Dict[str, Any]:
    """在指定坐标或元素索引处右键点击。"""
    args: Dict[str, Any] = {"x": x, "y": y}
    if pid is not None:
        args["pid"] = pid
    if element_index is not None:
        args["element_index"] = element_index
    if window_id is not None:
        args["window_id"] = window_id
    if session:
        args["session"] = session
    return _call_mcp("right_click", args)


def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int, button: str = "left", session: Optional[str] = None) -> Dict[str, Any]:
    """拖拽鼠标从起点到终点。"""
    return _call_mcp("drag", {
        "start_x": start_x, "start_y": start_y,
        "end_x": end_x, "end_y": end_y,
        "button": button,
        "session": session
    })


def move_cursor(x: int, y: int, session: Optional[str] = None) -> Dict[str, Any]:
    """移动鼠标光标到指定位置。"""
    args = {"x": x, "y": y}
    if session:
        args["session"] = session
    return _call_mcp("move_cursor", args)


def get_cursor_position() -> Dict[str, Any]:
    """获取当前鼠标光标位置。"""
    return _call_mcp("get_cursor_position")


def type_text(text: str, pid: Optional[int] = None, element_index: Optional[int] = None, window_id: Optional[int] = None, session: Optional[str] = None) -> Dict[str, Any]:
    """通过键盘输入文本。"""
    args: Dict[str, Any] = {"text": text}
    if pid is not None:
        args["pid"] = pid
    if element_index is not None:
        args["element_index"] = element_index
    if window_id is not None:
        args["window_id"] = window_id
    if session:
        args["session"] = session
    return _call_mcp("type_text", args)


def press_key(key: str, pid: Optional[int] = None, session: Optional[str] = None) -> Dict[str, Any]:
    """按下并释放单个按键。"""
    args: Dict[str, Any] = {"key": key}
    if pid is not None:
        args["pid"] = pid
    if session:
        args["session"] = session
    return _call_mcp("press_key", args)


def hotkey(*keys: str) -> Dict[str, Any]:
    """按下组合键。"""
    return _call_mcp("hotkey", {"keys": list(keys)})


def scroll(direction: str = "down", amount: int = 3, dx: int = 0, dy: int = 0) -> Dict[str, Any]:
    """滚动鼠标滚轮。"""
    if direction == "up":
        dy = -amount * 100
    elif direction == "down":
        dy = amount * 100
    elif direction == "left":
        dx = -amount * 100
    elif direction == "right":
        dx = amount * 100
    return _call_mcp("scroll", {"dx": dx, "dy": dy})


def get_screen_size() -> Dict[str, Any]:
    """获取屏幕分辨率。"""
    return _call_mcp("get_screen_size")


def get_window_state(pid: int, window_id: Optional[int] = None) -> Dict[str, Any]:
    """获取指定进程的窗口状态和无障碍树。"""
    args = {"pid": pid}
    if window_id is not None:
        args["window_id"] = window_id
    return _call_mcp("get_window_state", args)


def list_windows() -> Dict[str, Any]:
    """列出所有打开的窗口。"""
    return _call_mcp("list_windows")


def list_apps() -> Dict[str, Any]:
    """列出已安装的应用程序。"""
    return _call_mcp("list_apps")


def launch_app(bundle_id: Optional[str] = None, name: Optional[str] = None, creates_new_application_instance: bool = False) -> Dict[str, Any]:
    """启动指定应用程序。"""
    args: Dict[str, Any] = {}
    if bundle_id:
        args["bundle_id"] = bundle_id
    elif name:
        args["name"] = name
    if creates_new_application_instance:
        args["creates_new_application_instance"] = True
    return _call_mcp("launch_app", args)


def bring_to_front(window_id: int, session: Optional[str] = None) -> Dict[str, Any]:
    """将指定窗口置于前台。"""
    args = {"window_id": window_id}
    if session:
        args["session"] = session
    return _call_mcp("bring_to_front", args)


def close_window(window_id: int) -> Dict[str, Any]:
    """关闭指定窗口。"""
    return _call_mcp("close_window", {"window_id": window_id})


def kill_app(pid: int) -> Dict[str, Any]:
    """终止指定应用程序。"""
    return _call_mcp("kill_app", {"pid": pid})


def get_accessibility_tree(pid: int, window_id: Optional[int] = None) -> Dict[str, Any]:
    """获取指定窗口的无障碍树。"""
    args = {"pid": pid}
    if window_id is not None:
        args["window_id"] = window_id
    return _call_mcp("get_accessibility_tree", args)


def set_value(selector: str, value: str, session: Optional[str] = None) -> Dict[str, Any]:
    """设置指定元素的值。"""
    args = {"selector": selector, "value": value}
    if session:
        args["session"] = session
    return _call_mcp("set_value", args)


def zoom(factor: float) -> Dict[str, Any]:
    """缩放屏幕。"""
    return _call_mcp("zoom", {"factor": factor})


def check_permissions() -> Dict[str, Any]:
    """检查 cua-driver 权限状态。"""
    return _call_mcp("check_permissions")


def start_session(session_id: str) -> Dict[str, Any]:
    """开始一个会话。"""
    return _call_mcp("start_session", {"session": session_id})


def end_session(session_id: str) -> Dict[str, Any]:
    """结束一个会话。"""
    return _call_mcp("end_session", {"session": session_id})


def get_desktop_state() -> Dict[str, Any]:
    """获取桌面状态（截图+窗口列表）。"""
    return _call_mcp("get_desktop_state")


def get_config() -> Dict[str, Any]:
    """获取 cua-driver 配置。"""
    return _call_mcp("get_config")


def check_for_update() -> Dict[str, Any]:
    """检查 cua-driver 更新。"""
    return _call_mcp("check_for_update")


TOOL_DEFS = [
    {"name": "cua_mouse_click", "fn": lambda **kw: json.dumps(mouse_click(int(kw.get("x", 0)), int(kw.get("y", 0)), kw.get("button", "left"), kw.get("element_index"), kw.get("session"))),
     "desc": "Click mouse at coordinates or element_index via cua-driver", "params": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}, "element_index": {"type": "integer"}, "session": {"type": "string"}}, "req": ["x", "y"]},
    {"name": "cua_mouse_double_click", "fn": lambda **kw: json.dumps(mouse_double_click(int(kw.get("x", 0)), int(kw.get("y", 0)), kw.get("button", "left"), kw.get("element_index"), kw.get("session"))),
     "desc": "Double click mouse at coordinates", "params": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string"}, "element_index": {"type": "integer"}, "session": {"type": "string"}}, "req": ["x", "y"]},
    {"name": "cua_mouse_right_click", "fn": lambda **kw: json.dumps(mouse_right_click(int(kw.get("x", 0)), int(kw.get("y", 0)), kw.get("element_index"), kw.get("session"))),
     "desc": "Right click mouse at coordinates", "params": {"x": {"type": "integer"}, "y": {"type": "integer"}, "element_index": {"type": "integer"}, "session": {"type": "string"}}, "req": ["x", "y"]},
    {"name": "cua_mouse_drag", "fn": lambda **kw: json.dumps(mouse_drag(int(kw.get("start_x", 0)), int(kw.get("start_y", 0)), int(kw.get("end_x", 0)), int(kw.get("end_y", 0)), kw.get("button", "left"), kw.get("session"))),
     "desc": "Drag mouse from start to end coordinates", "params": {"start_x": {"type": "integer"}, "start_y": {"type": "integer"}, "end_x": {"type": "integer"}, "end_y": {"type": "integer"}, "button": {"type": "string"}, "session": {"type": "string"}}, "req": ["start_x", "start_y", "end_x", "end_y"]},
    {"name": "cua_move_cursor", "fn": lambda **kw: json.dumps(move_cursor(int(kw.get("x", 0)), int(kw.get("y", 0)), kw.get("session"))),
     "desc": "Move mouse cursor to coordinates", "params": {"x": {"type": "integer"}, "y": {"type": "integer"}, "session": {"type": "string"}}, "req": ["x", "y"]},
    {"name": "cua_get_cursor_position", "fn": lambda: json.dumps(get_cursor_position()),
     "desc": "Get current mouse cursor position", "params": {}, "req": []},
    {"name": "cua_type_text", "fn": lambda **kw: json.dumps(type_text(kw.get("text", ""), kw.get("element_index"), kw.get("session"))),
     "desc": "Type text via keyboard", "params": {"text": {"type": "string"}, "element_index": {"type": "integer"}, "session": {"type": "string"}}, "req": ["text"]},
    {"name": "cua_press_key", "fn": lambda **kw: json.dumps(press_key(kw.get("key", "enter"), kw.get("session"))),
     "desc": "Press and release a single key", "params": {"key": {"type": "string"}, "session": {"type": "string"}}, "req": ["key"]},
    {"name": "cua_hotkey", "fn": lambda **kw: json.dumps(hotkey(*kw.get("keys", []))),
     "desc": "Press a combination of keys", "params": {"keys": {"type": "array", "items": {"type": "string"}}}, "req": ["keys"]},
    {"name": "cua_scroll", "fn": lambda **kw: json.dumps(scroll(kw.get("direction", "down"), int(kw.get("amount", 3)))),
     "desc": "Scroll mouse wheel", "params": {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "amount": {"type": "integer"}}},
    {"name": "cua_get_screen_size", "fn": lambda: json.dumps(get_screen_size()),
     "desc": "Get screen resolution", "params": {}, "req": []},
    {"name": "cua_get_window_state", "fn": lambda **kw: json.dumps(get_window_state(int(kw.get("pid", 0)), kw.get("window_id"))),
     "desc": "Get window state and accessibility tree for a process", "params": {"pid": {"type": "integer"}, "window_id": {"type": "integer"}}, "req": ["pid"]},
    {"name": "cua_list_windows", "fn": lambda: json.dumps(list_windows()),
     "desc": "List all open windows", "params": {}, "req": []},
    {"name": "cua_list_apps", "fn": lambda: json.dumps(list_apps()),
     "desc": "List installed applications", "params": {}, "req": []},
    {"name": "cua_launch_app", "fn": lambda **kw: json.dumps(launch_app(kw.get("bundle_id"), kw.get("name"), bool(kw.get("creates_new_application_instance", False)))),
     "desc": "Launch an application by bundle_id or name", "params": {"bundle_id": {"type": "string"}, "name": {"type": "string"}, "creates_new_application_instance": {"type": "boolean"}}},
    {"name": "cua_bring_to_front", "fn": lambda **kw: json.dumps(bring_to_front(int(kw.get("window_id", 0)), kw.get("session"))),
     "desc": "Bring window to front", "params": {"window_id": {"type": "integer"}, "session": {"type": "string"}}, "req": ["window_id"]},
    {"name": "cua_close_window", "fn": lambda **kw: json.dumps(close_window(int(kw.get("window_id", 0)))),
     "desc": "Close a window", "params": {"window_id": {"type": "integer"}}, "req": ["window_id"]},
    {"name": "cua_kill_app", "fn": lambda **kw: json.dumps(kill_app(int(kw.get("pid", 0)))),
     "desc": "Kill an application process", "params": {"pid": {"type": "integer"}}, "req": ["pid"]},
    {"name": "cua_get_accessibility_tree", "fn": lambda **kw: json.dumps(get_accessibility_tree(int(kw.get("pid", 0)), kw.get("window_id"))),
     "desc": "Get accessibility tree of a window", "params": {"pid": {"type": "integer"}, "window_id": {"type": "integer"}}, "req": ["pid"]},
    {"name": "cua_set_value", "fn": lambda **kw: json.dumps(set_value(kw.get("selector", ""), kw.get("value", ""), kw.get("session"))),
     "desc": "Set value of an element", "params": {"selector": {"type": "string"}, "value": {"type": "string"}, "session": {"type": "string"}}, "req": ["selector", "value"]},
    {"name": "cua_zoom", "fn": lambda **kw: json.dumps(zoom(float(kw.get("factor", 1.0)))),
     "desc": "Zoom screen by factor", "params": {"factor": {"type": "number"}}},
    {"name": "cua_check_permissions", "fn": lambda: json.dumps(check_permissions()),
     "desc": "Check cua-driver permission status", "params": {}, "req": []},
    {"name": "cua_start_session", "fn": lambda **kw: json.dumps(start_session(kw.get("session_id", ""))),
     "desc": "Start a new cua-driver session", "params": {"session_id": {"type": "string"}}, "req": ["session_id"]},
    {"name": "cua_end_session", "fn": lambda **kw: json.dumps(end_session(kw.get("session_id", ""))),
     "desc": "End a cua-driver session", "params": {"session_id": {"type": "string"}}, "req": ["session_id"]},
    {"name": "cua_get_desktop_state", "fn": lambda: json.dumps(get_desktop_state()),
     "desc": "Get desktop state with screenshot and window list", "params": {}, "req": []},
    {"name": "cua_get_config", "fn": lambda: json.dumps(get_config()),
     "desc": "Get cua-driver configuration", "params": {}, "req": []},
    {"name": "cua_check_for_update", "fn": lambda: json.dumps(check_for_update()),
     "desc": "Check for cua-driver updates", "params": {}, "req": []},
]