"""LAAP — First-Run Onboarding Wizard"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os, sys, time

from laap.cli.skins import GOLD, GOLD_BRIGHT, GOLD_DIM, RESET, BOLD, SYM

def show_logo() -> str:
    return r"""                                 _____
      /\                  / ____|
     /  \   ___ ___  ___ | |  __  __ _ _ __ ___   ___
    / /\ \ / __/ __|/ _ \| | |_ |/ _` | '_ ` _ \ / _ \
   / ____ \\__ \__ \ (_) | |__| | (_| | | | | | |  __/
  /_/    \_\___/___/\___/ \_____|\__,_|_| |_| |_|\___|
    """

def show_intro() -> str:
    return "Lifeform Autonomous Adaptive Protocol — 自进化引擎意识生命体"

def show_help() -> str:
    return f"""
  {GOLD_BRIGHT}Commands:{RESET}
    {GOLD}/help{RESET}     — Show help
    {GOLD}/exit{RESET}     — Exit
    {GOLD}/status{RESET}   — Agent status
    {GOLD}/new{RESET}      — New session
    {GOLD}/memory{RESET}   — Memory tools
    {GOLD}/model{RESET}    — Switch model
    {GOLD}/config{RESET}   — Configuration
    """

def check_config() -> bool:
    """Check if API keys are configured."""
    providers = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]
    found = [k for k in providers if os.environ.get(k)]
    return len(found) > 0

def run_wizard() -> bool:
    """Interactive setup wizard for first run."""
    from laap.cli.config_manager import config_manager as _cm
    from laap.cli.skins import GOLD as _G, GOLD_BRIGHT as _GB, GOLD_DIM as _GD, RESET as _R, SYM as _SYM

    logger.info(f"\n  {_GB}{_SYM['dragon']} Welcome to LAAP! Let's get you set up.{_R}\n")
    providers = {
        "1": ("OpenAI", "openai", "OPENAI_API_KEY", "gpt-4o"),
        "2": ("Anthropic Claude", "anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
        "3": ("DeepSeek", "deepseek", "DEEPSEEK_API_KEY", "deepseek-chat"),
        "4": ("Google Gemini", "google", "GEMINI_API_KEY", "gemini-2.5-flash"),
    }
    
    logger.info(f"  {_G}Select your LLM provider:{_R}")
    for k, (disp, _, _, _) in providers.items():
        logger.info(f"    {_G}{k}{_R}) {disp}")
    choice = input(f"\n  {_G}Choice [1]: {_R}").strip() or "1"
    
    if choice in providers:
        disp_name, prov_id, env_key, default_model = providers[choice]
        logger.info(f"\n  {_GD}Enter your {disp_name} API key:{_R}")
        key = input(f"  {_G}>{_R} ").strip()
        if key:
            os.environ[env_key] = key
            # Save to .env for subprocess compatibility
            env_path = os.path.join(os.path.expanduser("~"), ".laap", ".env")
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            # Append or update
            lines = []
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if not line.startswith(env_key + "="):
                            lines.append(line)
            lines.append(f"{env_key}={key}\n")
            with open(env_path, "w") as f:
                f.writelines(lines)
            # Also save to config_manager directly
            _cm.config.providers[prov_id] = type('ProviderConfig', (), {
                "name": disp_name, "api_key": key,
                "base_url": _cm.config.providers.get(prov_id, type('P',(),{})).base_url if hasattr(_cm.config.providers.get(prov_id, None), 'base_url') else "",
                "model": _cm.config.providers.get(prov_id, type('P',(),{})).model if hasattr(_cm.config.providers.get(prov_id, None), 'model') else default_model,
                "custom": False,
            }) if False else None
            # Simpler: direct dict manipulation
            from laap.cli.config_manager import ProviderConfig
            _cm.config.providers[prov_id] = ProviderConfig(
                name=disp_name, api_key=key, model=default_model,
            )
            _cm.config.active_provider = prov_id
            _cm.save()
            logger.info(f"  {_G}✓ API key configured!{_R}")
            return True
    
    logger.info(f"  {_GD}You can always configure later with --config{_R}")
    return False

def config_wizard():
    """Configuration wizard (separate entry point)."""
    logger.info(f"\n  {GOLD_BRIGHT}LAAP Configuration Wizard{RESET}")
    run_wizard()