"""LAAP Domain SDK — Dynamic SDK Loading Utilities.

Provides utilities for loading domain SDKs from various sources at runtime.
Used by ``DomainSDKRegistry`` and the CLI ``laap domain install`` command.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from laap.domain_sdk.base import DomainSDKBase

logger = logging.getLogger("laap.domain_sdk.loader")

# Convention: domain SDK modules expose a `DomainSDK` class
SDK_CLASS_NAME = "DomainSDK"


def load_sdk_from_path(path: str) -> Optional[DomainSDKBase]:
    """Load a domain SDK from a filesystem path.

    Expects *path* to point to a directory containing an ``sdk.py`` file
    with a ``DomainSDK`` class (or any ``DomainSDKBase`` subclass).

    Args:
        path: Path to the domain SDK directory.

    Returns:
        DomainSDKBase instance, or None if loading fails.
    """
    sdk_path = Path(path)
    if not sdk_path.exists():
        logger.error("Domain SDK path does not exist: %s", path)
        return None

    sdk_file = sdk_path / "sdk.py"
    if not sdk_file.exists():
        logger.error("No sdk.py found in: %s", path)
        return None

    # Add parent to sys.path so relative imports work
    parent = str(sdk_path.parent)
    added = False
    if parent not in sys.path:
        sys.path.insert(0, parent)
        added = True

    try:
        module_name = f"laap_domain_{sdk_path.name}"
        spec = importlib.util.spec_from_file_location(module_name, sdk_file)
        if spec is None or spec.loader is None:
            logger.error("Cannot create module spec for %s", sdk_file)
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        return _extract_sdk_from_module(module)
    except Exception as e:
        logger.error("Failed to load domain SDK from %s: %s", path, e)
        return None
    finally:
        if added:
            try:
                sys.path.remove(parent)
            except ValueError:
                pass


def load_sdk_from_module(module_path: str) -> Optional[DomainSDKBase]:
    """Load a domain SDK from a dotted module path.

    Args:
        module_path: Dotted path like "laap.domain_sdks.finquant.sdk".

    Returns:
        DomainSDKBase instance, or None.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        logger.debug("Cannot import %s: %s", module_path, e)
        return None

    return _extract_sdk_from_module(module)


def _extract_sdk_from_module(module) -> Optional[DomainSDKBase]:
    """Extract and instantiate a DomainSDKBase from a loaded module."""
    # Prefer explicit DomainSDK class
    sdk_cls = getattr(module, SDK_CLASS_NAME, None)
    if (
        sdk_cls is not None
        and isinstance(sdk_cls, type)
        and issubclass(sdk_cls, DomainSDKBase)
        and sdk_cls is not DomainSDKBase
    ):
        try:
            return sdk_cls()
        except Exception as e:
            logger.error("Failed to instantiate %s.DomainSDK: %s", module.__name__, e)
            return None

    # Scan for any DomainSDKBase subclass
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if (
            isinstance(obj, type)
            and issubclass(obj, DomainSDKBase)
            and obj is not DomainSDKBase
            and not attr_name.startswith("_")
        ):
            try:
                return obj()
            except Exception as e:
                logger.warning("Failed to instantiate %s.%s: %s", module.__name__, attr_name, e)
                continue

    logger.warning("No DomainSDKBase subclass found in %s", module.__name__)
    return None


def get_sdks_directory() -> Path:
    """Return the path to the built-in domain SDKs directory.

    Returns:
        Path to ``laap/domain_sdks/``.
    """
    return Path(__file__).parent.parent / "domain_sdks"


def list_builtin_sdks() -> list[str]:
    """List domain IDs available in the built-in SDKs directory.

    Returns:
        List of domain IDs (directory names) that contain an sdk.py file.
    """
    sdks_dir = get_sdks_directory()
    if not sdks_dir.exists():
        return []

    result = []
    for entry in sorted(sdks_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if (entry / "sdk.py").exists():
            result.append(entry.name)
    return result
