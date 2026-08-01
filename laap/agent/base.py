"""
LAAP — Agent Base Class (v3.0 AGI Brain)

DEPRECATED — 本模块已废弃
=========================
废弃原因：Agent 对外入口已统一至 laap.agent_core.agent.Agent；
         AGIBrain 现作为 Agent(mode="agi") 的底层实现/兼容包装保留。
替代实现：from laap.agent_core.agent import Agent; Agent(mode="agi")
废弃时间：2026-07-11
登记位置：legacy/INDEX.md

代码保留目的：保持向后兼容，所有历史导入、类名与公共 API 继续可用。

Production AGI-oriented agent with unified Brain (human-like thinking),
Tool Execution Cortex (Hermes-style dispatch), streaming tool call loop,
meta-cognition, parliament deliberation, and first-principles reasoning.
"""

from __future__ import annotations

import asyncio
import logging

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import uuid, time, logging, json, os, sys, math, random

from laap.llm.factory import LLMFactory
from laap.llm.provider import Message, ToolDef
from laap.memory.hierarchical import HierarchicalMemory
from laap.memory.manager import MemoryManager
from laap.memory.providers.builtin import BuiltinMemoryProvider
from laap.tools.tool_registry import ToolRegistry, Tool
from laap.cognition.awareness import AwarenessSystem
from laap.plugins.manager import PluginManager
from laap.ui.display import (
    C, get_spinner, format_response, format_tool_start, format_tool_result,
    format_error, format_divider, TokenDisplay, context_indicator,
)
from laap.ui.stream_handler import StreamHandler
from laap.agent.meta_cognition import MetaCognitionEngine, ThinkingMode, CognitiveTrace
from laap.agent.parliament import Parliament, Deliberation, Opinion
from laap.orchestration.actor import AgentCell, Capability
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType
import shutil
# Brain/Cortex imports are lazy (inside __init__) to avoid circular imports

# Lazy import helper
def _lazy_import(module_path: str, attr: str):
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, attr)

logger = logging.getLogger("laap.agent")

MAX_CONTEXT_ROUNDS = 20  # soft cap — beyond this, compress mid messages


# ════════════════════════════════════════════════════════════
# 注意力机制 (Attention Mechanism)
# ════════════════════════════════════════════════════════════

@dataclass
class AttentionFocus:
    """
    注意力焦点 — Agent 应该关注什么
    
    类比人类的注意力：不是所有输入都同等重要，
    注意力机制帮助 Agent 聚焦于最关键的信息。
    """
    primary_topic: str = ""          # 主要关注点
    secondary_topics: List[str] = field(default_factory=list)  # 次要关注点
    ignored_signals: List[str] = field(default_factory=list)   # 应忽略的信号
    focus_intensity: float = 0.8     # 注意力集中程度
    context_window_priority: List[str] = field(default_factory=list)  # 上下文优先级


class AttentionController:
    """
    注意力控制器 — 管理Agent的注意力分配
    
    核心功能：
    1. 根据任务类型分配注意力权重
    2. 动态调整上下文窗口中的信息优先级
    3. 检测干扰信号并过滤
    4. 支持注意力的显式转移
    """

    def __init__(self):
        self.current_focus = AttentionFocus()
        self._focus_history: List[AttentionFocus] = []
        self._max_history = 20
        self._distraction_count = 0
        self._focus_switches = 0

    def set_focus(self, topic: str, 
                  secondary: List[str] = None,
                  intensity: float = 0.8):
        """设置注意力焦点"""
        old_focus = self.current_focus
        self.current_focus = AttentionFocus(
            primary_topic=topic,
            secondary_topics=secondary or [],
            focus_intensity=max(0.1, min(1.0, intensity)),
        )
        self._focus_history.append(old_focus)
        if len(self._focus_history) > self._max_history:
            self._focus_history = self._focus_history[-self._max_history:]
        self._focus_switches += 1

    def detect_distraction(self, new_input: str) -> bool:
        """检测新输入是否是干扰"""
        if not self.current_focus.primary_topic:
            return False
        
        focus_keywords = self.current_focus.primary_topic.lower().split()
        input_lower = new_input.lower()
        
        # 如果新输入中完全不含焦点关键词，可能是干扰
        if focus_keywords and not any(k in input_lower for k in focus_keywords):
            relevance_score = sum(
                1 for sec in self.current_focus.secondary_topics
                if any(w in input_lower for w in sec.lower().split())
            )
            if relevance_score == 0:
                self._distraction_count += 1
                return True
        return False

    def get_attention_prompt_block(self) -> str:
        """生成注意力提示词块 — 注入 System Prompt"""
        parts = ["[注意力分配]"]
        parts.append(f"主要关注: {self.current_focus.primary_topic}")
        if self.current_focus.secondary_topics:
            parts.append(f"次要关注: {', '.join(self.current_focus.secondary_topics[:3])}")
        parts.append(f"专注强度: {self.current_focus.focus_intensity:.0%}")
        return "\n".join(parts)

    def status(self) -> dict:
        return {
            "focus": self.current_focus.primary_topic[:40],
            "intensity": round(self.current_focus.focus_intensity, 2),
            "switches": self._focus_switches,
            "distractions": self._distraction_count,
        }


# ════════════════════════════════════════════════════════════
# Agent Config
# ════════════════════════════════════════════════════════════

@dataclass
class AgentConfig:
    name: str = "LAAP-Agent"
    description: str = "A LAAP AGI-oriented agent"
    llm_provider: str = ""
    llm_model: str = ""
    system_prompt: str = ""
    max_tool_rounds: int = 15
    tools_enabled: bool = True
    verbose: bool = True
    exploration_rate: float = 0.2
    learning_rate: float = 0.1
    show_tokens: bool = False
    
    # AGI 增强配置
    enable_meta_cognition: bool = True     # 启用元认知
    enable_parliament: bool = True         # 启用议会系统
    enable_attention: bool = True          # 启用注意力机制
    meta_cognition_interval: int = 5       # 每N次chat执行元认知反思
    parliament_on_high_stakes: bool = True  # 高风险决策启用议会
    auto_strategy_selection: bool = True    # 自动选择认知策略
    enable_brain: bool = True               # 启用统一类人脑思维层(v3.0)
    enable_cortex: bool = True              # 启用工具执行皮层(v3.0)
    enable_first_principles: bool = True     # 启用第一性原理(v3.0)


# ════════════════════════════════════════════════════════════
# 工具循环 (Tool Call Loop) — 增强版
# ════════════════════════════════════════════════════════════

class ToolCallLoop:
    """Streaming LLM tool call loop with meta-cognition enhancement and golden dragon UI.
    
    Design:
      - Spinner animates while LLM is thinking
      - Tokens stream in real-time after first word
      - Tool calls shown with status icons (running/success/error)
      - Results displayed with duration + preview
      - Final response formatted with golden dragon styling
      - Automatic context compression via sliding window
      - Meta-cognitive monitoring (bias detection, mode switching)
    """

    def __init__(self, agent: "Agent", max_rounds: int = 15):
        self.agent = agent
        self.max_rounds = max_rounds
        self.round = 0
        self.messages: List[Message] = []
        self.final_response: Optional[str] = None
        self._compress_every = 10  # compress after every N rounds

    def _compress_messages(self):
        """Sliding-window context compression with importance-aware retention."""
        COMPRESS_KEEP = 8
        if len(self.messages) <= MAX_CONTEXT_ROUNDS:
            return
        
        # Find system message index
        sys_idx = 0
        for i, m in enumerate(self.messages):
            if m.role == "system":
                sys_idx = i
                break
        
        # Keep: system + last COMPRESS_KEEP messages
        keep = (
            [m for m in self.messages[max(sys_idx, 0):sys_idx + 1]] 
            if any(m.role == "system" for m in self.messages) 
            else []
        )
        keep_start = sys_idx + 1 if keep else 0
        tail = self.messages[-COMPRESS_KEEP:]
        mid = self.messages[keep_start:-COMPRESS_KEEP]
        
        if mid:
            # 增强版摘要：提取关键工具调用和决策
            tool_types = set()
            decisions = []
            for m in mid:
                if m.tool_calls:
                    for tc in (m.tool_calls if isinstance(m.tool_calls, list) else []):
                        fn = tc.get("function", {}).get("name", "")
                        if fn:
                            tool_types.add(fn)
                if m.content and any(
                    kw in m.content.lower() 
                    for kw in ["decision", "conclusion", "therefore", "所以", "决定"]
                ):
                    decisions.append(m.content[:80])
            
            summary_parts = [f"[Context summary: {len(mid)} previous messages compressed]"]
            if tool_types:
                summary_parts.append(f"Tools: {', '.join(sorted(tool_types)[:8])}")
            if decisions:
                summary_parts.append(f"Decisions: {'; '.join(decisions[:2])}")
            
            summary = Message(
                role="system",
                content=" | ".join(summary_parts),
            )
            self.messages = keep + [summary] + tail
        else:
            self.messages = keep + tail
        
        logger.debug(f"Compressed: {len(mid) + len(keep) + len(tail)} -> {len(self.messages)} msgs")

    def run(self, user_input: str, system_prompt: str = "",
            tools: Optional[List[ToolDef]] = None,
            handler: Optional[StreamHandler] = None,
            initial_messages: Optional[List[Message]] = None) -> str:
        if not self.agent.llm:
            return ""

        self.messages = list(initial_messages) if initial_messages else []
        if system_prompt and not any(m.role == "system" for m in self.messages):
            self.messages.insert(0, Message.system(system_prompt))
        self.messages.append(Message.user(user_input))

        if handler is None:
            handler = StreamHandler(verbose=self.agent.config.verbose)

        # 元认知监控（如果启用）
        meta = self.agent.meta_cognition if hasattr(self.agent, 'meta_cognition') else None
        meta_active = meta and self.agent.config.enable_meta_cognition

        while self.round < self.max_rounds:
            self.round += 1
            content_buf = ""
            tool_calls_result = None
            t_start = time.time()

            # === Phase 1: LLM Streaming ===
            stream = self.agent.llm.chat_stream(self.messages, tools=tools)
            content_buf = handler.process_stream(stream, tools=tools)
            tool_calls_result = handler.tool_call_buffer if handler.tool_call_buffer else None

            response = Message(
                role="assistant", content=content_buf,
                tool_calls=tool_calls_result,
            )
            self.messages.append(response)

            if not response.tool_calls:
                self.final_response = response.content
                # 元认知：记录决策结果
                if meta_active:
                    meta.after_decision({
                        "task": user_input[:60],
                        "confidence": 0.7,
                        "duration_ms": (time.time() - t_start) * 1000,
                    }, outcome={"score": 0.8, "reflection": "直接响应，无工具调用"})
                return response.content

            # === Phase 2: Tool Execution ===
            for tc in response.tool_calls:
                func_name = tc["function"]["name"]
                try:
                    func_args = tc["function"]["arguments"]
                    args = json.loads(func_args) if isinstance(func_args, str) else func_args
                except Exception:
                    args = {}

                if sys.stdout.isatty():
                    get_spinner().add_tool(func_name, args)

                # 元认知：在工具调用前检测偏差
                if meta_active and self.round == 1:
                    bias_warnings = meta.detect_bias_in_response(
                        content_buf, {"tool": func_name}
                    )
                    if bias_warnings:
                        logger.info(
                            f"[ToolCallLoop] 检测到认知偏差: {bias_warnings} "
                            f"(tool={func_name})"
                        )

                # Execute (with permission check + audit)
                if self.agent.config.tools_enabled:
                    from laap.permissions.enforcer import PermissionEnforcer, AccessLevel
                    from laap.utils.audit import get_audit_logger
                    perm = PermissionEnforcer()
                    audit = get_audit_logger()
                    access = perm.check(func_name, args)
                    if access == AccessLevel.DENY:
                        audit.log("permission", func_name, str(args.get("path", "")),
                                  result="denied", details={"reason": "Permission denied"})
                        result = json.dumps({
                            "error": f"Permission denied: {func_name}",
                            "status": "denied",
                        })
                        continue
                    audit.log("tool_exec", func_name, str(args.get("path", "")),
                              result="allowed", details={"args": str(args)[:100]})
                    from laap.permissions.enforcer import enforcer as perm_enforcer
                    perm_resource = {
                        "run_command": "shell:execute", "run_python": "code:execute",
                        "run_script": "shell:execute", "write_file": "file:write",
                        "edit_file": "file:write", "create_file": "file:write",
                        "delete_file": "file:delete", "git_commit": "git:commit",
                        "git_push": "git:push", "git_branch": "git:commit",
                        "web_fetch": "network:connect", "web_search": "network:connect",
                    }.get(func_name, "code:execute")

                    permitted = perm_enforcer.check(perm_resource, f"Tool: {func_name}")
                    if not permitted:
                        tool_result = json.dumps({"error": f"Permission denied: {func_name}"})
                        duration = 0.0
                    else:
                        t0 = time.time()
                        tool_result = self.agent.call_tool(func_name, **args)
                        duration = time.time() - t0
                else:
                    t0 = time.time()
                    tool_result = self.agent.call_tool(func_name, **args)
                    duration = time.time() - t0

                handler.process_tool_result(func_name, tool_result, duration, success=True)

                self.messages.append(Message.tool_result(
                    content=str(tool_result)[:100000],
                    tool_call_id=tc["id"],
                    name=func_name,
                ))

                if self.agent.awareness:
                    self.agent.awareness.record_event("tool_call", {"tool": func_name})

            # 元认知：每轮结束后更新
            if meta_active and self.round % 3 == 0:
                mode_switch = meta.suggest_mode_switch({
                    "confidence": 0.5 + 0.3 * (1.0 - self.round / self.max_rounds),
                    "complexity": len(response.tool_calls) / 5 if response.tool_calls else 0.3,
                    "error_rate": 0.0,
                    "novelty": 0.3 if self.round == 1 else 0.1,
                })
                if mode_switch:
                    logger.info(
                        f"[ToolCallLoop] 元认知切换思考模式: "
                        f"{self.agent.meta_cognition.state.current_mode}"
                    )

            # Periodic context compression
            if self._compress_every and self.round % self._compress_every == 0:
                self._compress_messages()

        # Finalize
        handler.finalize()

        # 元认知：最终反思
        if meta_active:
            meta.perform_reflection()

        # Auto-save session messages
        if self.agent.session_manager and self.messages:
            sid = self.agent._current_session_id or self.agent.id
            msg_dicts = [m.to_dict() for m in self.messages]
            try:
                self.agent.session_manager.save_messages(sid, msg_dicts)
                logger.debug(f"Auto-saved {len(msg_dicts)} messages to session {sid}")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        return self.final_response or "Max rounds reached"

    async def arun(self, user_input: str, system_prompt: str = "",
                   tools: Optional[List[ToolDef]] = None,
                   initial_messages: Optional[List[Message]] = None) -> str:
        if not self.agent.llm:
            return "(no LLM available)"
        self.messages = list(initial_messages) if initial_messages else []
        if system_prompt and not any(m.role == "system" for m in self.messages):
            self.messages.insert(0, Message.system(system_prompt))
        self.messages.append(Message.user(user_input))

        handler = StreamHandler(verbose=self.agent.config.verbose)

        while self.round < self.max_rounds:
            self.round += 1
            content_buf = ""
            tool_calls_list = []

            stream = self.agent.llm.chat_stream(self.messages, tools=tools)
            content_buf = handler.process_stream(stream, tools=tools)
            tool_calls = handler.tool_call_buffer if handler.tool_call_buffer else None

            response = Message(role="assistant", content=content_buf, tool_calls=tool_calls)
            self.messages.append(response)

            if not response.tool_calls:
                self.final_response = response.content
                return response.content

            for tc in response.tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                t0 = time.time()
                if self.agent.config.tools_enabled:
                    from laap.permissions.enforcer import enforcer as perm_enforcer
                    perm_resource = {
                        "run_command": "shell:execute", "run_python": "code:execute",
                        "run_script": "shell:execute", "write_file": "file:write",
                        "edit_file": "file:write", "create_file": "file:write",
                        "delete_file": "file:delete", "git_commit": "git:commit",
                        "git_push": "git:push", "git_branch": "git:commit",
                        "web_fetch": "network:connect", "web_search": "network:connect",
                    }.get(func_name, "code:execute")
                    if not perm_enforcer.check(perm_resource, f"Tool: {func_name}"):
                        tool_result = json.dumps({"error": f"Permission denied: {func_name}"})
                    else:
                        tool_result = self.agent.call_tool(func_name, **args)
                else:
                    tool_result = self.agent.call_tool(func_name, **args)
                duration = time.time() - t0
                handler.process_tool_result(func_name, tool_result, duration)

                self.messages.append(Message.tool_result(
                    content=str(tool_result)[:100000],
                    tool_call_id=tc["id"], name=func_name,
                ))

        handler.finalize()

        if self.agent.session_manager and self.messages:
            sid = self.agent._current_session_id or self.agent.id
            try:
                self.agent.session_manager.save_messages(
                    sid, [m.to_dict() for m in self.messages]
                )
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        return self.final_response or "Max rounds reached"


# ════════════════════════════════════════════════════════════
# Agent 核心类 (v2.0 AGI)
# ════════════════════════════════════════════════════════════

class AGIBrain:
    """LAAP AGIBrain v3.0 — AGI-oriented base class with meta-cognition,
    parliament deliberation, attention control, and production capabilities.

    历史命名: 原名 `Agent`, 已重命名为 `AGIBrain` 以避免与
    `laap.agent_core.agent.Agent` (统一对外类) 冲突。

    当前定位: AGIBrain 作为 `Agent(mode="agi")` 的底层实现/兼容包装保留。
             新代码请直接使用统一入口:
                 from laap.agent_core.agent import Agent
                 agent = Agent(mode="agi")

    迁移指南:
        旧: from laap.agent.base import Agent
        新: from laap.agent_core.agent import Agent
                        agent = Agent(mode="agi")  # 自动包装 AGIBrain

    向后兼容: `Agent = AGIBrain` 别名保留在本文件末尾, 但会触发 DeprecationWarning。
    """

    DEFAULT_ACTOR_CAPABILITIES: List[str] = [
        "intent_parsing",
        "tool_execution",
        "reflection",
        "code_generation",
    ]

    def __init__(self, config: Optional[AgentConfig] = None,
                 llm_factory: Optional[LLMFactory] = None,
                 session_manager: Optional["SessionManager"] = None,
                 show_banner: Optional[bool] = None):
        self.id = str(uuid.uuid4())[:12]
        self.config = config or AgentConfig()
        self.alive = True
        self.step_count = 0
        self.birth_time = time.time()
        self._self_modifications = 0
        self._conversation: List[Message] = []
        self._show_banner = self.config.verbose if show_banner is None else show_banner

        # ── Actor composition (non-destructive) ──
        self._actor_cell = AgentCell(actor_id=self.id, host="local")
        self._aether_handlers: Dict[MessageType, Callable[[AetherMessage], Any]] = {}
        self._register_default_actor_capabilities()

        # ── AGI 增强组件 ──
        self.meta_cognition = MetaCognitionEngine(agent_id=self.id)
        self.parliament = Parliament(agent_id=self.id)
        self.attention = AttentionController()
        self._meta_reflection_counter = 0

        # ── AGI v3.0 Brain + Cortex + Unity (延迟导入避免循环) ──
        Brain_cls = _lazy_import("laap.cognition.brain", "Brain")
        ToolCortex_cls = _lazy_import("laap.tools.cortex", "ToolExecutionCortex")
        FirstPrin_cls = _lazy_import("laap.cognition.first_principles", "FirstPrinciplesEngine")
        Unity_cls = _lazy_import("laap.cognition.unity", "UnityEngine")
        
        self.brain = Brain_cls(agent_id=self.id, name=self.config.name)
        self.cortex = ToolCortex_cls(agent_id=self.id)
        self.first_principles = FirstPrin_cls()
        self.unity = Unity_cls(cortex=self.cortex, brain=self.brain)
        self._brain_initialized = True

        # Session persistence (optional)
        self.session_manager = session_manager
        self._current_session_id: Optional[str] = None

        # Tools
        self.tool_registry = ToolRegistry()

        # Legacy memory (hierarchical, in-memory)
        self.memory = HierarchicalMemory()
        self.memory.load()

        # Persistent memory system
        self.memory_manager = MemoryManager()
        try:
            builtin = BuiltinMemoryProvider()
            self.memory_manager.add_provider(builtin)
            self.memory_manager.initialize_all(
                session_id=self._current_session_id or self.id,
            )
            logger.info("Persistent memory initialized")
        except Exception as e:
            logger.warning(f"Persistent memory init failed: {e}")

        # Awareness
        self.awareness = AwarenessSystem(agent_id=self.id, name=self.config.name)

        # Plugin system
        self.plugins = PluginManager()

        # Register production tools
        self._init_tools()
        self.plugins.trigger("agent:ready", agent=self)

        # LLM
        self.llm_factory = llm_factory or LLMFactory()
        try:
            self.llm = self.llm_factory.get(
                name=self.config.llm_provider or None,
                model=self.config.llm_model or None,
            )
        except Exception:
            self.llm = None
            if self.config.verbose:
                logger.info(f"Agent [{self.id[:8]}] local-only mode")

        # Auto-restore previous session
        self._safe_load_session()

        if self._show_banner:
            logger.info(
                f"{C.GOLD}◆{C.RESET} {self.config.name} [{self.id[:8]}] "
                f"{self.tool_registry.count} tools | "
                f"Brain={self.config.enable_brain} "
                f"Cortex={self.config.enable_cortex} "
                f"FP={self.config.enable_first_principles}"
            )

    def _init_default_tools(self):
        if getattr(self, '_default_tools_registered', False):
            return
        self._default_tools_registered = True
        self.register_tool("apply_modification", self.apply_modification_tool,
                          "Apply config modification to self", stop_after=True)

    def _safe_load_session(self):
        if not self.session_manager:
            return
        try:
            states = self.session_manager.list_agent_states()
            if states:
                latest = states[-1]
                self.session_manager.load_agent_state(latest, self)
                self._current_session_id = latest
                if self.config.verbose:
                    logger.info(f"恢复会话: {latest}")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def _auto_save(self):
        self.plugins.trigger("agent:auto_save", agent=self)
        if self.session_manager:
            sid = self._current_session_id or self.id
            try:
                self.session_manager.save_agent_state(sid, self)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        self.memory.save()

    # ── Aether Actor integration ──

    def _register_default_actor_capabilities(self) -> None:
        """Advertise the default actor capabilities for this agent."""
        for name in self.DEFAULT_ACTOR_CAPABILITIES:
            self.register_actor_capability(
                Capability(name=name, confidence=0.8)
            )

    def register_actor_capability(self, capability: Capability) -> None:
        """Register a capability on the composed AgentCell."""
        self._actor_cell.register_capability(capability)

    @property
    def actor_address(self) -> AetherAddress:
        """Return the Aether address of the composed AgentCell."""
        return self._actor_cell.address

    def on_aether_message(
        self,
        msg_type: MessageType,
        handler: Callable[[AetherMessage], Any],
    ) -> None:
        """Subscribe a handler for a specific Aether message type.

        The handler may be synchronous or asynchronous. It is wrapped so that
        the underlying AgentCell receives an awaitable handler.
        """
        self._aether_handlers[msg_type] = handler

        async def _wrapper(msg: AetherMessage) -> None:
            if asyncio.iscoroutinefunction(handler):
                await handler(msg)
            else:
                handler(msg)

        self._actor_cell.on(msg_type, _wrapper)

    async def handle_aether_message(self, msg: AetherMessage) -> None:
        """Dispatch an Aether message to a previously subscribed handler."""
        handler = self._aether_handlers.get(msg.msg_type)
        if handler is None:
            logger.warning(
                f"[{self.id}] No Aether handler for {msg.msg_type}"
            )
            return
        if asyncio.iscoroutinefunction(handler):
            await handler(msg)
        else:
            handler(msg)

    def actor_status(self) -> dict:
        """Return actor-related status for introspection."""
        return {
            "actor_id": self._actor_cell.actor_id,
            "address": str(self._actor_cell.address),
            "state": self._actor_cell.state.name,
            "capabilities": [
                {"name": c.name, "confidence": c.confidence}
                for c in self._actor_cell.capabilities
            ],
            "metrics": dict(self._actor_cell.metrics),
        }

    def _init_tools(self):
        if getattr(self, '_tools_initialized', False):
            return
        self._tools_initialized = True
        self._init_default_tools()
        if self.config.tools_enabled:
            from laap.tools.code_edit import register_all as _register_code_tools
            from laap.tools.shell import register_all as _register_shell_tools
            from laap.tools.web import register_all as _register_web_tools
            from laap.tools.gui import register_all as _register_gui_tools
            from laap.tools.browser_auto import register_all as _register_browser_tools
            _register_code_tools(self.tool_registry)
            _register_shell_tools(self.tool_registry)
            _register_web_tools(self.tool_registry)
            _register_gui_tools(self.tool_registry)
            _register_browser_tools(self.tool_registry)
            # Agent-Reach integration (15+ internet platforms) — best-effort:
            # silently skipped if the agent_reach package is not installed.
            try:
                from laap.integrations.agent_reach import (
                    register_all as _register_reach_tools,
                )
                _register_reach_tools(self.tool_registry)
            except Exception as _e:
                logger.debug(f"Agent-Reach tools skipped: {_e}")

        # Sync tools to Cortex (v3.0)
        if self.config.enable_cortex:
            # lazily get cortex
            from laap.tools.cortex import ToolSpec as _ToolSpec
            for tool in self.tool_registry.list():
                if tool.handler:
                    self.cortex.register_handler(
                        name=tool.name,
                        handler=tool.handler,
                        description=tool.description,
                        category=tool.category,
                        parameters=tool.parameters,
                    )
            logger.info(f"Cortex synced: {len(self.cortex._tools)} tools from ToolRegistry")

    def register_tool(self, name: str, handler: Callable, description: str = "",
                      category: str = "custom", stop_after: bool = False):
        from laap.tools.base import infer_json_schema
        from inspect import signature, getdoc
        sig = signature(handler)
        hints = {}
        for pname, p in sig.parameters.items():
            if pname not in ("self", "cls", "agent", "fc"):
                hints[pname] = p.annotation if p.annotation != p.empty else str
        param_descriptions = {}
        doc = getdoc(handler)
        if doc:
            try:
                from docstring_parser import parse as doc_parse
                for p in (doc_parse(doc).params or []):
                    param_descriptions[p.arg_name] = p.description or ""
            except (ImportError, Exception):
                pass  # 可选模块，降级处理
        schema = infer_json_schema(hints, param_descriptions)
        tool = Tool(
            name=name, description=description,
            parameters={
                "type": "object",
                "properties": schema["properties"],
                "required": schema.get("required", []),
            },
            handler=handler, category=category,
        )
        self.tool_registry.register(tool)
        self.memory.register_skill(name, description)

    def call_tool(self, tool_name: str, **kwargs) -> Any:
        try:
            result = self.tool_registry.call(tool_name, **kwargs)
            self.memory.record_skill_result(tool_name, True)
            return result
        except Exception as e:
            self.memory.record_skill_result(tool_name, False)
            return json.dumps({"error": f"{type(e).__name__}: {str(e)[:200]}"})

    def get_tool_defs(self) -> List[ToolDef]:
        return [t.to_tool_def() for t in self.tool_registry.list() if t.handler]

    # ═══════════════════════════════════════════════════
    # 核心 chat 方法 (AGI v3.0 Brain 集成版)
    # ═══════════════════════════════════════════════════

    def chat(self, message: str, system_prompt: str = "",
             tools: Optional[List[ToolDef]] = None,
             max_rounds: Optional[int] = None,
             handler: Optional[StreamHandler] = None) -> str:
        if not self.alive:
            return "Agent is not alive."
        self.step_count += 1

        if self.awareness:
            self.awareness.record_event("chat", {"message": message[:60]})
        self.plugins.trigger("agent:will_chat", agent=self, message=message)

        brain_active = self.config.enable_brain
        cortex_active = self.config.enable_cortex
        fp_active = self.config.enable_first_principles

        # ── Phase 0: Brain 统一思考 (v3.0) ──
        if brain_active:
            thought = self.brain.think(
                message,
                use_first_principles=fp_active and len(message) > 80,
                use_parliament=self.config.enable_parliament and len(message) > 100,
            )
            brain_recommendation = {
                "selected_action": thought.selected_action,
                "confidence": thought.confidence,
                "reasoning": thought.reasoning_path[-3:],
                "emotional_context": thought.emotional_context,
            }
            logger.info(
                f"[Agent.chat] Brain思考完成: action={thought.selected_action[:20]} "
                f"conf={thought.confidence:.2f} ({thought.duration_ms:.0f}ms)"
            )
        else:
            thought = None
            brain_recommendation = {}

        # ── Phase 1: 元认知决策前分析 ──
        meta_active = self.config.enable_meta_cognition
        par_active = self.config.enable_parliament and not brain_active
        att_active = self.config.enable_attention

        if meta_active:
            meta_recommendations = self.meta_cognition.before_decision(
                message, {"tools_available": self.tool_registry.count}
            )
        else:
            meta_recommendations = {}

        # ── Phase 2: 注意力设置 ──
        if att_active:
            self.attention.set_focus(
                topic=message[:80],
                secondary=meta_recommendations.get("strategy_steps", []),
            )

        # ── Phase 3: 议会 (Brain未启用时回退) ──
        parliament_result = None
        if par_active and self.config.parliament_on_high_stakes:
            task_len = len(message)
            is_high_stakes = (
                task_len > 200 or
                any(kw in message.lower() for kw in [
                    "delete", "remove", "modify", "change config",
                    "删除", "修改", "危险", "风险",
                    "execute", "deploy", "publish", "commit",
                ])
            )
            if is_high_stakes:
                deliberation = self.parliament.deliberate(
                    topic=f"决策: {message[:100]}",
                    context=f"步骤计数={self.step_count}",
                    fast_mode=True,
                )
                parliament_result = deliberation.final_decision

        # ── Phase 4: 构建增强 System Prompt ──
        memory_context = self.memory_manager.prefetch_all(
            message, session_id=self._current_session_id or self.id,
        )
        enhanced_prompt = system_prompt or self.config.system_prompt

        # 注入 Brain 状态 (v3.0)
        if brain_active:
            brain_block = self.brain.get_brain_prompt_block()
            enhanced_prompt = f"{brain_block}\n\n{enhanced_prompt}"

        # 注入元认知提示
        if meta_active:
            meta_block = self.meta_cognition.get_reflection_prompt()
            enhanced_prompt = f"{meta_block}\n\n{enhanced_prompt}"

        # 注入注意力提示
        if att_active:
            att_block = self.attention.get_attention_prompt_block()
            enhanced_prompt = f"{att_block}\n\n{enhanced_prompt}"

        # 注入议会结果
        if parliament_result:
            enhanced_prompt = (
                f"[议会审议结果: {parliament_result}]\n\n{enhanced_prompt}"
            )

        # 注入 Brain 思考结果
        if brain_active and brain_recommendation.get("reasoning"):
            reasoning = "; ".join(brain_recommendation["reasoning"])
            enhanced_prompt = (
                f"[大脑思考路径: {reasoning}]\n\n{enhanced_prompt}"
            )

        # 注入第一性原理
        if fp_active and self.config.enable_brain:
            fp_block = self.first_principles.get_first_principles_prompt_block()
            enhanced_prompt = f"{fp_block}\n\n{enhanced_prompt}"

        # 注入记忆上下文
        if memory_context:
            enhanced_prompt = f"{enhanced_prompt}\n\n{memory_context}"

        # ── Phase 5: Memory管理 ──
        self.memory_manager.on_turn_start(self.step_count, message)

        # ── Phase 6: 构建工具定义 ──
        if cortex_active:
            # 使用 Cortex 获取工具 Schema
            all_tools_defs = []
            for spec_name in self.cortex.list_available():
                spec = self.cortex._tools.get(spec_name)
                if spec:
                    all_tools_defs.append(spec.to_tool_def())
        else:
            all_tools_defs = self.get_tool_defs()

        memory_tools_raw = self.memory_manager.get_all_tool_schemas()
        from laap.llm.provider import ToolDef
        memory_tools = []
        for raw in memory_tools_raw:
            if isinstance(raw, dict):
                fn_info = raw.get("function", raw)
                memory_tools.append(ToolDef(
                    name=fn_info.get("name", "unknown"),
                    description=fn_info.get("description", ""),
                    parameters=fn_info.get("parameters", {
                        "type": "object", "properties": {}, "required": [],
                    }),
                ))
            else:
                memory_tools.append(raw)
        all_tools = (tools or all_tools_defs) + memory_tools

        # ── Phase 7: 执行工具循环 ──
        loop = ToolCallLoop(
            self, max_rounds=max_rounds or self.config.max_tool_rounds
        )
        result = loop.run(
            user_input=message,
            system_prompt=enhanced_prompt,
            tools=all_tools,
            handler=handler,
            initial_messages=self._conversation or None,
        )

        # ── Phase 8: 保存对话历史 ──
        if loop.messages and len(loop.messages) > 1:
            self._conversation = loop.messages

        # ── Phase 9: 后处理 ──
        self.memory_manager.sync_all(
            message, result or "",
            session_id=self._current_session_id or self.id,
        )

        # Brain 从结果学习 (v3.0)
        if brain_active:
            self.brain.perceive(f"Chat完成: {result[:40] if result else 'empty'}")
            self.brain.learn_from_outcome(
                brain_recommendation.get("selected_action", "chat"),
                0.8 if result else 0.2,
            )

        # 元认知后处理
        if meta_active:
            self.meta_cognition.after_decision({
                "task": message[:60],
                "confidence": 0.6,
                "selected": result[:50] if result else "",
                "duration_ms": 0,
            }, outcome={"score": 0.7 if result else 0.0})

        # 定期元认知反思
        if meta_active:
            self._meta_reflection_counter += 1
            if self._meta_reflection_counter >= self.config.meta_cognition_interval:
                self.meta_cognition.perform_reflection()
                self._meta_reflection_counter = 0

        self.plugins.trigger("agent:did_chat", agent=self, result=result)
        self._auto_save()
        return result

    def run(self, task: str) -> str:
        self.step_count += 1
        if self.awareness:
            self.awareness.set_task(task)
        return self.chat(task)

    # ── AGI 高级接口 ──

    def deliberate(self, topic: str, context: str = "",
                   full: bool = False) -> Deliberation:
        """
        对某个议题进行议会审议 — 内部多视角决策

        Args:
            topic: 审议议题
            context: 背景信息
            full: 是否完整审议（全部角色参与）

        Returns:
            审议记录
        """
        return self.parliament.full_deliberate(topic, context)

    def reflect(self) -> Dict[str, Any]:
        """
        执行元认知反思 — 分析近期决策模式
        
        Returns:
            反思报告
        """
        if not self.config.enable_meta_cognition:
            return {"error": "Meta-cognition disabled"}
        return self.meta_cognition.perform_reflection()

    def introspect(self) -> str:
        """
        全面内省 — 返回Agent的自我认知状态
        
        包括：元认知状态、议会状态、注意力状态、Brain状态、Cortex状态、整体健康
        """
        parts = [
            "╔═══════════════════════════════════════════════════╗",
            "║        LAAP Agent v3.0 — 全面内省报告             ║",
            "╚═══════════════════════════════════════════════════╝",
            "",
            f"Agent ID: {self.id}",
            f"名称: {self.config.name}",
            f"状态: {'活跃' if self.alive else '已停止'}",
            f"步骤: {self.step_count}",
            f"存活时间: {self.age:.0f}s",
            f"自我修改: {self._self_modifications}",
            f"工具: {self.tool_registry.count}",
        ]

        # ── Brain 状态 (v3.0) ──
        if self.config.enable_brain:
            try:
                brain = self.brain
                parts.extend(["", "── 大脑 (Brain) ──"])
                parts.append(f"  思考周期: {brain._total_think_cycles}")
                parts.append(f"  决策次数: {brain._total_decisions}")
                parts.append(f"  皮层整合度: {brain.cortex.integration_level:.0%}")
                parts.append(f"  PFC激活: {brain.cortex.pfc_activation:.0%}")
                parts.append(f"  DMN(反思): {brain.cortex.dmn_activation:.0%}")
                parts.append(f"  注意力广度: {brain.cortex.attention_breadth:.0%}")
            except Exception:
                parts.append("  (不可用)")

        # ── Cortex 状态 (v3.0) ──
        if self.config.enable_cortex:
            try:
                stats = self.cortex.get_stats()
                parts.extend(["", "── 执行皮层 (Cortex) ──"])
                parts.append(f"  总调用: {stats['total_calls']}")
                parts.append(f"  成功率: {stats['success_rate']:.0%}")
                parts.append(f"  被阻止: {stats['blocked']}")
                parts.append(f"  注册工具: {stats['registered_tools']}")
                parts.append(f"  工具集: {stats['toolsets']}")
            except Exception:
                parts.append("  (不可用)")

        if self.config.enable_meta_cognition:
            parts.extend(["", "── 元认知 ──"])
            meta_status = self.meta_cognition.status()
            parts.append(f"  思考模式: {meta_status['mode']}")
            parts.append(f"  认知负载: {meta_status['load']}")
            parts.append(f"  自我效能: {meta_status['self_efficacy']}")
            parts.append(f"  偏差纠正: {meta_status['bias_corrections']}")

        if self.config.enable_parliament:
            parts.extend(["", "── 议会 ──"])
            par_status = self.parliament.status()
            parts.append(f"  议员: {par_status['members']}")
            parts.append(f"  总审议: {par_status['total_deliberations']}")
            parts.append(f"  共识率: {par_status['consensus_rate']:.0%}")

        if self.config.enable_attention:
            parts.extend(["", "── 注意力 ──"])
            att_status = self.attention.status()
            parts.append(f"  焦点: {att_status['focus']}")
            parts.append(f"  专注强度: {att_status['intensity']:.0%}")
            parts.append(f"  切换次数: {att_status['switches']}")

        parts.extend([
            "",
            "── LLM ──",
            f"  提供商: {self.config.llm_provider or 'auto'}",
            f"  模型: {self.config.llm_model or 'auto'}",
        ])

        return "\n".join(parts)

    # ── Session Persistence ──

    def save_session(self, session_id: Optional[str] = None) -> bool:
        if not self.session_manager:
            return False
        sid = session_id or self._current_session_id or self.id
        try:
            self.session_manager.save_agent_state(sid, self)
            self._current_session_id = sid
            return True
        except Exception as e:
            logger.warning(f"Session save failed: {e}")
            return False

    def load_session(self, session_id: str) -> bool:
        if not self.session_manager:
            return False
        try:
            ok = self.session_manager.load_agent_state(session_id, self)
            if ok:
                self._current_session_id = session_id
            return ok
        except Exception as e:
            logger.warning(f"Session load failed: {e}")
            return False

    def apply_modification(self, modification: Dict[str, Any]) -> bool:
        mod_type = modification.get("type")
        params = modification.get("params", {})
        try:
            if mod_type == "adjust_exploration":
                self.config.exploration_rate = max(
                    0.01, min(0.99, params.get("value", 0.2))
                )
            elif mod_type == "adjust_learning_rate":
                self.config.learning_rate = max(
                    0.001, min(0.5, params.get("value", 0.1))
                )
            else:
                logger.warning(f"Unknown mod type: {mod_type}")
                return False
            self._self_modifications += 1
            return True
        except Exception as e:
            logger.error(f"Modification failed: {e}")
            return False

    def apply_modification_tool(self, mod_type: str = "", params: str = "{}") -> str:
        if not mod_type:
            return "No modification type specified"
        try:
            p = json.loads(params) if isinstance(params, str) else params
            success = self.apply_modification({"type": mod_type, "params": p})
            return f"Modification {'succeeded' if success else 'failed'}"
        except Exception as e:
            return f"Error: {e}"

    def chat_stream(self, message: str):
        """Streaming chat — yields response text chunks."""
        if not self.llm:
            return
        result = self.chat(message)
        if result:
            yield result

    def die(self, reason: str = "unknown"):
        self.alive = False
        self.plugins.trigger("agent:die", agent=self, reason=reason)
        logger.warning(f"Agent [{self.id[:8]}] died: {reason}")
        if self.awareness:
            self.awareness.record_event("death", {"reason": reason})
        if getattr(self, "_actor_cell", None):
            self._actor_cell.stop()

    @property
    def age(self) -> float:
        return time.time() - self.birth_time

    def status(self) -> dict:
        s = {
            "id": self.id,
            "name": self.config.name,
            "alive": self.alive,
            "steps": self.step_count,
            "age_s": round(self.age, 1),
            "self_modifications": self._self_modifications,
            "tools": self.tool_registry.count,
            "memory": self.memory.to_dict(),
            "awareness": self.awareness.summary() if self.awareness else {},
        }

        # AGI 组件状态
        if self.config.enable_meta_cognition:
            s["meta_cognition"] = self.meta_cognition.status()
        if self.config.enable_parliament:
            s["parliament"] = self.parliament.status()
        if self.config.enable_attention:
            s["attention"] = self.attention.status()
        if self.config.enable_brain:
            try:
                s["brain"] = self.brain.status()
            except Exception:
                s["brain"] = {"error": "unavailable"}
        if self.config.enable_cortex:
            try:
                s["cortex"] = self.cortex.status()
            except Exception:
                s["cortex"] = {"error": "unavailable"}

        return s


# ══════════════════════════════════════════════════════════════════
# 向后兼容别名 — Agent = AGIBrain
# ══════════════════════════════════════════════════════════════════

def _deprecated_agent_alias(*args, **kwargs):
    """Agent 别名 — 触发 DeprecationWarning 并委托给 AGIBrain。

    迁移路径:
        旧: from laap.agent.base import Agent
        新: from laap.agent.base import AGIBrain
            或统一入口: from laap.agent_core.agent import Agent
    """
    import warnings
    warnings.warn(
        "laap.agent.base.Agent 已重命名为 AGIBrain。"
        "请改用 `from laap.agent.base import AGIBrain`，"
        "或使用统一入口 `from laap.agent_core.agent import Agent`。"
        "Agent(mode='agi') 会自动包装 AGIBrain。",
        DeprecationWarning,
        stacklevel=2,
    )
    return AGIBrain(*args, **kwargs)


# 保持 `isinstance(x, Agent)` 兼容: Agent 必须是类, 不能是函数
# 所以这里用 __getattr__ 模式 — 只在真正访问 `Agent` 时触发警告
class _AgentAliasMeta(type):
    """元类: 让 Agent 别名既是类又能在实例化时触发 DeprecationWarning。"""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        import warnings
        warnings.warn(
            "laap.agent.base.Agent 已重命名为 AGIBrain。"
            "请改用 `from laap.agent.base import AGIBrain`，"
            "或使用统一入口 `from laap.agent_core.agent import Agent`。"
            "Agent(mode='agi') 会自动包装 AGIBrain。",
            DeprecationWarning,
            stacklevel=2,
        )
        return super().__call__(*args, **kwargs)


class Agent(AGIBrain, metaclass=_AgentAliasMeta):
    """已弃用别名 — 请使用 AGIBrain 或 laap.agent_core.agent.Agent。

    此类仅作为 AGIBrain 的子类存在, 以保持 `isinstance(x, Agent)` 兼容。
    实例化时会触发 DeprecationWarning。
    """
    pass


# 显式声明 Agent 是 AGIBrain 的别名 (用于 from laap.agent.base import Agent)
__all_exported__ = ["AGIBrain", "Agent", "AgentConfig",
                   "ToolCallLoop", "AttentionController", "AttentionFocus"]
