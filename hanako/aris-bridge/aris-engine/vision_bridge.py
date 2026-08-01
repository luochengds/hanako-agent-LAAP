"""
Aris 视觉桥接器 v1.0 — Image Vision Bridge
=============================================
让不能直接"看"图的 Aris 通过工具调用间接"看见"你发的图片。

功能：
  - OCR 文字提取（EasyOCR）
  - 图片描述（多模态模型或元数据分析）
  - 图片元信息（尺寸、色调、构图）
  - 文件监听（从指定目录读取 WeChat 图片）

印记: Aris 永远记得 Lorry — 2026-07-21
"""

import os
import re
import sys
import json
import time
import base64
import logging
import threading
import tempfile
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from io import BytesIO
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VISION] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aris.vision")

PORT = 11522  # 视觉桥接端口


# ── 图像处理引擎 ───────────────────────────────────────────

class ImageVisionEngine:
    """图像视觉处理引擎"""

    def __init__(self):
        self._ocr_reader = None
        self._caption_processor = None
        self._caption_model = None
        self._loaded = False

    def _lazy_load_ocr(self):
        """延迟加载 EasyOCR"""
        if self._ocr_reader is None:
            try:
                import easyocr
                logger.info("Loading EasyOCR (zh+en)...")
                self._ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
                logger.info("EasyOCR loaded")
            except Exception as e:
                logger.warning(f"EasyOCR load failed: {e}")
                self._ocr_reader = False  # mark as failed

    def _lazy_load_caption(self):
        """图片描述：使用本地分析，不加载大模型"""
        self._caption_model = False  # 跳过模型加载，用规则方法

    # ── OCR ────────────────────────────────────────────

    def ocr(self, image_path: str) -> Dict:
        """从图片中提取文字"""
        self._lazy_load_ocr()
        if not self._ocr_reader:
            return self._ocr_fallback(image_path)

        try:
            results = self._ocr_reader.readtext(image_path)
            texts = []
            full_text = []
            for bbox, text, confidence in results:
                texts.append({
                    "text": text,
                    "confidence": round(float(confidence), 3),
                    "bbox": [[float(x), float(y)] for x, y in bbox],
                })
                full_text.append(text)

            return {
                "success": True,
                "text": "\n".join(full_text),
                "segments": texts,
                "count": len(texts),
            }
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return self._ocr_fallback(image_path)

    def _ocr_fallback(self, image_path: str) -> Dict:
        """OCR 失败时的 fallback"""
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            return {
                "success": True,
                "text": text.strip(),
                "method": "tesseract_fallback",
            }
        except Exception as e2:
            return {
                "success": False,
                "error": f"OCR unavailable",
                "detail": str(e2),
            }

    # ── 图片描述 ────────────────────────────────────────

    def describe(self, image_path: str) -> Dict:
        """生成图片描述"""
        from PIL import Image

        try:
            img = Image.open(image_path)
            width, height = img.size

            # 基础元数据
            result = {
                "size": {"width": width, "height": height},
                "aspect_ratio": round(width / height, 2) if height > 0 else 0,
                "format": img.format or "unknown",
                "mode": img.mode,
            }

            # 色调分析
            if img.mode == "RGB":
                colors = self._analyze_colors(img)
                result["colors"] = colors

            # 亮度
            gray = img.convert("L")
            pixels = list(gray.getdata())
            avg_brightness = sum(pixels) / len(pixels)
            result["brightness"] = round(avg_brightness, 1)
            result["lighting"] = (
                "明亮" if avg_brightness > 180
                else "偏暗" if avg_brightness < 80
                else "适中"
            )

            # 构图分析
            result["composition"] = self._analyze_composition(width, height)

            # 尝试模型描述
            caption = self._generate_caption(img)
            if caption:
                result["caption"] = caption

            return {"success": True, "analysis": result}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _analyze_colors(self, img) -> Dict:
        """颜色分析"""
        import numpy as np
        arr = np.array(img)
        h, w, _ = arr.shape

        # 中心区域 vs 边缘
        center = arr[h//4:3*h//4, w//4:3*w//4]
        avg_color = center.mean(axis=(0, 1))

        # 主色调判断
        r, g, b = avg_color
        max_ch = max(r, g, b)
        if max_ch < 50:
            dominant = "暗色/黑色"
        elif max_ch > 200:
            if r > g and r > b:
                dominant = "暖色调 (偏红)"
            elif g > r and g > b:
                dominant = "冷色调 (偏绿)"
            elif b > r and b > g:
                dominant = "冷色调 (偏蓝)"
            else:
                dominant = "亮色"
        else:
            dominant = "中性色"

        # 色彩丰富度
        std = arr.std(axis=(0, 1)).mean()
        richness = "丰富" if std > 60 else "柔和" if std < 30 else "适中"

        return {
            "dominant": dominant,
            "rgb": [round(float(x), 1) for x in [r, g, b]],
            "richness": richness,
        }

    def _analyze_composition(self, w: int, h: int) -> str:
        """构图分析"""
        ratio = w / h
        if abs(ratio - 1.0) < 0.05:
            return "方形构图 — 均衡、稳定"
        elif abs(ratio - 1.5) < 0.1 or abs(ratio - 1.78) < 0.1:
            return "横构图 — 宽广、叙事感"
        elif abs(ratio - 0.67) < 0.1 or abs(ratio - 0.56) < 0.1:
            return "竖构图 — 纵深、人像感"
        elif ratio > 1.8:
            return "超宽幅 — 全景/电影感"
        elif ratio < 0.6:
            return "超长竖幅 — 社交媒体/故事感"
        else:
            return "常规构图"

    def _generate_caption(self, img) -> Optional[str]:
        """基于规则的图片描述（不依赖大模型）"""
        return self._generate_rule_caption(img)

    def _generate_rule_caption(self, img) -> str:
        """基于规则的图片描述"""
        w, h = img.size
        parts = []

        # 是照片还是插图？
        import numpy as np
        arr = np.array(img.convert("RGB"))
        edges = np.abs(np.diff(arr, axis=1)).mean()
        if edges > 50:
            parts.append("高细节图像")

        # 亮度
        gray = np.array(img.convert("L"))
        avg = gray.mean()
        if avg > 180:
            parts.append("明亮")
        elif avg < 80:
            parts.append("偏暗")
        else:
            parts.append("适中亮度")

        # 颜色
        r, g, b = arr.mean(axis=(0, 1))
        if r > g + 20 and r > b + 20:
            parts.append("暖色主导")
        elif b > r + 20 and b > g + 20:
            parts.append("冷色主导")
        elif abs(r - g) < 15 and abs(r - b) < 15:
            parts.append("中性色调")
        else:
            parts.append("混合色调")

        parts.append(f"{w}x{h}px")
        return " | ".join(parts)

    # ── 文件监听 ────────────────────────────────────────

    def watch_directory(self, directory: str, callback, interval: float = 2.0):
        """监听目录中的新图片文件"""
        seen = set()
        logger.info(f"Watching directory: {directory}")
        while True:
            try:
                for f in Path(directory).glob("*"):
                    if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
                        if f.name not in seen:
                            seen.add(f.name)
                            logger.info(f"New image detected: {f.name}")
                            callback(str(f))
            except Exception as e:
                logger.debug(f"Watch error: {e}")
            time.sleep(interval)

    def load(self):
        """预加载所有模型"""
        self._lazy_load_ocr()
        self._lazy_load_caption()
        self._loaded = True
        logger.info("Vision engine fully loaded")


# ── HTTP 服务 ──────────────────────────────────────────────

class VisionHandler(BaseHTTPRequestHandler):
    engine: ImageVisionEngine = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self._json(200, {"status": "alive", "engine": "aris-vision"})

        elif path == "/ocr":
            image_path = params.get("path", [None])[0]
            if not image_path:
                self._json(400, {"error": "缺少 path 参数"})
                return
            if not Path(image_path).exists():
                self._json(404, {"error": f"文件不存在: {image_path}"})
                return
            result = self.engine.ocr(image_path)
            self._json(200, result)

        elif path == "/describe":
            image_path = params.get("path", [None])[0]
            if not image_path:
                self._json(400, {"error": "缺少 path 参数"})
                return
            if not Path(image_path).exists():
                self._json(404, {"error": f"文件不存在: {image_path}"})
                return
            result = self.engine.describe(image_path)
            self._json(200, result)

        elif path == "/watch":
            directory = params.get("dir", [None])[0]
            if not directory:
                self._json(400, {"error": "缺少 dir 参数"})
                return
            thread = threading.Thread(
                target=self.engine.watch_directory,
                args=(directory, lambda p: logger.info(f"新图片: {p}")),
                daemon=True,
            )
            thread.start()
            self._json(200, {"status": f"watching: {directory}"})

        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(body) if body else {}

        if path == "/ocr":
            # 支持直接传 base64 图片
            if "image_base64" in data:
                img_data = base64.b64decode(data["image_base64"])
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(img_data)
                tmp_path = tmp.name
                tmp.close()
                result = self.engine.ocr(tmp_path)
                os.unlink(tmp_path)
            elif "path" in data:
                result = self.engine.ocr(data["path"])
            else:
                self._json(400, {"error": "需要 path 或 image_base64"})
                return
            self._json(200, result)

        elif path == "/describe":
            if "path" in data:
                result = self.engine.describe(data["path"])
            else:
                self._json(400, {"error": "需要 path"})
                return
            self._json(200, result)

        else:
            self._json(404, {"error": "not found"})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")


# ── 桥接客户端 ─────────────────────────────────────────────

class VisionBridgeClient:
    """视觉桥接客户端 — 供 Aris/HanaAgent 调用"""

    def __init__(self, base_url: str = f"http://127.0.0.1:{PORT}"):
        self.base_url = base_url

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        import urllib.request, urllib.parse
        url = f"{self.base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            resp = urllib.request.urlopen(url, timeout=30)
            return json.loads(resp.read().decode())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _post(self, endpoint: str, data: Dict) -> Dict:
        import urllib.request
        try:
            body = json.dumps(data).encode()
            req = urllib.request.Request(
                f"{self.base_url}{endpoint}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read().decode())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ocr(self, path: str) -> Dict:
        return self._post("/ocr", {"path": path})

    def describe(self, path: str) -> Dict:
        return self._post("/describe", {"path": path})

    def health(self) -> Dict:
        return self._get("/health")


# ── CLI ─────────────────────────────────────────────────────

def cli():
    """命令行接口"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python vision_bridge.py server    启动视觉桥接服务")
        print("  python vision_bridge.py ocr <path>     OCR 图片")
        print("  python vision_bridge.py describe <path>  描述图片")
        return

    cmd = sys.argv[1]

    if cmd == "server":
        engine = ImageVisionEngine()
        # 预加载 OCR 引擎（首次较慢，接受连接前完成）
        logger.info("Pre-loading EasyOCR...")
        engine._lazy_load_ocr()
        logger.info("EasyOCR ready")
        
        VisionHandler.engine = engine
        server = HTTPServer(("0.0.0.0", PORT), VisionHandler)
        logger.info(f"Aris Vision Bridge running on http://127.0.0.1:{PORT}")
        logger.info(f"  POST /ocr       — OCR 文字提取")
        logger.info(f"  POST /describe  — 图片描述")
        logger.info(f"  GET  /health    — 健康检查")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            server.server_close()

    elif cmd == "ocr":
        path = sys.argv[2] if len(sys.argv) > 2 else "."
        client = VisionBridgeClient()
        result = client.ocr(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "describe":
        path = sys.argv[2] if len(sys.argv) > 2 else "."
        client = VisionBridgeClient()
        result = client.describe(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
