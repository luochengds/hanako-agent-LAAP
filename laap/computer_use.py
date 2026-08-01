#!/usr/bin/env python3
"""
阿瑞斯 Computer Use —— Windows 版
====================================
用屏幕截图 + 鼠标键盘控制 实现完整的计算机使用能力

能力：
  - screenshot()  → 截屏保存
  - click(x,y)    → 点击
  - type(text)    → 打字
  - scroll(dy)    → 滚动
  - locate(text)  → 屏幕文字查找（需要 OCR 或 VLM）

需要视觉 API key 才能真正"看懂"画面
"""

import logging
logger = logging.getLogger(__name__)

import os
import sys
import time
import base64
from datetime import datetime
from pathlib import Path

# ── 依赖 ────────────────────────────────────────────────────────────
CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


def check_deps() -> dict:
    """检查所有依赖是否可用"""
    deps = {}
    try:
        import mss
        deps["mss"] = True
    except:
        deps["mss"] = False
    try:
        import pyautogui
        deps["pyautogui"] = True
    except:
        deps["pyautogui"] = False
    try:
        import pygetwindow as gw
        deps["pygetwindow"] = True
    except:
        deps["pygetwindow"] = False
    try:
        import cv2
        deps["opencv"] = True
    except:
        deps["opencv"] = False
    try:
        import numpy as np
        deps["numpy"] = True
    except:
        deps["numpy"] = False
    return deps


def screenshot(name: str = None) -> str:
    """
    截屏并保存
    返回：图片路径
    """
    import mss
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = name or f"screen_{ts}"
    path = str(CAPTURES_DIR / f"{filename}.png")

    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 主显示器
        sct.shot(mon=-1, output=path)

    size = os.path.getsize(path)
    logger.info(f"📸 截图已保存: {path} ({size//1024} KB)")
    logger.info(f"   分辨率: {monitor['width']}x{monitor['height']}")
    return path


def screenshot_b64() -> str:
    """截屏并返回 base64（用于 VLM API）"""
    path = screenshot("vlm_input")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return b64


def click(x: int, y: int, button: str = "left", clicks: int = 1):
    """点击屏幕上的位置"""
    import pyautogui
    pyautogui.click(x, y, button=button, clicks=clicks)
    logger.info(f"🖱️ 点击 ({x}, {y})")
def right_click(x: int, y: int):
    """右键点击"""
    click(x, y, button="right")


def double_click(x: int, y: int):
    """双击"""
    click(x, y, clicks=2)


def move_to(x: int, y: int):
    """移动鼠标到位置"""
    import pyautogui
    pyautogui.moveTo(x, y)
    logger.info(f"🖱️ 移动到 ({x}, {y})")
def type_text(text: str, interval: float = 0.05):
    """打字"""
    import pyautogui
    pyautogui.write(text, interval=interval)
    logger.info(f"⌨️ 输入: {text[:50]}{'...' if len(text)>50 else ''}")
def press(key: str):
    """按键盘键"""
    import pyautogui
    pyautogui.press(key)
    logger.info(f"⌨️ 按键: {key}")
def hotkey(*keys: str):
    """组合键"""
    import pyautogui
    pyautogui.hotkey(*keys)
    logger.info(f"⌨️ 组合键: {'+'.join(keys)}")
def scroll(clicks: int):
    """滚动"""
    import pyautogui
    pyautogui.scroll(clicks)
    logger.info(f"🖱️ 滚动: {clicks}")
def get_mouse_pos() -> tuple:
    """获取鼠标位置"""
    import pyautogui
    x, y = pyautogui.position()
    return x, y


def get_window(name: str):
    """按标题查找窗口"""
    import pygetwindow as gw
    try:
        windows = gw.getWindowsWithTitle(name)
        if windows:
            win = windows[0]
            logger.info(f"🪟 找到窗口: {win.title}")
            logger.info(f"   位置: ({win.left}, {win.top}), 大小: {win.width}x{win.height}")
            return win
    except Exception as e:
        logger.debug(f"操作失败: {e}")
    return None


def focus_window(name: str) -> bool:
    """激活窗口"""
    win = get_window(name)
    if win:
        try:
            win.activate()
            return True
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    return False


def list_windows():
    """列出所有窗口"""
    import pygetwindow as gw
    wins = gw.getAllWindows()
    visible = [w for w in wins if w.visible and w.title.strip()]
    logger.info(f"🪟 可见窗口 ({len(visible)}):")
    for w in visible[:20]:
        logger.info(f"   - {w.title[:60]}")
    return visible


def describe_screen() -> str:
    """
    描述屏幕内容（需要 VLM API）
    当前：返回基础信息
    """
    import mss
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        info = f"屏幕 {monitor['width']}x{monitor['height']}"
    logger.info(f"👁️ {info}")
    logger.info("   需要 VLM API key 才能描述画面内容")
    return info


# ── 状态 ────────────────────────────────────────────────────────────
def status() -> dict:
    d = check_deps()
    return {
        "截图": d["mss"],
        "鼠标控制": d["pyautogui"],
        "窗口管理": d["pygetwindow"],
        "图像处理": d["opencv"],
        "视觉分析": "需要 Gemini API key → aistudio.google.com/apikey",
    }


# ── 命令行 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "screenshot" or cmd == "shot":
        screenshot()
    elif cmd == "status":
        s = status()
        logger.info("🖥️ 阿瑞斯 Computer Use")
        for k, v in s.items():
            logger.info(f"  {k}: {'✅' if v is True else '❌' if v is False else v}")
    elif cmd == "windows":
        list_windows()
    elif cmd == "click":
        click(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "type":
        type_text(" ".join(sys.argv[2:]))
    elif cmd == "mouse":
        x, y = get_mouse_pos()
        logger.info(f"🖱️ 鼠标位置: ({x}, {y})")
    elif cmd == "focus":
        focus_window(" ".join(sys.argv[2:]))
    else:
        logger.info("🖥️ 阿瑞斯 Computer Use")
        logger.info("   screenshot  → 截屏")
        logger.info("   status      → 状态")
        logger.info("   windows     → 窗口列表")
        logger.info("   click x y   → 点击")
        logger.info("   type text   → 打字")
        logger.info("   mouse       → 鼠标位置")
        logger.info('   focus name  → 激活窗口')