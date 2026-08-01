"""Health-check helpers for the HarnessX integration."""

from __future__ import annotations

from laap.integrations.harnessx.config import HARNESSX_ROOT, ensure_harnessx_importable


def healthcheck() -> dict:
    """Return the integration health status.

    Returns:
        A dict with keys ``status`` (``"ok"`` or ``"error"``),
        ``harnessx_root``, and ``error`` (``None`` when healthy).
    """
    try:
        ensure_harnessx_importable()
        return {
            "status": "ok",
            "harnessx_root": str(HARNESSX_ROOT),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "harnessx_root": str(HARNESSX_ROOT),
            "error": f"{type(exc).__name__}: {exc}",
        }
