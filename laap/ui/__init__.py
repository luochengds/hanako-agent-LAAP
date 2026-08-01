"""LAAP UI modules - Golden Dragon TUI.

Import strategy
---------------
- Theme / dragon art are lazily imported via PEP 562 __getattr__
  to avoid ``ModuleNotFoundError: No module named 'rich'`` when Rich is
  not installed (REPL / headless / pip install laap without [tui] extra).
- TUI / Textual are heavy optional dependencies, also lazily loaded.
"""
__all__ = [
    "DRAGON", "gold_style", "gradient_text", "DragonColors",
    "DRAGON_FRAMES", "GOLD", "GOLD_BRIGHT", "SYM", "TITLE_CN",
    "run_tui", "GoldenDragonTUI", "GoldenDragonApp",
    "MainScreen", "MessageDisplay", "DragonBanner",
    "LAAP_TUI",
]


def __getattr__(name):
    """Resolve laap.ui.<symbol> lazily to avoid hard 'rich' dependency."""
    # Theme / dragon art (requires rich)
    if name in {"DragonColors", "DRAGON", "gold_style", "gradient_text"}:
        from laap.ui import theme as _m
        return getattr(_m, name)
    # Dragon art constants (plain, no Rich dependency)
    if name in {"DRAGON_FRAMES", "GOLD", "GOLD_BRIGHT", "SYM", "TITLE_CN"}:
        from laap.ui import dragon_art as _m
        return getattr(_m, name)
    # TUI symbols (require textual + rich)
    if name in {
        "run_tui", "GoldenDragonTUI", "GoldenDragonApp",
        "MainScreen", "MessageDisplay", "DragonBanner",
        "LAAP_TUI",
    }:
        from laap.ui import tui as _m
        return getattr(_m, name)
    raise AttributeError(f"module 'laap.ui' has no attribute {name!r}")
