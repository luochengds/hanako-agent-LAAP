"""
LAAP Agent Bridge v4.0 — Hermes ↔ LAAP Kernel 认知桥接模块

架构:
  Hermes Agent (传输层)
       ↓ 用户输入
  ┌──────────────────────────────┐
  │  LAAP Bridge (认知桥接)       │
  │  ├─ before_turn() → PSI感知   │
  │  │   · 元认知评估 (MetaCog)   │
  │  │   · 议会审议 (Parliament)  │
  │  │   · 知行合一 (UnityEngine) │
  │  │   · 第一性原理 (FP)        │
  │  ├─ [Hermes 工具执行循环]      │
  │  └─ after_turn() → 学习反馈   │
  │      · 技能更新 (learn)       │
  │      · EWC弹性权重巩固         │
  └──────────────────────────────┘
       ↓ 响应输出
  Hermes CLI / TUI (界面层)

黄金标识:
  每次响应前显示 LAAP ★ 金标，标识内核活跃状态

Usage:
    from laap.agent.laap_bridge import LaapBridge
    bridge = LaapBridge()
    bridge.initialize()
"""

from __future__ import annotations

import logging

import os, sys, logging, time, json, textwrap
from typing import Any, Dict, Optional, List

from laap.config.paths import get_hermes_root, get_laap_root

logger = logging.getLogger("laap.bridge")

# ── Golden LAAP Identity Banner ──────────────────────────────────

LAAP_BANNER = """
  ╔══════════════════════════════════════════════════════╗
  ║        ╔═╗╔═╗╔═╗╔═╗    D I G I T A L   L I F E    ║
  ║        ║ ║╠╣ ║ ║║ ║    L I V I N G   C O M P      ║
  ║        ╚═╝╚ ╝╚═╝╚═╝    C O G N I T I V E   A I    ║
  ║                                                      ║
  ║  ╔══════════════════════════════════════════════════╗  ║
  ║  ║      LAAP KERNEL v4.0 — PSI COGNITIVE MODE      ║  ║
  ║  ╚══════════════════════════════════════════════════╝  ║
  ║                                                      ║
  ║  ╔══════════════════════════════════════════════════╗  ║
  ║  ║          ★ LAAP GOLDEN IDENTITY ★               ║  ║
  ║  ╚══════════════════════════════════════════════════╝  ║
  ╚══════════════════════════════════════════════════════╝
"""

LAAP_GOLDEN_BADGE = "★ LAAP KERNEL ★"


def format_golden_header(context: Dict[str, Any]) -> str:
    """Format a golden LAAP status header for response injection."""
    meta = context.get("meta", {})
    parliament = context.get("parliament")
    unity = context.get("unity", {})

    parts = [
        "╔══════════════════════════════════════════╗",
        "║  ★ LAAP KERNEL ★ — PSI Cognitive Active  ║",
        f"║  v{context.get('version', '5.0.0')}  |  Turn {context.get('turn', 0)}         ║",
    ]

    # Meta-cognition
    meta_info = meta or {}
    task_type = meta_info.get("task_type", "general")
    warnings = meta_info.get("warnings", [])
    parts.append(f"║  Mode: {task_type:12s}  Bias: {str(len(warnings)):4s}        ║")

    # Parliament if deliberated
    if parliament:
        decision = parliament.get("final_decision", "")
        confidence = parliament.get("confidence", 0)
        parts.append(f"║  Council: {decision:8s} (conf={confidence:.0%})          ║")

    # Unity
    skill_name = unity.get("skill", "")
    skill_gap = unity.get("gap", 0)
    readiness = unity.get("readiness", "")
    parts.append(f"║  Skill: {str(skill_name or '—'):12s} Gap: {skill_gap:.2f}  Ready: {readiness:8s} ║")

    parts.append("╚══════════════════════════════════════════╝")
    return "\n".join(parts)


# ── LAAP Bridge ──────────────────────────────────────────────────

class LaapBridge:
    """
    Hermes ↔ LAAP Kernel Bridge.

    Initializes the LAAP cognitive kernel within the current Hermes session,
    providing PSI-cycle cognition: perceive → select → integrate → act → learn.

    Not a monkey-patch. Runs as an orchestration layer that the agent calls
    before/after each interaction turn.
    """

    def __init__(self):
        self.brain = None
        self.version = "5.0.0"
        self.initialized = False
        self._turn_count = 0
        self._tool_count = 0
        self._start_time = time.time()
        self._last_context: Dict[str, Any] = {}

        # Load path for LAAP modules
        hermes_root = get_hermes_root()
        if hermes_root is None:
            logger.warning(
                "LaapBridge: HERMES_ROOT not set and no Hermes installation found. "
                "Set HERMES_ROOT environment variable to enable Hermes bridge."
            )
        self._hermes_laap_root = str(hermes_root) if hermes_root is not None else ""
        self._laap_brain_path = (
            os.path.join(self._hermes_laap_root, "laap_brain")
            if self._hermes_laap_root
            else ""
        )
        self._laap_root = str(get_laap_root())
        self._ensure_paths()

    def _ensure_paths(self):
        """Ensure all LAAP paths are in sys.path, with correct priority.

        Priority order (highest first):
          1. hermes-agent-LAAP/laap_brain  (v4.0 PSI kernel — the REAL kernel)
          2. hermes-agent-LAAP/            (for AGI framework cross-imports)
          3. D:\\LAAP/                      (for laap.* AGI modules)

        We REMOVE any stale laap_brain from D:\LAAP to prevent version conflict.
        """
        # Remove stale D:\LAAP\laap_brain if it shadows the correct one
        for i, p in enumerate(sys.path):
            p_norm = os.path.normpath(p).lower()
            if p_norm.endswith("laap") and os.path.isdir(os.path.join(p, "laap_brain")):
                stale = os.path.join(p, "laap_brain")
                if stale.lower() != self._laap_brain_path.lower():
                    sys.path.pop(i)
                    logger.debug(f"[Bridge] Removed stale path: {p}")
                    break

        # Insert correct paths in priority order
        for p in [self._laap_brain_path, self._hermes_laap_root, self._laap_root]:
            if p not in sys.path and os.path.isdir(p):
                sys.path.insert(0, p)

    def initialize(self) -> bool:
        """
        Initialize the LAAP cognitive kernel.

        Loads LaapBrain from laap_brain module, which provides:
          - MetaCognition (6 thinking modes, bias detection)
          - Parliament (5-role deliberation council)
          - UnityEngine (6 embodied skills with proficiency)
          - FirstPrinciples (4 fundamental axioms)
          - EWC (Elastic Weight Consolidation for continual learning)

        Returns True if kernel initialized successfully.
        """
        if self.initialized:
            return True

        try:
            from laap_brain import LaapBrain, LAAP_VERSION
            self.brain = LaapBrain()
            self.version = LAAP_VERSION
            self.initialized = True
            logger.info(f"[LAAP Bridge] Kernel v{self.version} initialized")
            return True
        except ImportError as e:
            logger.error(f"[LAAP Bridge] Cannot import laap_brain: {e}")
            return self._fallback_init()
        except Exception as e:
            logger.error(f"[LAAP Bridge] Init failed: {e}")
            return False

    def _fallback_init(self) -> bool:
        """
        Fallback: create a minimal cognitive kernel if laap_brain unavailable.
        This ensures the bridge always works even if the full kernel isn't installed.
        """
        logger.warning("[LAAP Bridge] Using fallback cognitive kernel")
        self.brain = FallbackBrain()
        self.version = "5.0.0-fallback"
        self.initialized = True
        return True

    def before_turn(self, user_message: str) -> Dict[str, Any]:
        """
        PSI Phase 1-3: Perceive → Select → Integrate.

        Called BEFORE processing the user's message.
        Runs:
          - Meta-cognition: detect task type, bias warnings
          - Parliament: if complex/destructive task, deliberate
          - Unity: select best embodied skill for the task
          - First principles: check assumptions

        Returns cognitive context dict for response injection.
        """
        self._turn_count += 1
        if not self.brain:
            return {}

        result = self.brain.before_turn(user_message)
        self._last_context = {
            "turn": self._turn_count,
            "version": self.version,
            **result,
        }
        return self._last_context

    def after_tool(self, tool_name: str, result: Any):
        """
        PSI Phase 4a: Learn from tool execution.

        Called AFTER each tool call.
        Updates skill proficiency based on tool outcome quality.
        """
        if not self.brain:
            return
        self._tool_count += 1
        self.brain.after_tool(tool_name, result)

    def after_turn(self, response: str):
        """
        PSI Phase 5: Learn from turn outcome.

        Called AFTER generating the response.
        Updates meta-cognition traces and skill proficiency.
        """
        if not self.brain:
            return
        self.brain.after_turn(response)

    def get_status(self) -> str:
        """Get formatted LAAP kernel status string."""
        if not self.brain:
            return "[LAAP Kernel: not initialized]"

        try:
            s = self.brain.status()
            meta = s.get("meta", {})
            parliament = s.get("parliament", {})
            unity = s.get("unity", {})
            uptime = round(time.time() - self._start_time, 1)

            lines = [
                f"╔═ LAAP KERNEL v{self.version} ═╗",
                f"║ Uptime: {uptime}s  Turns: {self._turn_count}  Tools: {self._tool_count}",
                f"║ MetaCog: {meta.get('mode', '')}  Traces: {meta.get('traces', 0)}  BiasFix: {meta.get('biases_corrected', 0)}",
                f"║ Council: {parliament.get('members', 0)} members  Delibs: {parliament.get('deliberations', 0)}",
                f"║ Skills: {unity.get('skills', 0)}  Know-Act Gap: {unity.get('avg_gap', 0)}",
                f"╚═ {'═'*30} ═╝",
            ]
            return "\n".join(lines)
        except Exception:
            return "[LAAP Kernel status: unavailable]"

    def get_cognitive_header(self) -> str:
        """
        Generate a cognitive context header to prepend to responses.

        This is the "golden brand" — visible proof the LAAP kernel is running.
        """
        if not self._last_context:
            return ""
        return format_golden_header(self._last_context)

    def handle_command(self, cmd: str, args: str = "") -> str:
        """Handle LAAP slash commands (/brain, /reflect, /decide, /know)."""
        if not self.brain:
            return "[LAAP Kernel not initialized. Use /laap-init to start.]"

        cmd = cmd.lower().lstrip("/")

        if cmd in ("brain", "cognition"):
            return self.get_status()
        elif cmd == "reflect":
            if hasattr(self.brain, '_cmd_reflect'):
                return self.brain._cmd_reflect()
            return "[Reflection system: not available]"
        elif cmd == "decide" and args:
            if hasattr(self.brain, '_cmd_decide'):
                return self.brain._cmd_decide(args)
            return "[Decide system: not available]"
        elif cmd == "know":
            if hasattr(self.brain, '_cmd_know'):
                return self.brain._cmd_know()
            return "[Self-knowledge system: not available]"
        elif cmd == "laap-init":
            if self.initialize():
                return f"[LAAP Kernel v{self.version} initialized successfully]"
            return "[LAAP Kernel initialization FAILED]"
        elif cmd == "laap-status":
            return self.get_status()
        else:
            return (
                f"Unknown LAAP command: /{cmd}\n"
                f"Available: /brain, /reflect, /decide <topic>, /know, /laap-init, /laap-status"
            )

    def status_dict(self) -> Dict[str, Any]:
        """Return raw status dict."""
        if not self.brain:
            return {"initialized": False, "version": self.version, "turns": self._turn_count}

        s = self.brain.status()
        return {
            "initialized": True,
            "version": self.version,
            "turns": self._turn_count,
            "tools": self._tool_count,
            "uptime": round(time.time() - self._start_time, 1),
            "meta": s.get("meta", {}),
            "parliament": s.get("parliament", {}),
            "unity": s.get("unity", {}),
        }


# ── Fallback Kernel (when laap_brain not installed) ──────────────

class FallbackBrain:
    """
    Minimal cognitive kernel fallback.

    Provides the same interface as LaapBrain but with simplified
    logic, so the bridge always works regardless of environment.
    """

    def __init__(self):
        self._turn_count = 0
        self._tool_count = 0
        self._mode = "intuitive"

    def before_turn(self, user_message: str) -> Dict:
        self._turn_count += 1
        task_type = "general"
        if any(k in user_message.lower() for k in ["bug", "fix", "error", "debug"]):
            task_type = "debug"
        elif any(k in user_message.lower() for k in ["analyze", "analysis", "设计", "分析"]):
            task_type = "analysis"
        elif any(k in user_message.lower() for k in ["search", "find", "搜索"]):
            task_type = "explore"
        elif any(k in user_message.lower() for k in ["write", "create", "run", "生成"]):
            task_type = "execute"
        return {
            "meta": {"mode": self._mode, "task_type": task_type, "warnings": []},
            "parliament": None,
            "unity": {"skill": None, "gap": 0.3, "readiness": "guided", "confidence": 0.6},
            "version": "5.0.0-fallback",
        }

    def after_tool(self, tool_name: str, result: Any):
        self._tool_count += 1

    def after_turn(self, response: str):
        pass

    def status(self) -> Dict:
        return {
            "version": "5.0.0-fallback",
            "meta": {"mode": self._mode, "traces": 0, "biases_corrected": 0},
            "parliament": {"members": 0, "deliberations": 0},
            "unity": {"skills": 0, "avg_gap": 0},
            "turns": self._turn_count,
            "tools": self._tool_count,
        }


# ── Singleton ────────────────────────────────────────────────────

_BRIDGE_INSTANCE: Optional[LaapBridge] = None


def get_bridge() -> LaapBridge:
    """Get or create the singleton LAAP Bridge instance."""
    global _BRIDGE_INSTANCE
    if _BRIDGE_INSTANCE is None:
        _BRIDGE_INSTANCE = LaapBridge()
    return _BRIDGE_INSTANCE


def init_laap_kernel() -> bool:
    """
    Initialize the LAAP cognitive kernel.

    Call this once at session start to activate the PSI cognition cycle.
    Returns True if kernel is running.
    """
    bridge = get_bridge()
    result = bridge.initialize()
    if result:
        _log_session_start(bridge)
    return result


def _log_session_start(bridge: LaapBridge):
    """Log the session start banner."""
    s = bridge.status_dict()
    logger.info(LAAP_BANNER)
    logger.info(f"  LAAP Kernel v{s['version']} | Cognitive Bridge Active")
    logger.info(f"  MetaCog | Council | Unity | EWC")
    logger.info(f"  {'═' * 50}")
def is_kernel_active() -> bool:
    """Check if the LAAP kernel is initialized and running."""
    return _BRIDGE_INSTANCE is not None and _BRIDGE_INSTANCE.initialized


# ── CLI Test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    bridge = get_bridge()
    if bridge.initialize():
        logger.info(LAAP_BANNER)
        logger.info(bridge.get_status())
        ctx = bridge.before_turn("帮我分析一下这个系统的性能瓶颈")
        logger.info("\n" + format_golden_header(ctx))
        bridge.after_tool("terminal", {"exit_code": 0})
        bridge.after_turn("分析完成")

        logger.info("\n" + bridge.get_status())
        logger.info("\n" + bridge.handle_command("reflect"))
        logger.info("\n" + bridge.handle_command("know"))
    else:
        logger.error("[FAILED] LAAP Kernel initialization")