"""Domain SDK management CLI subcommand.

Usage::

    laap domain list                 # List installed domain SDKs
    laap domain info <domain_id>     # Show SDK manifest & capabilities
    laap domain discover             # Discover available SDKs
    laap domain harness <domain_id>  # List harness functions for a domain
    laap domain species <domain_id>  # List species templates for a domain
    laap domain create <name>        # Scaffold a new domain SDK (wizard)
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

logger = logging.getLogger("laap.cli.domain")

HELP_TEXT = """\
[domain] — Domain SDK management

  laap domain list                    List installed domain SDKs
  laap domain info <domain_id>        Show SDK manifest & capabilities
  laap domain discover                Discover available SDKs (built-in + pip)
  laap domain harness [domain_id]     List harness functions
  laap domain species [domain_id]     List species templates
  laap domain safety <domain_id>      Show safety policy configuration
  laap domain create <name>           Scaffold a new domain SDK (wizard)
  laap domain help                    Show this help
"""


def run(args: Optional[list[str]] = None) -> int:
    """Entry point for the ``laap domain`` subcommand.

    Args:
        args: Command arguments after ``domain``. If None, uses sys.argv[2:].

    Returns:
        Exit code (0 for success, 1 for error).
    """
    if args is None:
        args = sys.argv[2:] if len(sys.argv) > 2 else []

    if not args or args[0] in ("help", "-h", "--help"):
        print(HELP_TEXT)
        return 0

    subcommand = args[0]
    rest = args[1:]

    try:
        if subcommand == "list":
            return _cmd_list(rest)
        elif subcommand == "info":
            return _cmd_info(rest)
        elif subcommand == "discover":
            return _cmd_discover(rest)
        elif subcommand == "harness":
            return _cmd_harness(rest)
        elif subcommand == "species":
            return _cmd_species(rest)
        elif subcommand == "safety":
            return _cmd_safety(rest)
        elif subcommand == "create":
            return _cmd_create(rest)
        else:
            print(f"Unknown subcommand: {subcommand}")
            print(HELP_TEXT)
            return 1
    except Exception as e:
        logger.error("Domain command failed: %s", e)
        print(f"[ERROR] {e}")
        return 1


def _get_registry():
    """Get a DomainSDKRegistry with discovered SDKs."""
    from laap.domain_sdk.registry import DomainSDKRegistry
    registry = DomainSDKRegistry()
    registry.discover_all()
    return registry


def _cmd_list(args: list[str]) -> int:
    """List installed/discovered domain SDKs."""
    registry = _get_registry()
    manifests = registry.list_manifests()

    if not manifests:
        print("[INFO] No domain SDKs found.")
        print("       Run 'laap domain discover' to scan for SDKs.")
        return 0

    print(f"\n[DOMAINS] {len(manifests)} domain SDK(s) discovered:\n")
    print(f"  {'DOMAIN ID':<20} {'VERSION':<10} {'NAME':<30} {'HARNESS':<8} {'SPECIES':<8}")
    print(f"  {'-'*20} {'-'*10} {'-'*30} {'-'*8} {'-'*8}")
    for m in sorted(manifests, key=lambda x: x.domain_id):
        print(
            f"  {m.domain_id:<20} {m.version:<10} {m.domain_name[:30]:<30} "
            f"{len(m.harness_functions):<8} {len(m.species_categories):<8}"
        )
    print()
    return 0


def _cmd_info(args: list[str]) -> int:
    """Show detailed info for a specific domain SDK."""
    if not args:
        print("Usage: laap domain info <domain_id>")
        return 1

    domain_id = args[0]
    registry = _get_registry()
    manifest = registry.get_manifest(domain_id)

    if manifest is None:
        print(f"[ERROR] Domain SDK '{domain_id}' not found.")
        return 1

    print("\n" + "=" * 60)
    print(f"  Domain: {manifest.domain_name}")
    print(f"  ID:     {manifest.domain_id}")
    print(f"  Ver:    {manifest.version}")
    print(f"  Desc:   {manifest.description}")
    print("=" * 60)

    if manifest.cognitive_actors:
        print(f"\n[Cognitive Actors] ({len(manifest.cognitive_actors)}):")
        for actor in manifest.cognitive_actors:
            print(f"  - {actor}")

    if manifest.harness_functions:
        print(f"\n[Harness Functions] ({len(manifest.harness_functions)}):")
        for fn in manifest.harness_functions:
            print(f"  - {fn}")

    if manifest.species_categories:
        print(f"\n[Species Categories] ({len(manifest.species_categories)}):")
        for cat in manifest.species_categories:
            print(f"  - {cat}")

    if manifest.bus_topics:
        print(f"\n[Bus Topics] ({len(manifest.bus_topics)}):")
        for topic in manifest.bus_topics:
            print(f"  - {topic}")

    if manifest.data_sources:
        print(f"\n[Data Sources] ({len(manifest.data_sources)}):")
        for src in manifest.data_sources:
            print(f"  - {src}")

    if manifest.safety_policy_class:
        print(f"\n[Safety Policy] {manifest.safety_policy_class}")

    print(f"\n[Min LAAP Version] {manifest.min_laap_version}")
    print()
    return 0


def _cmd_discover(args: list[str]) -> int:
    """Discover available domain SDKs."""
    from laap.domain_sdk.loader import list_builtin_sdks
    registry = DomainSDKRegistry = _get_registry()

    builtin = list_builtin_sdks()
    print(f"\n[DISCOVER] Scanning for domain SDKs...")
    print(f"  Built-in directory: {len(builtin)} SDK(s) found")
    for d in builtin:
        print(f"    - {d}")

    discovered = registry.list_domains()
    print(f"\n  Total registered: {len(discovered)}")
    for d in discovered:
        m = registry.get_manifest(d)
        if m:
            print(f"    - {d} v{m.version} ({m.domain_name})")
    print()
    return 0


def _cmd_harness(args: list[str]) -> int:
    """List harness functions, optionally for a specific domain."""
    from laap.domain_sdk.harness_function import HarnessFunctionRegistry
    registry = HarnessFunctionRegistry()

    domain = args[0] if args else None

    # In a real runtime, functions are registered by mounted SDKs.
    # For standalone CLI, we show what's available from discovery.
    funcs = registry.list(domain=domain)

    if not funcs:
        if domain:
            print(f"[INFO] No harness functions found for domain '{domain}'.")
            print("       Is the domain SDK mounted?")
        else:
            print("[INFO] No harness functions registered.")
        return 0

    print(f"\n[HARNESS FUNCTIONS] {len(funcs)} function(s):")
    print(f"  {'NAME':<40} {'DOMAIN':<12} {'CATEGORY':<15} {'ZERO-TOKEN'}")
    print(f"  {'-'*40} {'-'*12} {'-'*15} {'-'*10}")
    for f in sorted(funcs, key=lambda x: x.name):
        print(
            f"  {f.name:<40} {f.domain:<12} {f.category:<15} "
            f"{'[OK]' if f.zero_token else '[TOKEN]'}"
        )
    print()
    return 0


def _cmd_species(args: list[str]) -> int:
    """List species templates, optionally for a specific domain."""
    from laap.domain_sdk.species import SpeciesLibrary
    library = SpeciesLibrary()

    domain = args[0] if args else None
    templates = library.list(domain=domain)

    if not templates:
        if domain:
            print(f"[INFO] No species templates found for domain '{domain}'.")
        else:
            print("[INFO] No species templates registered.")
        return 0

    print(f"\n[SPECIES TEMPLATES] {len(templates)} template(s):")
    print(f"  {'ID':<45} {'DOMAIN':<12} {'CATEGORY':<15} {'VER'}")
    print(f"  {'-'*45} {'-'*12} {'-'*15} {'-'*8}")
    for t in sorted(templates, key=lambda x: x.id):
        print(
            f"  {t.id:<45} {t.domain:<12} {t.category:<15} v{t.species_version}"
        )
    print()
    return 0


def _cmd_safety(args: list[str]) -> int:
    """Show safety policy configuration for a domain."""
    if not args:
        print("Usage: laap domain safety <domain_id>")
        return 1

    domain_id = args[0]
    print(f"\n[SAFETY] Domain: {domain_id}")
    print("[INFO] Safety policy details require a running runtime with the domain mounted.")
    print("       In a runtime context, use: runtime._safety_policies['{0}'].get_config()".format(domain_id))
    print()
    return 0


def _cmd_create(args: list[str]) -> int:
    """Scaffold a new domain SDK (wizard)."""
    if not args:
        name = input("Domain ID (e.g. finquant): ").strip()
    else:
        name = args[0]

    if not name:
        print("[ERROR] Domain ID is required.")
        return 1

    name = name.lower().replace(" ", "_").replace("-", "_")

    print(f"\n[CREATE] Scaffolding domain SDK: {name}")
    print("  (This wizard will create the directory structure)")
    print()

    # TODO: implement actual scaffolding in Phase 1
    print("  Scaffolding is planned for Phase 1 implementation.")
    print(f"  Target directory: laap/domain_sdks/{name}/")
    print()
    return 0
