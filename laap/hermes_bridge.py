"""
LAAP ↔ Hermes Unified Bidirectional Bridge (统一双向桥接)

Previously: 51-line subprocess wrapper (laap/hermes_bridge.py)
Now: Full bidirectional integration layer connecting:
  Hermes → LAAP: AGI cognitive enhancement (already done via agi_bridge)
  LAAP → Hermes: LLM access, session sync, skill pipeline, tool delegation

Key integrations:
  1. LLM Provider Bridge — AGI modules call LLMs through Hermes's 20+ providers
  2. Session Sync — AGI state ↔ Hermes session DB (SQLite+FTS5)
  3. Skill Pipeline — Evolution proposals → Hermes skills
  4. Tool Delegation — AGI autonomy → Hermes tool execution
  5. Memory Sync — LAAP 5-layer memory ↔ Hermes persistent memory
  6. Config Sync — Shared configuration between frameworks
  7. Event Bus — Cross-framework event notification

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │                     LAAP (Brain)                         │
  │  ┌───────────────────────────────────────────────────┐  │
  │  │           UnifiedBridge (this file)                │  │
  │  │  ┌─────────────────────────────────────────────┐  │  │
  │  │  │         Hermes (Body)                        │  │  │
  │  │  │  Providers | Tools | Gateway | Sessions      │  │  │
  │  │  │  Skills | Cron | Memory | Checkpoints        │  │  │
  │  │  └─────────────────────────────────────────────┘  │  │
  │  └───────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────┘

Usage:
    from laap.hermes_bridge import UnifiedBridge
    bridge = UnifiedBridge()
    bridge.llm_call("What is gravity?")
    bridge.sync_session(agent_id="Ao", session_data={...})
    bridge.propose_skill("new_pattern", domain="coding")
"""

from __future__ import annotations

import logging

from typing import Any, Dict, List, Optional, Callable
import threading, logging, os, sys, time, json, subprocess
from pathlib import Path
from dataclasses import dataclass, field

from laap.config.paths import get_hermes_root

logger = logging.getLogger("laap.hermes_bridge")


# ════════════════════════════════════════════════════════════
# Configuration Detection
# ════════════════════════════════════════════════════════════

def detect_hermes() -> Dict[str, Any]:
    """Detect Hermes installation and capabilities."""
    root = get_hermes_root()
    if root is not None:
        c = str(root)
        run_agent = os.path.join(c, "run_agent.py")
        cli = os.path.join(c, "cli.py")
        if os.path.exists(run_agent):
            return {
                "available": True,
                "home": c,
                "run_agent": run_agent,
                "cli": cli,
            }
        logger.warning(
            "UnifiedBridge: HERMES_ROOT points to %s but run_agent.py is missing; "
            "Hermes integration disabled.",
            c,
        )
    else:
        logger.warning(
            "UnifiedBridge: HERMES_ROOT not set and no Hermes installation found. "
            "Set HERMES_ROOT environment variable to enable Hermes integration."
        )
    return {"available": False}


# ════════════════════════════════════════════════════════════
# Unified Bridge
# ════════════════════════════════════════════════════════════

class UnifiedBridge:
    """
    Bidirectional bridge between LAAP AGI framework and Hermes Agent.

    Provides Hermes infrastructure services to LAAP modules,
    and LAAP cognitive capabilities to Hermes.
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.hermes = detect_hermes()
        self.hermes_home = self.hermes.get("home", "")
        self.created_at = time.time()

        # Service references (lazy init)
        self._llm_provider = None
        self._session_db = None
        self._skill_engine = None
        self._tool_registry = None
        self._memory_bridge = None

        # Stats
        self.total_llm_calls = 0
        self.total_sessions_synced = 0
        self.total_skills_proposed = 0

        logger.info(f"UnifiedBridge: Hermes {'available' if self.hermes['available'] else 'unavailable'} "
                     f"at {self.hermes_home}")

    @classmethod
    def get_instance(cls) -> "UnifiedBridge":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ════════════════════════════════════════════════════════
    # 1. LLM Provider Bridge
    # ════════════════════════════════════════════════════════

    def llm_call(self, prompt: str, system_prompt: str = "",
                 model: str = None, provider: str = None,
                 max_tokens: int = 1000) -> Dict[str, Any]:
        """
        Call LLM through Hermes's provider layer.

        This gives LAAP's AGI modules access to all 20+ providers
        that Hermes supports: OpenAI, Anthropic, DeepSeek, OpenRouter, etc.
        """
        self.total_llm_calls += 1

        if not self.hermes["available"]:
            return {"error": "Hermes not available", "text": ""}

        try:
            # Use Hermes CLI for reliable integration
            cmd = [
                sys.executable, "-m", "hermes", "chat",
                "-q", prompt,
                "--quiet",
            ]
            if model:
                cmd.extend(["-m", model])

            result = subprocess.run(
                cmd, cwd=self.hermes_home,
                capture_output=True, text=True,
                timeout=60,
                env={**os.environ, "PYTHONPATH": self.hermes_home},
            )

            return {
                "text": (result.stdout or result.stderr)[:max_tokens],
                "success": result.returncode == 0,
                "model": model or "default",
                "call_id": self.total_llm_calls,
            }
        except subprocess.TimeoutExpired:
            return {"error": "LLM call timeout", "text": ""}
        except Exception as e:
            return {"error": str(e), "text": ""}

    async def llm_call_async(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Async LLM call (when running within Hermes process)."""
        # This is used when LAAP runs INSIDE Hermes via integrate.py
        return self.llm_call(prompt, **kwargs)

    def get_available_models(self) -> List[str]:
        """Get list of available models from Hermes."""
        if not self.hermes["available"]:
            return []
        try:
            # Try to import Hermes model registry
            sys.path.insert(0, self.hermes_home)
            from hermes.agent.model_registry import MODEL_REGISTRY
            return list(MODEL_REGISTRY.keys())[:30]
        except ImportError:
            return ["default"]

    # ════════════════════════════════════════════════════════
    # 2. Session Sync
    # ════════════════════════════════════════════════════════

    def sync_session(self, agent_id: str,
                     session_data: Dict[str, Any]) -> bool:
        """
        Sync AGI state to Hermes session DB.

        Allows Hermes sessions to carry LAAP cognitive state.
        """
        self.total_sessions_synced += 1

        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from hermes.hermes_state import SessionDB
                db = SessionDB()
                # Store AGI state as session metadata
                db.update_session_metadata(agent_id, {
                    "laap_version": "2.2.0",
                    "modules_active": session_data.get("module_count", 0),
                    "last_sync": time.time(),
                    "agi_state": json.dumps(session_data, default=str),
                })
                return True
        except Exception as e:
            logger.debug(f"Session sync failed: {e}")
        return False

    def load_session_state(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Load AGI state from Hermes session DB."""
        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from hermes.hermes_state import SessionDB
                db = SessionDB()
                meta = db.get_session_metadata(agent_id)
                if meta and "agi_state" in meta:
                    return json.loads(meta["agi_state"])
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        return None

    # ════════════════════════════════════════════════════════
    # 3. Skill Pipeline
    # ════════════════════════════════════════════════════════

    def propose_skill(self, name: str, domain: str,
                      steps: List[str], success_rate: float = 0.5,
                      description: str = "") -> Dict[str, Any]:
        """
        Convert an AGI evolution proposal into a Hermes skill.

        When the evolution system discovers a repeatable pattern,
        this creates a proper SKILL.md that Hermes can load.
        """
        self.total_skills_proposed += 1

        skill_content = f"""---
name: {name}
description: "{description or f'Auto-generated skill for {domain}'}"
version: 1.0.0
author: LAAP AGI Evolution
tags: [auto-generated, {domain}]
---

# {name}

Auto-generated by LAAP AGI CodeEvolution v2.1.

## Domain
{domain}

## Steps
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(steps))}

## Success Rate
{success_rate:.0%} (from evolution analysis)
"""

        # Save to Hermes skills directory
        skill_path = None
        if self.hermes["available"]:
            skill_dir = os.path.join(self.hermes_home, "skills", "agi-generated")
            os.makedirs(skill_dir, exist_ok=True)
            skill_path = os.path.join(skill_dir, f"{name}.md")
            with open(skill_path, 'w', encoding='utf-8') as f:
                f.write(skill_content)

        return {
            "name": name,
            "saved_to": skill_path,
            "content_preview": skill_content[:200],
            "success": skill_path is not None,
        }

    # ════════════════════════════════════════════════════════
    # 4. Tool Delegation
    # ════════════════════════════════════════════════════════

    def execute_tool(self, tool_name: str, args: Dict[str, Any] = None,
                     timeout: int = 30) -> Dict[str, Any]:
        """
        Execute a Hermes tool from LAAP's AGI modules.

        This allows the autonomous engine to use Hermes's full tool suite
        for its goal-driven actions.
        """
        args = args or {}

        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from tools.registry import registry
                handler = registry.get_handler(tool_name)
                if handler:
                    result = handler(args)
                    return {"success": True, "tool": tool_name, "result": str(result)[:500]}
        except Exception as e:
            logger.debug(f"Tool delegation failed for {tool_name}: {e}")

        return {"success": False, "tool": tool_name, "error": "Tool not available"}

    def list_available_tools(self) -> List[str]:
        """List all tools available through Hermes."""
        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from toolsets import _HERMES_CORE_TOOLS
                return _HERMES_CORE_TOOLS
        except ImportError:
            pass  # 可选模块，降级处理
        return []

    # ════════════════════════════════════════════════════════
    # 5. Memory Sync
    # ════════════════════════════════════════════════════════

    def sync_memory(self, key: str, value: Any) -> bool:
        """
        Sync a LAAP memory entry to Hermes persistent memory.
        """
        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from tools.memory_tool import memory_tool
                memory_tool(key, str(value), action="add", target="memory")
                return True
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        return False

    def recall_memory(self, key: str) -> Optional[str]:
        """Recall a memory from Hermes persistent store."""
        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from tools.memory_tool import memory_tool
                return memory_tool(key, action="search")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        return None

    # ════════════════════════════════════════════════════════
    # 6. Config Sync
    # ════════════════════════════════════════════════════════

    def get_hermes_config(self, key: str, default: Any = None) -> Any:
        """Read a Hermes config value."""
        try:
            if self.hermes["available"]:
                sys.path.insert(0, self.hermes_home)
                from hermes_cli.config import load_config
                config = load_config()
                keys = key.split(".")
                val = config
                for k in keys:
                    val = val.get(k, {})
                return val if val != {} else default
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        return default

    # ════════════════════════════════════════════════════════
    # 7. Status
    # ════════════════════════════════════════════════════════

    def status(self) -> Dict[str, Any]:
        return {
            "hermes_available": self.hermes["available"],
            "hermes_home": self.hermes_home,
            "llm_calls": self.total_llm_calls,
            "sessions_synced": self.total_sessions_synced,
            "skills_proposed": self.total_skills_proposed,
            "available_tools": len(self.list_available_tools()),
            "uptime_seconds": time.time() - self.created_at,
        }


# ════════════════════════════════════════════════════════════
# Legacy Compatibility
# ════════════════════════════════════════════════════════════

def check_hermes() -> Dict[str, Any]:
    """Legacy compatibility wrapper."""
    bridge = UnifiedBridge.get_instance()
    return bridge.hermes

def run_with_hermes(prompt: str) -> str:
    """Legacy compatibility wrapper."""
    bridge = UnifiedBridge.get_instance()
    result = bridge.llm_call(prompt)
    return result.get("text", "") or result.get("error", "")


class HermesAgentWrapper:
    """Legacy compatibility wrapper (matches old HermesAgentWrapper)."""

    def __init__(self):
        self.bridge = UnifiedBridge.get_instance()
        self.name = "Ao (Hermes↔LAAP)"

    def chat(self, text: str, handler=None) -> str:
        result = self.bridge.llm_call(text)
        response = result.get("text", "")
        if handler and hasattr(handler, 'on_token'):
            for word in response.split():
                handler.on_token(word + " ")
                time.sleep(0.01)
        return response
