"""LAAP Domain SDK — Domain SDK Registry.

Manages installed domain SDKs, providing discovery from:
1. Built-in: ``laap/domain_sdks/{domain}/``
2. Installed pip packages: ``laap-domain-{name}``
3. GitHub repositories: ``laap-domain-*``

Mirrors the Skills Hub pattern (laap/skills/hub.py) but for domain SDKs.
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from laap.domain_sdk.base import DomainManifest, DomainSDKBase

logger = logging.getLogger("laap.domain_sdk.registry")


class DomainSDKRegistry:
    """Registry for installed domain SDKs.

    Supports registration, lookup, and discovery of domain SDKs from
    multiple sources. Thread-safe.

    Usage::

        registry = DomainSDKRegistry()
        registry.register(FinQuantDomainSDK())
        sdk = registry.get("finquant")
        manifests = registry.list_manifests()
        registry.discover_builtin()
    """

    def __init__(self) -> None:
        self._sdks: Dict[str, DomainSDKBase] = {}
        self._manifests: Dict[str, DomainManifest] = {}
        self._lock = threading.RLock()

    def register(self, sdk: DomainSDKBase) -> bool:
        """Register a domain SDK instance.

        Args:
            sdk: The DomainSDKBase instance to register.

        Returns:
            True if registered, False if already registered.
        """
        manifest = sdk.manifest()
        with self._lock:
            if manifest.domain_id in self._sdks:
                logger.debug("Domain SDK already registered: %s", manifest.domain_id)
                return False
            self._sdks[manifest.domain_id] = sdk
            self._manifests[manifest.domain_id] = manifest
        logger.info(
            "Registered domain SDK: %s v%s (%s)",
            manifest.domain_id, manifest.version, manifest.domain_name,
        )
        return True

    def unregister(self, domain_id: str) -> bool:
        """Remove a domain SDK from the registry.

        Returns:
            True if found and removed.
        """
        with self._lock:
            if domain_id in self._sdks:
                del self._sdks[domain_id]
                self._manifests.pop(domain_id, None)
                logger.info("Unregistered domain SDK: %s", domain_id)
                return True
            return False

    def get(self, domain_id: str) -> Optional[DomainSDKBase]:
        """Return the SDK for *domain_id*, or None."""
        with self._lock:
            return self._sdks.get(domain_id)

    def get_manifest(self, domain_id: str) -> Optional[DomainManifest]:
        """Return the manifest for *domain_id*, or None."""
        with self._lock:
            return self._manifests.get(domain_id)

    def list_sdks(self) -> List[DomainSDKBase]:
        """Return all registered SDK instances."""
        with self._lock:
            return list(self._sdks.values())

    def list_manifests(self) -> List[DomainManifest]:
        """Return manifests of all registered SDKs."""
        with self._lock:
            return list(self._manifests.values())

    def list_domains(self) -> List[str]:
        """Return sorted list of registered domain IDs."""
        with self._lock:
            return sorted(self._sdks.keys())

    def is_registered(self, domain_id: str) -> bool:
        """Check if a domain SDK is registered."""
        with self._lock:
            return domain_id in self._sdks

    # ── Discovery ──────────────────────────────────────────────────

    def discover_builtin(self) -> List[str]:
        """Discover and load built-in domain SDKs from ``laap.domain_sdks``.

        Scans the ``laap/domain_sdks/`` package for subpackages containing
        an ``sdk.py`` module with a ``DomainSDK`` class.

        Returns:
            List of newly discovered domain IDs.
        """
        discovered: List[str] = []
        try:
            import laap.domain_sdks as domain_sdks_pkg
            pkg_path = getattr(domain_sdks_pkg, "__path__", [])
            if not pkg_path:
                return discovered
        except ImportError:
            logger.debug("laap.domain_sdks package not found")
            return discovered

        import pkgutil
        for importer, modname, ispkg in pkgutil.iter_modules(pkg_path):
            if not ispkg or modname.startswith("_"):
                continue
            domain_id = modname
            if self.is_registered(domain_id):
                continue
            try:
                sdk = _load_sdk_from_module(f"laap.domain_sdks.{modname}.sdk")
                if sdk is not None:
                    self.register(sdk)
                    discovered.append(domain_id)
            except Exception as e:
                logger.warning("Failed to load built-in domain SDK '%s': %s", modname, e)

        if discovered:
            logger.info("Discovered built-in domain SDKs: %s", discovered)
        return discovered

    def discover_pip_packages(self) -> List[str]:
        """Discover domain SDKs from installed pip packages.

        Scans for packages matching ``laap-domain-*`` pattern and loads
        their SDK entry point.

        Returns:
            List of newly discovered domain IDs.
        """
        discovered: List[str] = []
        try:
            from importlib.metadata import distributions
        except ImportError:
            try:
                from importlib_metadata import distributions  # type: ignore
            except ImportError:
                logger.debug("importlib.metadata not available")
                return discovered

        for dist in distributions():
            name = dist.metadata.get("Name", "")
            if not name or not name.lower().startswith("laap-domain-"):
                continue
            domain_id = name.lower().replace("laap-domain-", "").replace("-", "_")
            if self.is_registered(domain_id):
                continue
            try:
                sdk = _load_sdk_from_module(f"laap_domain_{domain_id.replace('_', '-')}.sdk")
                if sdk is not None:
                    self.register(sdk)
                    discovered.append(domain_id)
            except Exception as e:
                logger.warning("Failed to load pip domain SDK '%s': %s", name, e)

        if discovered:
            logger.info("Discovered pip domain SDKs: %s", discovered)
        return discovered

    def discover_all(self) -> List[str]:
        """Discover from all sources (built-in + pip).

        Returns:
            List of all newly discovered domain IDs.
        """
        discovered = self.discover_builtin()
        discovered.extend(self.discover_pip_packages())
        return discovered

    # ── Container protocol ─────────────────────────────────────────

    def __contains__(self, domain_id: object) -> bool:
        if isinstance(domain_id, str):
            return self.is_registered(domain_id)
        return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._sdks)

    def __iter__(self):
        with self._lock:
            return iter(list(self._sdks.values()))

    @property
    def count(self) -> int:
        return len(self)


def _load_sdk_from_module(module_path: str) -> Optional[DomainSDKBase]:
    """Load a DomainSDKBase instance from a module path.

    Looks for a class named ``DomainSDK`` or any subclass of ``DomainSDKBase``
    in the module, instantiates it, and returns the instance.

    Args:
        module_path: Dotted module path (e.g. "laap.domain_sdks.finquant.sdk").

    Returns:
        DomainSDKBase instance, or None if not found.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        logger.debug("Cannot import %s: %s", module_path, e)
        return None

    # Look for explicit DomainSDK class first
    sdk_cls = getattr(module, "DomainSDK", None)
    if sdk_cls is not None and isinstance(sdk_cls, type) and issubclass(sdk_cls, DomainSDKBase):
        return sdk_cls()

    # Fallback: scan module for any DomainSDKBase subclass
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
                logger.warning("Failed to instantiate %s.%s: %s", module_path, attr_name, e)
                continue

    return None
