"""LAAP — Vision tool for image analysis."""

from __future__ import annotations
import base64
import io
import json
import logging
from typing import Optional

from laap.tools.base import ToolResult

logger = logging.getLogger("laap.tools.vision")


def screenshot_analyze(
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
) -> ToolResult:
    """Analyze an image and return its metadata and base64 payload.

    Args:
        image_path: Path to a local image file.
        image_base64: Base64-encoded image data (alternative to image_path).

    Returns:
        ToolResult with image format, size, base64 data, and optional OCR text.
    """
    if not image_path and not image_base64:
        return ToolResult(
            success=False,
            output="",
            error="Either image_path or image_base64 must be provided",
        )

    try:
        pil = None
        try:
            from PIL import Image

            pil = Image
        except ImportError:
            pass

        image_bytes: Optional[bytes] = None
        source = "unknown"

        if image_path and pil is not None:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            source = image_path
        elif image_base64:
            image_bytes = base64.b64decode(image_base64)
            source = "base64"

        if image_bytes is None:
            return ToolResult(
                success=False,
                output="",
                error="PIL is required to load image_path; provide image_base64 instead.",
            )

        encoded = base64.b64encode(image_bytes).decode("utf-8")

        metadata: dict = {"source": source, "base64_length": len(encoded)}
        if pil is not None:
            try:
                img = pil.open(io.BytesIO(image_bytes))
                metadata["format"] = img.format
                metadata["mode"] = img.mode
                metadata["size"] = img.size
            except Exception as img_exc:
                metadata["image_error"] = str(img_exc)

        ocr_text = ""
        if pil is not None and "image_error" not in metadata:
            try:
                import pytesseract

                img = pil.open(io.BytesIO(image_bytes))
                ocr_text = pytesseract.image_to_string(img)
            except Exception:
                pass

        output = json.dumps(
            {
                "format": metadata.get("format"),
                "size": metadata.get("size"),
                "mode": metadata.get("mode"),
                "ocr_text": ocr_text.strip() if ocr_text else "",
            },
            ensure_ascii=False,
        )

        return ToolResult(
            success=True,
            output=output,
            metadata={
                **metadata,
                "ocr_available": bool(ocr_text),
            },
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            output="",
            error=str(exc),
            metadata={"source": image_path or "base64"},
        )
