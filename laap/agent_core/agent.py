"""LAAP Agent — 统一对外入口 (V5 内核级)

三套历史 Agent 实现的合并收敛点：
    - mode="kernel" (默认): 自包含 + HermesToolBridge (73 工具)
    - mode="hermes":  嵌入 Hermes AIAgent + LAAP 认知层 (吸收 laap_agent.py)
    - mode="agi":     包装 v3.0 AGI Brain (元认知 + 议会 + 注意力, 吸收 agent/base.py)

对外 API:
    from laap.agent_core.agent import Agent, AgentConfig
    agent = Agent(mode="kernel")              # 轻量自包含
    agent = Agent(mode="hermes", model="...")  # Hermes 全量集成
    agent = Agent(mode="agi")                  # AGI Brain 增强

向后兼容:
    LAAPAgent = Agent  (laap_agent.py 改为薄 shim)
    agent.base.Agent → AGIBrain (保留 Agent 别名 + DeprecationWarning)
"""
from __future__ import annotations
import os
import sys
import time
import json
import logging
import uuid
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from laap.agent_core.context import Context, Role, Message
from laap.agent_core.llm_provider import LLMFactory
from laap.agent_core.hermes_tool_bridge import HermesToolBridge, Tool
from laap.agent_core.planner import Planner
from laap.agent_core.executor import Executor
from laap.agent_core.memory_bridge import MemoryBridge
from laap.agent_core.context_compressor import ContextCompressor
from laap.agent_core.cron import CronScheduler
from laap.agent_core.background_review import BackgroundReviewer
from laap.agent_core.llm_adapters import AdapterRegistry
from laap.agent_core.plugins.hooks import HookRegistry, HookPoint
from laap.agent_core.platforms.manager import PlatformManager
from laap.agent_core.plugins.manager import PluginManager as _PluginManager

# optional cognitive autonomy protection
from laap.cognition.autonomy_protection import ResponseMode  # noqa: E402

logger = logging.getLogger("agent_core.agent")


class AgentState(str, Enum):
    IDLE = "idle"; THINKING = "thinking"; ACTING = "acting"
    OBSERVING = "observing"; DONE = "done"


class AgentMode(str, Enum):
    """Agent 后端模式选择。

    - kernel: 自包含轻量 Agent (默认, 使用 HermesToolBridge 注入 73 工具)
    - hermes: 嵌入 Hermes AIAgent + LAAP 认知层 (全量集成, 需 HERMES_HOME)
    - agi:    包装 v3.0 AGI Brain (元认知 + 议会 + 注意力, 无外部依赖)
    """
    KERNEL = "kernel"
    HERMES = "hermes"
    AGI = "agi"


@dataclass
class AgentConfig:
    name: str = "LAAP-Agent"
    version: str = "1.0.0"
    system_prompt: str = ""
    max_iterations: int = 20
    max_tokens: int = 128000
    temperature: float = 0.7
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    enable_memory: bool = True
    enable_tools: bool = True
    enable_planning: bool = True
    # AGI Brain 模式专用
    enable_meta_cognition: bool = True
    enable_parliament: bool = True
    enable_attention: bool = True
    enable_brain: bool = True
    enable_cortex: bool = True
    # 量子认知引擎 (kernel mode)
    enable_quantum_cognition: bool = True
    quantum_cognition_mode: str = "hybrid"
    enable_hallucination_guard: bool = True
    verbose: bool = False


DEFAULT_SYSTEM = "你是LAAP智能体。有记忆、有工具、可规划。请用中文回答。"


# ══════════════════════════════════════════════════════════════════
# 统一 Agent 类 (外观模式 + 模式选择)
# ══════════════════════════════════════════════════════════════════

class Agent:
    """LAAP 统一 Agent — 唯一对外类。

    通过 `mode` 参数选择后端实现：
        mode="kernel" (默认): 自包含, 使用 HermesToolBridge, 支持依赖注入
        mode="hermes":        嵌入 Hermes AIAgent, 挂载 LAAP 认知层 + 握手协议
        mode="agi":           包装 v3.0 AGI Brain, 元认知 + 议会 + 注意力

    所有模式暴露统一 API: chat / stream_chat / execute_tool / get_status。
    高级模式 (hermes/agi) 额外暴露底层对象 (agent.hermes_agent / agent.agi_brain)。
    """

    def __init__(self,
                 config: Optional[AgentConfig] = None,
                 *,
                 mode: str = "kernel",
                 # kernel 模式参数 (依赖注入)
                 llm: Any = None,
                 memory_manager: Any = None,
                 tool_manager: Any = None,
                 agent_id: Optional[str] = None,
                 system_prompt: Optional[str] = None,
                 # hermes 模式参数
                 model: str = "",
                 provider: str = "",
                 enabled_toolsets: Optional[List[str]] = None,
                 disabled_toolsets: Optional[List[str]] = None,
                 quiet_mode: bool = True,
                 platform: str = "cli",
                 session_id: str = "",
                 # 透传给底层 AIAgent / AGIBrain
                 **kwargs):
        """创建统一 Agent。

        Args:
            config: AgentConfig (可选, 与显式参数二选一)
            mode: 后端模式 "kernel" | "hermes" | "agi"
            llm: kernel 模式下注入 LLM 实例 (测试用)
            memory_manager: kernel 模式下注入 MemoryManager
            tool_manager: kernel 模式下注入 ToolManager
            agent_id: 显式 agent ID
            system_prompt: 显式系统提示
            model: hermes 模式下的 LLM 模型名
            provider: hermes 模式下的 LLM 提供商
            enabled_toolsets: hermes 模式下启用的工具集
            disabled_toolsets: hermes 模式下禁用的工具集
            quiet_mode: hermes 模式是否静默
            platform: hermes 模式平台 (cli/telegram/discord 等)
            session_id: 显式会话 ID
            **kwargs: 透传给底层 AIAgent / AGIBrain
        """
        self.config = config or AgentConfig()
        self.mode = AgentMode(mode)
        self._agent_id = agent_id or ("sess_" + uuid.uuid4().hex[:8])
        self.system_prompt = system_prompt or self.config.system_prompt or DEFAULT_SYSTEM

        # 根据模式分发到对应后端
        if self.mode == AgentMode.KERNEL:
            self._init_kernel(
                llm=llm, memory_manager=memory_manager,
                tool_manager=tool_manager, agent_id=agent_id,
                system_prompt=system_prompt,
            )
        elif self.mode == AgentMode.HERMES:
            self._init_hermes(
                model=model, provider=provider,
                enabled_toolsets=enabled_toolsets,
                disabled_toolsets=disabled_toolsets,
                quiet_mode=quiet_mode, platform=platform,
                session_id=session_id, **kwargs,
            )
        elif self.mode == AgentMode.AGI:
            self._init_agi(**kwargs)
        else:
            raise ValueError(
                f"Unknown agent mode: {mode!r}. "
                f"Expected one of: kernel, hermes, agi"
            )

        # ── OpenForge RL 训练管道 (可选) ─────────────────────────
        self._init_training()

    # ── kernel 模式初始化 (原 agent_core/agent.py Agent) ──────────

    def _init_training(self) -> None:
        """可选: 初始化训练数据采集管道 (OpenForge RL 集成)。

        如果 AgentConfig.training 存在且 enabled=True,
        自动调用 integrate_training() 挂载 agent.training。
        不修改 agent 主逻辑, 只在尾部添加一个可选钩子。
        """
        training_config = getattr(self.config, 'training', None)
        if training_config and training_config.enabled:
            try:
                from laap.training.integration import (
                    integrate_training, TrainingConfig,
                )
                from dataclasses import asdict
                # 确保 training 是 TrainingConfig 实例
                if isinstance(training_config, dict):
                    self.config.training = TrainingConfig(
                        **training_config
                    )
                # 将 config.training 转为 dict 传给 integrate_training
                training_dict = {
                    k: v for k, v in asdict(training_config).items()
                    if not k.startswith('_')
                }
                integrate_training(
                    self, config_dict=training_dict
                )
                logger.info(
                    f"Training pipeline auto-initialized for "
                    f"{self._agent_id}"
                )
            except ImportError:
                logger.debug(
                    "laap.training not available, "
                    "skipping training integration"
                )
            except Exception as e:
                logger.warning(
                    f"Training integration init failed: {e}"
                )

    def _init_kernel(self, *, llm, memory_manager, tool_manager,
                     agent_id, system_prompt):
        """自包含轻量 Agent — 统一 ToolManager + 多 backend 路由。

        V2 改进:
          - 使用统一 ToolManager (唯一入口) 替代直接用 HermesToolBridge
          - 通过 register_all_backends() 依次注册 Hermes + agent_core/tools + laap/tools
          - 如注入了 tool_manager (测试用), 直接使用不再注册 backend
        """
        self.state = AgentState.IDLE

        # 依赖注入支持 (用于测试)
        self._injected_llm = llm
        self._injected_memory = memory_manager
        self._injected_tool_manager = tool_manager

        if tool_manager is not None:
            # 测试模式: 使用注入的 tool_manager (可能是 mock)
            self.tool_mgr = tool_manager
        else:
            # 生产模式: 统一 ToolManager + 多 backend 路由
            from laap.agent_core.tool_manager import ToolManager
            self.tool_mgr = ToolManager()
            try:
                self._backend_status = self.tool_mgr.register_all_backends(
                    include_hermes=True,
                    include_agent_core=True,
                    include_laap_tools=True,
                    include_mcp=False,  # 默认关闭, 依赖 npx/uvx
                )
            except Exception as e:
                logger.warning(f"Agent kernel: backend 注册失败 ({e}), 使用空 ToolManager")
                self._backend_status = {"error": str(e)}

        self.context = Context(max_tokens=self.config.max_tokens)
        self.memory_manager = memory_manager
        if memory_manager is not None:
            self.memory = memory_manager
        elif self.config.enable_memory and llm is not None:
            # When llm is injected (test mode), don't create MemoryBridge
            self.memory = None
        elif self.config.enable_memory:
            self.memory = MemoryBridge()
            self.memory_manager = self.memory
        else:
            self.memory = None

        if llm is not None:
            self.llm = llm
        else:
            # V2: 使用统一 laap.llm 入口 (旧版 LLMFactory.create 仍兼容)
            try:
                from laap.llm.factory import factory as _llm_factory
                self.llm = _llm_factory.get(
                    model=self.config.llm_model,
                    temperature=self.config.temperature,
                )
            except Exception:
                # fallback 到旧版 LLMFactory.create (shim 兼容)
                self.llm = LLMFactory.create(
                    self.config.llm_provider, self.config.llm_model,
                    temperature=self.config.temperature,
                )

        self.context.set_system(self.system_prompt)
        self._session_id = self._agent_id
        self._stats = {"total_turns": 0, "total_tool_calls": 0}
        self.running = True
        self.max_tokens = self.config.max_tokens
        self.temperature = self.config.temperature

        self.plugin_mgr = None
        self.cron = CronScheduler()
        self.cron.start()

        # Register LAAP-specific memory tools on top of Hermes tools
        self._add_memory_tools()

        # ── 量子认知引擎 (kernel 模式) ──────────────────────────
        if self.config.enable_quantum_cognition:
            try:
                from laap.agent_core.quantum_cognition.psi_quantum import (
                    PsiQuantumCognition, QuantumCognitionConfig,
                )
                from laap.agent_core.quantum_cognition.hallucination_guard import (
                    HallucinationGuard, GuardConfig,
                )
                from laap.agent_core.quantum_cognition.cognition_monitor import (
                    CognitionMonitor,
                )
                qc_cfg = QuantumCognitionConfig(
                    mode=self.config.quantum_cognition_mode,
                    dim_state=8,
                    enable_spectral=True,
                    enable_kalman=True,
                    enable_schrodinger=True,
                    enable_bayesian=True,
                    enable_occam=True,
                    verbose_logging=False,
                )
                self.quantum_cognition = PsiQuantumCognition(qc_cfg)
                if self.config.enable_hallucination_guard:
                    self.hallucination_guard = HallucinationGuard(GuardConfig())
                else:
                    self.hallucination_guard = None
                # 数据采集 (默认启用)
                self.cognition_monitor = CognitionMonitor()
                logger.info(
                    f"Agent [kernel]: quantum cognition active "
                    f"(mode={self.config.quantum_cognition_mode})"
                )
            except Exception as exc:
                logger.warning(
                    f"Agent [kernel]: quantum cognition init failed: {exc}"
                )
                self.quantum_cognition = None
                self.hallucination_guard = None
                self.cognition_monitor = None
        else:
            self.quantum_cognition = None
            self.hallucination_guard = None
            self.cognition_monitor = None

        tool_count = len(self.tool_mgr.list_tools())
        logger.info(
            f"Agent ready [kernel]: {self.config.name} "
            f"({tool_count} tools from Hermes engine)"
        )

    def _add_memory_tools(self):
        """注册 LAAP 特有的记忆工具到 tool_mgr。"""
        if not getattr(self, "memory", None):
            return
        self.tool_mgr.register(Tool(
            "remember", "记住信息",
            {"type": "object",
             "properties": {"fact": {"type": "string"},
                            "importance": {"type": "number"}},
             "required": ["fact"]},
            handler=lambda fact, imp=0.5: self.memory.remember_fact(fact, imp),
            category="memory",
        ))
        self.tool_mgr.register(Tool(
            "recall", "回忆信息",
            {"type": "object",
             "properties": {"query": {"type": "string"}},
             "required": ["query"]},
            handler=lambda q: json.dumps(
                self.memory.search_memory(q), ensure_ascii=False),
            category="memory",
        ))

    # ── hermes 模式初始化 (吸收 laap_agent.py LAAPAgent) ───────────

    def _init_hermes(self, *, model, provider, enabled_toolsets,
                     disabled_toolsets, quiet_mode, platform,
                     session_id, **kwargs):
        """嵌入 Hermes AIAgent + LAAP 认知层 + 握手协议。

        原实现: laap/agent_core/laap_agent.py LAAPAgent
        改进: 移除硬编码路径, 改用环境变量 HERMES_HOME / LAAP_HOME
        """
        self.state = AgentState.IDLE

        # 1. 通过 laap.config.paths 定位 Hermes (不再硬编码)
        from laap.config.paths import get_hermes_root, get_laap_root

        hermes_root = get_hermes_root()
        hermes_home = str(hermes_root) if hermes_root is not None else ""
        laap_home = str(get_laap_root())

        if not hermes_home:
            logger.warning(
                "Agent [hermes]: HERMES_ROOT not set and no Hermes installation found. "
                "Set HERMES_ROOT environment variable to enable Hermes mode."
            )

        # 把路径加入 sys.path (与原 laap_agent.py 行为一致)
        for p in [hermes_home, laap_home]:
            if p and p not in sys.path:
                sys.path.insert(0, p)
        laap_brain_path = os.path.join(laap_home, "laap_brain")
        if os.path.isdir(laap_brain_path) and laap_brain_path not in sys.path:
            sys.path.insert(0, laap_brain_path)

        # 2. 安装 LAAP 认知层 (monkey-patch AIAgent)
        try:
            from laap_brain.integrate import install_laap
            install_laap()
        except Exception as e:
            logger.warning(
                f"Agent [hermes]: install_laap failed ({e}). "
                f"Falling back to plain Hermes AIAgent."
            )

        # 3. 创建 Hermes AIAgent (受 install_laap 增强)
        try:
            from run_agent import AIAgent
        except ImportError as e:
            raise RuntimeError(
                f"Agent mode='hermes' requires Hermes AIAgent. "
                f"Set HERMES_HOME env var or install Hermes. (import error: {e})"
            ) from e

        # 从 kwargs 中弹出已显式处理的参数，避免冲突
        for key in ('model', 'provider', 'enabled_toolsets', 'disabled_toolsets',
                    'quiet_mode', 'platform', 'session_id', 'skip_context_files'):
            kwargs.pop(key, None)

        self._hermes_agent = AIAgent(
            model=model,
            provider=provider,
            enabled_toolsets=enabled_toolsets or ["hermes-cli"],
            disabled_toolsets=disabled_toolsets or [],
            quiet_mode=quiet_mode,
            platform=platform,
            session_id=session_id,
            skip_context_files=True,
            **kwargs,
        )

        # 4. 握手协议 + 认知层
        self._handshake = None
        try:
            from laap.handshake import HandshakeProtocol
            self._handshake = HandshakeProtocol.get_instance()
        except Exception as e:
            logger.debug(f"Agent [hermes]: handshake init failed: {e}")

        self._brain = getattr(self._hermes_agent, 'laap_brain', None)
        if self._brain:
            logger.info("Agent [hermes]: cognitive layer active")
        else:
            logger.warning(
                "Agent [hermes]: no cognitive layer "
                "(install_laap might have failed)"
            )

        # kernel 模式兼容字段
        self.context = None  # hermes 模式用 Hermes 的 context
        self.memory = None
        self.memory_manager = None
        self.tool_mgr = None  # hermes 模式用 Hermes 的 registry
        self.llm = None
        self._stats = {"total_turns": 0, "total_tool_calls": 0}
        self.running = True
        self._created_at = time.time()
        self._call_count = 0

        logger.info(
            f"Agent ready [hermes]: {self.config.name} "
            f"(model={model or 'default'}, brain={'on' if self._brain else 'off'})"
        )

    # ── agi 模式初始化 (吸收 agent/base.py Agent v3.0) ─────────────

    def _init_agi(self, **kwargs):
        """包装 v3.0 AGI Brain — 元认知 + 议会 + 注意力。

        原实现: laap/agent/base.py Agent (v3.0)
        保留原类为 AGIBrain, 这里通过组合委托。
        """
        self.state = AgentState.IDLE

        try:
            from laap.agent.base import AGIBrain, AgentConfig as _AGIConfig
        except ImportError as e:
            raise RuntimeError(
                f"Agent mode='agi' requires laap.agent.base.AGIBrain. "
                f"(import error: {e})"
            ) from e

        # 把统一 AgentConfig 转换为 AGI 专用 config
        agi_config = _AGIConfig(
            name=self.config.name,
            llm_provider=self.config.llm_provider,
            llm_model=self.config.llm_model,
            system_prompt=self.system_prompt,
            tools_enabled=self.config.enable_tools,
            verbose=self.config.verbose,
            enable_meta_cognition=self.config.enable_meta_cognition,
            enable_parliament=self.config.enable_parliament,
            enable_attention=self.config.enable_attention,
            enable_brain=self.config.enable_brain,
            enable_cortex=self.config.enable_cortex,
        )

        # 透传 llm_factory / session_manager / show_banner (如果提供)
        self._agi_brain = AGIBrain(config=agi_config, **kwargs)

        # kernel 模式兼容字段 (委托给 AGIBrain)
        self.context = None
        self.memory = getattr(self._agi_brain, 'memory', None)
        self.memory_manager = getattr(self._agi_brain, 'memory_manager', None)
        self.tool_mgr = getattr(self._agi_brain, 'tool_registry', None)
        self.llm = getattr(self._agi_brain, 'llm', None)
        self._stats = {"total_turns": 0, "total_tool_calls": 0}
        self.running = True

        logger.info(
            f"Agent ready [agi]: {self.config.name} "
            f"(meta={self.config.enable_meta_cognition}, "
            f"parliament={self.config.enable_parliament})"
        )

    # ════════════════════════════════════════════════════════════════
    # 统一对外 API — 所有模式都支持
    # ════════════════════════════════════════════════════════════════

    def chat(self, message: str) -> str:
        """同步对话 — 返回回复文本。"""
        self._stats["total_turns"] = self._stats.get("total_turns", 0) + 1
        self.state = AgentState.THINKING

        # optional cognitive autonomy protection
        autonomy_guidance = ""
        if getattr(self, "autonomy_filter", None) is not None:
            try:
                assessment = self.autonomy_filter.assess(
                    message, context={"recent_answer_ratio": 0.5}
                )
                if assessment.recommended_mode != ResponseMode.ANSWER_MODE and assessment.suggested_prompts:
                    autonomy_guidance = "\n".join(assessment.suggested_prompts[:2])
            except Exception:
                autonomy_guidance = ""

        if self.mode == AgentMode.KERNEL:
            response = self._kernel_chat(message, autonomy_guidance=autonomy_guidance)
            self.state = AgentState.DONE
            return response
        elif self.mode == AgentMode.HERMES:
            self._call_count = getattr(self, '_call_count', 0) + 1
            resp = self._hermes_agent.chat(message)
            self.state = AgentState.DONE
            return resp
        elif self.mode == AgentMode.AGI:
            resp = self._agi_brain.chat(message)
            self.state = AgentState.DONE
            return resp
        return "(空响应)"

    def run(self, task: str) -> str:
        """执行任务 — agi 模式委托给 AGIBrain, kernel 模式使用 chat 兜底。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.run(task)
        return self.chat(task)

    def status(self) -> dict:
        """AGI 模式状态 — 委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.status()
        return self.get_status()

    def introspect(self) -> str:
        """AGI 模式内省 — 委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.introspect()
        return "Introspection only available in agi mode."

    def reflect(self) -> dict:
        """AGI 模式元认知反思 — 委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.reflect()
        return {"error": "Reflection only available in agi mode."}

    def deliberate(self, topic: str, context: str = "", full: bool = False):
        """AGI 模式议会审议 — 委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.deliberate(topic, context, full=full)
        raise NotImplementedError("Deliberation only available in agi mode.")

    def register_tool(self, name: str, handler: Callable, description: str = "",
                      category: str = "custom", stop_after: bool = False):
        """注册工具 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.register_tool(
                name, handler, description=description,
                category=category, stop_after=stop_after,
            )
        raise NotImplementedError("Tool registration only available in agi mode.")

    def call_tool(self, name: str, **kwargs) -> Any:
        """调用工具 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.call_tool(name, **kwargs)
        return self.execute_tool(name, kwargs)

    def save_session(self, session_id: Optional[str] = None) -> bool:
        """保存会话 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.save_session(session_id)
        return False

    def load_session(self, session_id: str) -> bool:
        """加载会话 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.load_session(session_id)
        return False

    def apply_modification(self, modification: dict) -> bool:
        """应用自我修改 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.apply_modification(modification)
        raise NotImplementedError("Modification only available in agi mode.")

    def apply_modification_tool(self, mod_type: str = "", params: str = "{}") -> str:
        """工具形式的自我修改 — agi 模式委托给 AGIBrain。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.apply_modification_tool(mod_type, params)
        raise NotImplementedError("Modification tool only available in agi mode.")

    # ── AGI 模式 Aether Actor 集成 ─────────────────────────────────

    @property
    def actor_address(self):
        """agi 模式: 返回底层 AGIBrain 的 Aether 地址。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.actor_address
        return None

    def register_actor_capability(self, capability):
        """agi 模式: 注册 Aether 能力。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.register_actor_capability(capability)
        raise NotImplementedError("Actor capabilities only available in agi mode.")

    def on_aether_message(self, msg_type, handler):
        """agi 模式: 订阅 Aether 消息。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.on_aether_message(msg_type, handler)
        raise NotImplementedError("Aether messages only available in agi mode.")

    def handle_aether_message(self, msg):
        """agi 模式: 处理 Aether 消息。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.handle_aether_message(msg)
        raise NotImplementedError("Aether messages only available in agi mode.")

    def actor_status(self) -> dict:
        """agi 模式: 返回 Actor 相关状态。"""
        if self.mode == AgentMode.AGI:
            return self._agi_brain.actor_status()
        return {}

    def _kernel_chat(self, message: str, *, autonomy_guidance: str = "") -> str:
        """kernel 模式的 chat 实现 (保留原 agent_core/agent.py 逻辑)。

        集成量子认知引擎的三层防幻觉：
          1. pre-gate: 置信度/不确定性检测 → 拒绝或生成
          2. in-generation: temperature/top_p 调制
          3. post-validation: 文本一致性验证
        """
        self.context.add(Role.USER, message)
        t0 = time.time()

        # ── 量子认知引擎感知 ──
        qc_decision = None
        mod_params = None

        if hasattr(self, 'quantum_cognition') and self.quantum_cognition is not None:
            qc = self.quantum_cognition
            # 感知输入
            qc.decide(message)

            if hasattr(self, 'hallucination_guard') and self.hallucination_guard is not None:
                guard = self.hallucination_guard
                stats = qc.get_stats()

                # 1. Pre-generation gate
                qc_decision = guard.pre_gate(stats)
                if qc_decision.action == 'reject':
                    self.context.add(Role.ASSISTANT, qc_decision.safe_response)
                    self.state = AgentState.DONE
                    qc.learn(f"rejected (low confidence)", success=False)
                    return qc_decision.safe_response

                # 2. In-generation parameter modulation
                mod_params = guard.modulate_params(stats)

        # ── LLM 生成 ──
        # Build H-QKV cognitive context prefix
        hqkv_prefix = ''
        if hasattr(self, 'quantum_cognition') and self.quantum_cognition is not None \
           and hasattr(self, 'hallucination_guard') and self.hallucination_guard is not None:
            try:
                from laap.agent_core.quantum_cognition.hqkv_bridge import H_QKVBuilder
                builder = getattr(self, '_hqkv_builder', None)
                if builder is None:
                    builder = H_QKVBuilder()
                    self._hqkv_builder = builder
                stats = self.quantum_cognition.get_stats()
                hqkv_prefix = builder.build_cognitive_prefix(stats)
                # Save modulated params
                mod_params = self.hallucination_guard.modulate_params(stats)
            except Exception as exc:
                logger.debug(f"H-QKV prefix build failed: {exc}")
                hqkv_prefix = ''

        # Build messages with optional H-QKV prefix
        messages = self.context.get_messages()
        if hqkv_prefix:
            # Inject as a system-level instruction (not replacing original system)
            sys_msg = next((m for m in messages if hasattr(m, 'role') and m.role == 'system'), None)
            if sys_msg and hasattr(sys_msg, 'content'):
                sys_msg.content = sys_msg.content + '\n' + hqkv_prefix
        if autonomy_guidance:
            self.context.add(
                Role.SYSTEM,
                '[Cognitive Autonomy Protection]\n' + autonomy_guidance,
            )
        try:
            if hasattr(self.llm, 'generate') and callable(self.llm.generate):
                response = self.llm.generate(self.context.get_messages())
                if hasattr(response, '__await__'):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            response = asyncio.run_coroutine_threadsafe(
                                response, loop
                            ).result(timeout=10)
                        else:
                            response = asyncio.run(response)
                    except RuntimeError:
                        response = asyncio.run(response)
            else:
                from laap.agent_core.llm_provider import LLMResponse
                resp = self.llm.chat(self.context.get_messages())
                response = resp.content
        except Exception:
            from laap.agent_core.llm_provider import LLMResponse
            resp = self.llm.chat(self.context.get_messages())
            response = resp.content

        response = response or "(空响应)"

        # ── 3. Post-generation validation ──
        qc_validate = None
        if hasattr(self, 'quantum_cognition') and self.quantum_cognition is not None \
           and hasattr(self, 'hallucination_guard') and self.hallucination_guard is not None:
            stats = self.quantum_cognition.get_stats()
            qc_validate = self.hallucination_guard.validate(
                response, message, stats
            )
            if qc_validate.needs_caveat:
                response = qc_validate.annotated_response
            # 学习反馈
            self.quantum_cognition.learn(
                f"generated response ({len(response)} chars)",
                success=qc_validate.is_valid,
            )

        self.context.add(Role.ASSISTANT, response)
        self.state = AgentState.DONE
        if self.memory:
            self.memory.remember_interaction(message, response or "")

        # ── 数据采集 ──
        if hasattr(self, 'cognition_monitor') and self.cognition_monitor is not None:
            try:
                mon = self.cognition_monitor
                qs = self.quantum_cognition.get_stats() if hasattr(self, 'quantum_cognition') and self.quantum_cognition is not None else None
                timing = {'total_ms': round((time.time() - t0) * 1000, 1)} if 't0' in dir() else None
                tokens = None
                if hasattr(self.context, '_token_counts') and self.context._token_counts:
                    tokens = {'input_tokens': sum(self.context._token_counts) if self.context._token_counts else 0}
                if response:
                    tokens = tokens or {}
                    tokens['output_tokens'] = len(response.split())
                hqkv_tokens = len(hqkv_prefix.split()) if hqkv_prefix else 0
                gen_params = None
                if mod_params is not None:
                    gen_params = {
                        'temperature': getattr(mod_params, 'temperature', 0.7),
                        'top_p': getattr(mod_params, 'top_p', 0.9),
                        'hqkv_prefix_tokens': hqkv_tokens,
                    }
                gd = None
                if qc_decision is not None:
                    gd = {'action': qc_decision.action, 'reason': qc_decision.reason}
                vr = None
                if qc_validate is not None:
                    vr = {
                        'is_valid': qc_validate.is_valid,
                        'needs_caveat': qc_validate.needs_caveat,
                        'issues': qc_validate.issues,
                    }
                mon.log_turn(
                    quantum_stats=qs,
                    guard_decision=gd,
                    validation_result=vr,
                    generation_params=gen_params,
                    timing=timing,
                    tokens=tokens,
                    success=True,
                )
            except Exception as exc:
                logger.debug(f"[monitor] log failed: {exc}")

        return response

    def stream_chat(self, message: str, *, autonomy_guidance: str = ""):
        """流式对话 — 逐 chunk 返回。

        kernel 模式: yield ("status"/"token"/"done"/"error", payload)
        hermes 模式: 透传 Hermes stream_chat
        agi 模式:    透传 AGIBrain.chat_stream
        """
        if self.mode == AgentMode.KERNEL:
            yield from self._kernel_stream_chat(message, autonomy_guidance=autonomy_guidance)
        elif self.mode == AgentMode.HERMES:
            for chunk in self._hermes_agent.stream_chat(message):
                yield chunk
        elif self.mode == AgentMode.AGI:
            yield from self._agi_brain.chat_stream(message)

    def _kernel_stream_chat(self, message: str, *, autonomy_guidance: str = ""):
        """kernel 模式流式 (保留原 agent_core/agent.py 逻辑)。"""
        self.context.add(Role.USER, message)
        if autonomy_guidance:
            self.context.add(
                Role.SYSTEM,
                '[Cognitive Autonomy Protection]\n' + autonomy_guidance,
            )
        yield ("status", "thinking")
        full = ""
        try:
            for token in self.llm.stream_chat(self.context.get_messages()):
                full += token
                yield ("token", token)
            self.context.add(Role.ASSISTANT, full)
            if self.memory:
                self.memory.remember_interaction(message, full)
            yield ("done", full)
        except Exception as e:
            yield ("error", str(e))

    # chat_stream 别名 (兼容 tests/test_agent_core.py)
    def chat_stream(self, message: str, *, autonomy_guidance: str = ""):
        """Streaming chat — yields response text chunks (kernel 模式兼容)。"""
        if self.mode == AgentMode.KERNEL:
            result = self.chat(message)
            if result:
                yield result
        else:
            yield from self.stream_chat(message, autonomy_guidance=autonomy_guidance)

    def execute_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        """执行工具 — 统一接口。"""
        self._stats["total_tool_calls"] = self._stats.get(
            "total_tool_calls", 0) + 1

        if self.mode == AgentMode.KERNEL:
            return self.tool_mgr.execute_tool(name, arguments or {})
        elif self.mode == AgentMode.HERMES:
            from tools.registry import registry
            result = registry.dispatch(name, arguments or {})
            if isinstance(result, str) and result.startswith("{"):
                try:
                    return json.loads(result)
                except Exception:
                    pass
            return result
        elif self.mode == AgentMode.AGI:
            return self._agi_brain.call_tool(name, **(arguments or {}))

    def list_tools(self) -> List[str]:
        """列出所有可用工具名。"""
        if self.mode == AgentMode.KERNEL:
            return self.tool_mgr.list_tools()
        elif self.mode == AgentMode.HERMES:
            try:
                from tools.registry import registry
                return registry.get_all_tool_names()
            except Exception:
                return []
        elif self.mode == AgentMode.AGI:
            try:
                return [t.name for t in self.tool_registry.list()]
            except Exception:
                return []
        return []

    # ── 状态 / 统计 ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """统一状态接口。"""
        base = {
            "agent_id": self._agent_id,
            "mode": self.mode.value,
            "running": self.running,
            "state": self.state.value,
            "total_turns": self._stats.get("total_turns", 0),
            "total_tool_calls": self._stats.get("total_tool_calls", 0),
        }
        if self.mode == AgentMode.KERNEL:
            base["tools"] = len(self.tool_mgr.list_tools())
        elif self.mode == AgentMode.HERMES:
            base["tools"] = len(self.list_tools())
            base["model"] = getattr(self._hermes_agent, 'model', '')
            base["provider"] = getattr(self._hermes_agent, 'provider', '')
            base["session_id"] = getattr(self._hermes_agent, 'session_id', '')
            if self._brain:
                base["cognitive"] = True
        elif self.mode == AgentMode.AGI:
            base["tools"] = self.tool_registry.count if self.tool_registry else 0
            base["meta_cognition"] = self.config.enable_meta_cognition
            base["parliament"] = self.config.enable_parliament
        return base

    def get_stats(self) -> dict:
        """详细统计 (kernel 模式兼容)。"""
        if self.mode == AgentMode.KERNEL:
            return dict(
                self._stats, state=self.state.value,
                context_tokens=self.context.total_tokens() if self.context else 0,
                tools=len(self.tool_mgr.list_tools()),
                memory=self.memory.get_stats() if self.memory else {},
            )
        return self.get_status()

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "name": self.config.name,
            "mode": self.mode.value,
            "state": self.state.value,
            "stats": self.get_stats(),
        }

    # ── 控制接口 ──────────────────────────────────────────────────

    def stop(self):
        self.running = False
        if self.mode == AgentMode.AGI:
            self._agi_brain.alive = False

    def reset(self):
        """重置 Agent 状态。"""
        self.state = AgentState.IDLE
        self.running = True
        if self.mode == AgentMode.KERNEL and self.context:
            self.context.clear()

    def set_llm_provider(self, new_llm):
        """切换 LLM 提供商。"""
        self.llm = new_llm
        if self.mode == AgentMode.AGI:
            self._agi_brain.llm = new_llm

    def set_autonomy_filter(self, filter_obj: Any) -> None:
        """Attach an optional cognitive autonomy protection filter.

        When set, ``chat()`` will assess open-ended queries before
        generation and may inject thinking-inviting guidance.
        """
        self.autonomy_filter = filter_obj

    def init_plugins(self):
        """初始化插件管理器 (kernel 模式)。"""
        if self.mode != AgentMode.KERNEL:
            return None
        if self.plugin_mgr is None:
            self.plugin_mgr = _PluginManager()
            self.plugin_mgr.init_plugins(agent=self)
        return self.plugin_mgr

    # ── 高级访问 (模式专属) ───────────────────────────────────────

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def hermes_agent(self):
        """hermes 模式: 底层 Hermes AIAgent 实例。"""
        if self.mode != AgentMode.HERMES:
            raise AttributeError(
                "hermes_agent only available in mode='hermes'"
            )
        return self._hermes_agent

    @property
    def agi_brain(self):
        """agi 模式: 底层 AGIBrain 实例。"""
        if self.mode != AgentMode.AGI:
            raise AttributeError(
                "agi_brain only available in mode='agi'"
            )
        return self._agi_brain

    @property
    def brain(self):
        """hermes 模式: LAAP 认知层 (LaapBrain)。"""
        if self.mode == AgentMode.HERMES:
            return self._brain
        elif self.mode == AgentMode.AGI:
            return getattr(self._agi_brain, 'brain', None)
        return None

    @property
    def handshake(self):
        """hermes 模式: 握手协议实例。"""
        if self.mode == AgentMode.HERMES:
            return self._handshake
        return None

    def cognitive_status(self) -> dict:
        """认知层状态 (hermes 模式 + kernel 量子引擎)。"""
        # hermes 模式
        if self.mode == AgentMode.HERMES and self._brain:
            brain = self._brain
            status = {"active": True}
            if hasattr(brain, 'current_mode'):
                status["mode"] = getattr(brain, 'current_mode', 'unknown')
            if hasattr(brain, '_total_turns'):
                status["turns"] = getattr(brain, '_total_turns', 0)
            if hasattr(brain, '_total_tools'):
                status["tool_calls"] = getattr(brain, '_total_tools', 0)
            if hasattr(brain, 'bias_corrections'):
                status["bias_corrections"] = getattr(brain, 'bias_corrections', 0)
            if hasattr(brain, 'skills'):
                status["skills"] = len(getattr(brain, 'skills', {}))
            return status

        # kernel 模式: 量子认知引擎
        if hasattr(self, 'quantum_cognition') and self.quantum_cognition is not None:
            stats = self.quantum_cognition.get_stats()
            status = {"active": True, "mode": "quantum"}
            status.update(stats)
            if hasattr(self, 'hallucination_guard') and self.hallucination_guard is not None:
                status["guard"] = self.hallucination_guard.get_stats()
            return status

        return {"active": False, "mode": self.mode.value}
        return status

    # ── 平台处理 (kernel 模式兼容) ───────────────────────────────

    def _platform_handler(self, event):
        """平台事件处理 (kernel 模式)。"""
        HookRegistry.trigger(HookPoint.BEFORE_CHAT, event.text)
        resp = self.chat(event.text)
        HookRegistry.trigger(HookPoint.AFTER_CHAT, resp)
        return resp

    # ── 内核工具调用 (kernel 模式兼容) ───────────────────────────

    def _exec_tool(self, msg: str):
        """关键词匹配工具调用 (kernel 模式 Hermes 73 工具后备)。"""
        if self.mode != AgentMode.KERNEL:
            return None
        m = msg.lower()
        tool_names = self.tool_mgr.list_tools()
        for name in tool_names:
            if name.lower() in m:
                if name == "web_search":
                    return self.tool_mgr.call(name, {"query": msg})
                elif name == "read_file":
                    return self.tool_mgr.call(name, {"path": ".", "limit": 50})
                elif name == "memory" or name == "remember":
                    return self.tool_mgr.call(name, {"fact": msg, "target": "memory"})
                elif name == "session_search":
                    return self.tool_mgr.call(name, {"query": msg})
                elif name == "execute_code":
                    return self.tool_mgr.call(name, {"code": msg})
                elif name == "vision_analyze":
                    return self.tool_mgr.call(name, {"image": msg})
                elif name in ("system_info", "think"):
                    return self.tool_mgr.call(name, {"thought": f"process: {msg[:200]}"})
                return self.tool_mgr.call(name, {})

        keyword_map = [
            (["时间", "几点了", "time"], "think", {"thought": f"user asked about time: {msg[:100]}"}),
            (["搜索", "search", "查找"], "web_search", {"query": msg}),
            (["读文件", "读取", "read"], "read_file", {"path": "."}),
            (["写文件", "创建"], "write_file", {"content": msg}),
            (["记忆", "记住", "记得"], "memory", {"fact": msg, "target": "memory"}),
            (["回忆", "recall"], "session_search", {"query": msg}),
            (["代码", "执行", "python"], "execute_code", {"code": msg}),
            (["系统", "信息", "status"], "system_info", {"category": "all"}),
            (["终端", "shell", "命令", "run"], "terminal", {"command": msg}),
            (["浏览", "浏览器", "打开"], "browser_navigate", {"url": msg}),
            (["图片", "看图", "vision"], "vision_analyze", {"image": msg}),
        ]
        for kws, name, args in keyword_map:
            if any(k in m for k in kws):
                return self.tool_mgr.call(name, args)
        return self.tool_mgr.call("think", {"thought": "process: " + msg[:200]})

    def __repr__(self):
        return (
            f"<Agent {self.config.name} [{self.mode.value}] "
            f"tools={len(self.list_tools())}>"
        )


# ══════════════════════════════════════════════════════════════════
# 向后兼容别名
# ══════════════════════════════════════════════════════════════════

# 历史代码用 LAAPAgent 名称 (来自 laap_agent.py), 现统一为 Agent
LAAPAgent = Agent
