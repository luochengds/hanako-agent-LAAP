"""
Vision Tool — 图像分析与OCR
Fixes: full base64 data URIs for LLM vision, OCR via pytesseract
"""
from __future__ import annotations

import logging

import json, base64, logging, os, io
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.tools.vision")

try:
    from PIL import Image as PILImage
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def analyze_image(image_path: str, prompt: str = "Describe this image in detail.") -> str:
    """Encode image as base64 data URI for LLM vision consumption."""
    try:
        if not os.path.exists(image_path):
            return json.dumps({"error": f"File not found: {image_path}"})
        ext = os.path.splitext(image_path)[1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        width, height = 0, 0
        if HAVE_PIL:
            try:
                with PILImage.open(image_path) as img:
                    width, height = img.size
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        return json.dumps({
            "image_path": image_path,
            "data_uri": f"data:{mime};base64,{b64}",
            "mime_type": mime,
            "size_bytes": len(b64) * 3 // 4,
            "base64_length": len(b64),
            "width": width,
            "height": height,
            "prompt": prompt,
            "hint": "Pass data_uri to LLM vision for analysis, or use OCR for text extraction",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def analyze_screenshot(screenshot_data: str, prompt: str = "Describe what you see in this screenshot.") -> str:
    """Analyze a base64 screenshot (from computer_use screenshot tool)."""
    try:
        return json.dumps({
            "data_uri": f"data:image/png;base64,{screenshot_data}",
            "base64_length": len(screenshot_data),
            "prompt": prompt,
            "hint": "Pass data_uri to LLM vision for analysis",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ocr_image(image_path: str, lang: str = "eng+chi_sim") -> str:
    """Extract text from image using OCR (tesseract)."""
    try:
        import pytesseract
        if not HAVE_PIL:
            return json.dumps({"error": "Pillow required for OCR"})
        img = PILImage.open(image_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return json.dumps({"text": text.strip(), "length": len(text.strip()),
                           "language": lang, "source": image_path}, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "pytesseract/tesseract not installed",
                          "hint": "pip install pytesseract && install tesseract-ocr"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def image_info(image_path: str) -> str:
    """Get image metadata."""
    try:
        stat = os.stat(image_path)
        info = {"path": image_path, "bytes": stat.st_size, "modified": stat.st_mtime}
        if HAVE_PIL:
            try:
                with PILImage.open(image_path) as img:
                    info["width"] = img.width
                    info["height"] = img.height
                    info["format"] = img.format
                    info["mode"] = img.mode
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOL_DEFS = [
    {"name": "analyze_image",
     "fn": lambda **kw: analyze_image(kw.get("image_path", ""), kw.get("prompt", "Describe this image in detail.")),
     "desc": "Encode image as data URI for LLM vision analysis",
     "params": {"image_path": {"type": "string"}, "prompt": {"type": "string"}}, "req": ["image_path"]},
    {"name": "image_info",
     "fn": lambda **kw: image_info(kw.get("image_path", "")),
     "desc": "Get image metadata (dimensions, format, size)",
     "params": {"image_path": {"type": "string"}}, "req": ["image_path"]},
    {"name": "ocr_image",
     "fn": lambda **kw: ocr_image(kw.get("image_path", ""), kw.get("lang", "eng+chi_sim")),
     "desc": "Extract text from image via OCR (tesseract)",
     "params": {"image_path": {"type": "string"}, "lang": {"type": "string"}}, "req": ["image_path"]},
]
