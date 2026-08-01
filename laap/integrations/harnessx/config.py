"""HarnessX discovery and import bootstrapping."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HARNESSX_ROOT = Path(
    os.environ.get("HARNESSX_ROOT", "D:/LAAP/HarnessX-main")
).resolve()


def ensure_harnessx_importable() -> None:
    """Make sure ``D:/LAAP/HarnessX-main`` (or ``HARNESSX_ROOT``) is on ``sys.path``.

    This is a no-op if the path is already present. The function validates that
    ``harnessx`` can be imported afterwards.
    """
    root = str(HARNESSX_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import harnessx  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            f"HarnessX not found at {HARNESSX_ROOT}. "
            "Set the HARNESSX_ROOT environment variable to the correct path."
        ) from exc
