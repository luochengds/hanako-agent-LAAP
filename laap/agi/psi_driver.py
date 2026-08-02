"""
LAAP AGI — PSI Driver (PSI认知驱动引擎)

Implements the PSI theory (Dietrich Dörner) cognition cycle:
  1. Perceive  — sensory input → internal representation (WorldModel)
  2. Select   — needs/emotion/bias → what to attend to (ConsciousStream/Attention)
  3. Integrate — bind perceptions + memories + predictions into unified experience
  4. Act      — generate response based on integrated state (LLM as I/O, not as thinker)
  5. Learn    — update world model, self model, skills from outcomes

The LLM becomes just the natural language I/O channel within this cycle,
NOT the cognitive driver. This module is OPT-IN (use_psi=False by default)
and NEVER breaks existing functionality.

Integration:
    from laap.agi.psi_driver import PSIDriver, integrate_psi_driver

    # Attach to agent
    driver = integrate_psi_driver(agent, llm_channel=my_llm_fn)

    # Use via process_interaction(use_psi=True)
    result = agent.process_interaction("Hello", use_psi=True)
"""

from __future__ import annotations

import logging
import threading

from typing import Any, Dict, List, Optional, Tuple
import time, logging
from collections import Counter
from laap.agi.world_model import EntityType
from laap.agi.directional_mesh import DirectionalMeshOrchestrator

logger = logging.getLogger("laap.agi.psi_driver")


class KakeyaCoverageMonitor:
    """
    Kakeya 认知方向覆盖度监控器 (P0)

    基于挂谷猜想的方向覆盖完备性原理：
    要确保认知系统在所有"方向"（需求类型/认知模式）上都有均匀覆盖，
    避免长期偏向某一种需求方向导致的认知偏食。

    核心机制：
      - 维护最近 N 个 PSI 周期的方向采样历史
      - 每次新周期记录当前访问的 (domain, focus, emotion_quadrant)
      - 周期性评估各方向轴的覆盖率，计算与均匀分布的差距
      - 当某个方向覆盖率低于阈值时，产生覆盖度偏置信号
      - 偏置信号在 _build_context 中注入，间接引导注意力分配
    """

    def __init__(self, window_size: int = 20, gap_threshold: float = 0.3):
        self.window_size = window_size
        self.gap_threshold = gap_threshold
        self.history: List[Dict[str, Any]] = []
        self._gap_warnings: List[str] = []

    def record_cycle(self, domain: str, focus: str = "respond",
                     valence: float = 0.0, arousal: float = 0.0) -> Dict[str, float]:
        """记录一个 PSI 周期访问的认知方向。

        Args:
            domain: 当前领域标签 (general, technical, emotional, ...)
            focus: 注意焦点 (respond, ask, reflect, analyze, ...)
            valence: 情感效价 (-1~1)
            arousal: 情感唤醒度 (0~1)

        Returns:
            方向覆盖度缺口字典 {轴: 缺口值}
        """
        # 情感象限：将连续的情感空间离散化为 4 个方向
        if valence >= 0 and arousal >= 0.3:
            emotion_quad = "Q1_pos_high"
        elif valence < 0 and arousal >= 0.3:
            emotion_quad = "Q2_neg_high"
        elif valence < 0 and arousal < 0.3:
            emotion_quad = "Q3_neg_low"
        else:
            emotion_quad = "Q4_pos_low"

        direction = {
            "domain": domain,
            "focus": focus,
            "emotion_quadrant": emotion_quad,
            "timestamp": time.time(),
        }
        self.history.append(direction)

        # 保持窗口大小
        if len(self.history) > self.window_size:
            self.history = self.history[-self.window_size:]

        self._gap_warnings = self._compute_warnings()
        return self._compute_coverage_gaps()

    def _compute_coverage_gaps(self) -> Dict[str, float]:
        """计算各方向轴的覆盖度与均匀分布的差距。

        对每个方向轴 (domain / focus / emotion_quadrant)：
          如果该轴上有 N 个不同值，均匀覆盖的期望频率 = 1/N
          gap = max(0, 期望频率 - 实际频率)
        仅返回 gap > gap_threshold 的缺口。
        """
        if not self.history or len(self.history) < 3:
            return {}

        total = len(self.history)

        # 各轴的值集合
        domains = set(d["domain"] for d in self.history)
        focuses = set(d["focus"] for d in self.history)
        quadrants = set(d["emotion_quadrant"] for d in self.history)

        # 各值的出现频率
        domain_counts = Counter(d["domain"] for d in self.history)
        focus_counts = Counter(d["focus"] for d in self.history)
        quadrant_counts = Counter(d["emotion_quadrant"] for d in self.history)

        gaps = {}

        for axis, values, counts in [
            ("domain", domains, domain_counts),
            ("focus", focuses, focus_counts),
            ("quadrant", quadrants, quadrant_counts),
        ]:
            if len(values) <= 1:
                continue  # 只有一个值，无障碍
            expected = 1.0 / len(values)
            for v in values:
                coverage = counts.get(v, 0) / total
                gap = max(0.0, expected - coverage)
                if gap > self.gap_threshold:
                    gaps[f"{axis}:{v}"] = round(gap, 3)

        return gaps

    def get_attention_bias(self) -> Dict[str, float]:
        """根据覆盖度缺口生成注意力偏置信号。

        Returns:
            {方向标识: 偏置强度 0~1}
        """
        gaps = self._compute_coverage_gaps()
        if not gaps:
            return {}

        bias = {}
        for key, gap in gaps.items():
            boost = min(1.0, gap * 2.0)  # gap 0.3 → boost 0.6
            if key.startswith("domain:"):
                bias[key] = boost
            elif key.startswith("focus:"):
                bias[key] = boost
            elif key.startswith("quadrant:"):
                bias[key] = boost * 0.5  # 情感象限偏置权重减半
        return bias

    def get_warnings(self) -> List[str]:
        """获取当前覆盖度缺口警告（最多 3 条）。"""
        return self._gap_warnings[:3]

    def _compute_warnings(self) -> List[str]:
        gaps = self._compute_coverage_gaps()
        warnings = []
        seen = set()
        for key in sorted(gaps.keys(), key=lambda k: gaps[k], reverse=True):
            canonical = key.split(":", 1)[1] if ":" in key else key
            if canonical not in seen:
                warnings.append(f"[KakeyaCov] {key} gap={gaps[key]:.2f}")
                seen.add(canonical)
            if len(warnings) >= 3:
                break
        return warnings

    def stats(self) -> Dict[str, Any]:
        """监控器统计信息。"""
        gaps = self._compute_coverage_gaps()
        return {
            "enabled": True,
            "window_size": self.window_size,
            "gap_threshold": self.gap_threshold,
            "history_length": len(self.history),
            "coverage_gaps": gaps,
            "domain_distribution": dict(Counter(d["domain"] for d in self.history)),
            "focus_distribution": dict(Counter(d["focus"] for d in self.history)),
            "quadrant_distribution": dict(Counter(d["emotion_quadrant"] for d in self.history)),
        }


class PSIDriver:
    """
    PSI-driven cognitive engine. Replaces LLM-as-thinker loop.

    Flow per interaction:
      1. perceive()   → WorldModel.add_entity() + ConsciousStream.experience()
      2. select()     → needs assessment → attention focus
      3. integrate()  → bind context → generate unified state
      4. decide()     → select action based on integrated state
      5. learn()      → update self-model + memory + learning pipeline

    The LLM is called only in step 4 (decide) for natural language generation,
    and is a sub-processor, not the driver.
    """

    def __init__(self, agent: Any, llm_channel: Optional[callable] = None,
                 enable_causal_verification: bool = False,
                 enable_kakeya_monitor: bool = True,
                 enable_mesh: bool = True):
        self.agent = agent            # AGIAgent instance
        self.llm = llm_channel        # LLM I/O channel (sub-processor)
        self.cycle_count = 0
        self.last_domain = "general"
        self._last_focus = "respond"
        # P1-5: 启用真正的因果一致性校验(从 LLM 响应抽取因果声明,
        # 调 causal_engine 查询是否与已学因果键/规则一致)
        self.enable_causal_verification = enable_causal_verification
        self._causal_violations: List[Dict[str, Any]] = []
        # P0: Kakeya 覆盖度监控器
        self.enable_kakeya_monitor = enable_kakeya_monitor
        self._kakeya = KakeyaCoverageMonitor() if enable_kakeya_monitor else None
        # Mesh: 方向性代理网格编排器
        self.enable_mesh = enable_mesh
        self._mesh: Optional[DirectionalMeshOrchestrator] = None
        self._mesh_initialized = False

    def process_interaction(self, user_input: str, domain: str = "general",
                            context: Optional[Dict[str, Any]] = None,
                            action_outcome: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the canonical six-stage PSI transaction exactly once."""
        lock = getattr(self.agent, "_psi_driver_lock", None)
        if lock is None:
            lock = threading.RLock()
            self.agent._psi_driver_lock = lock
        with lock:
            if getattr(self.agent, "_psi_driver_active", False):
                raise RuntimeError("PSIDriver re-entry detected; duplicate PSI cycle blocked")
            self.agent._psi_driver_active = True
            try:
                result = self.agent._process_interaction_core(
                    user_input,
                    domain=domain,
                    context=context,
                    action_outcome=action_outcome,
                    use_psi=True,
                )
            finally:
                self.agent._psi_driver_active = False
        self.cycle_count = getattr(self.agent, "total_interactions", self.cycle_count)
        self.last_domain = domain
        result["psi_driver"] = {
            "canonical": True,
            "cycle": self.cycle_count,
            "phases": ["perceive", "select", "integrate", "act", "learn", "close"],
            "implementation": "AGIAgent CognitiveBus core",
        }
        return result

    def process(self, user_input: str, domain: str = "general") -> str:
        """Compatibility string API backed by the canonical transaction."""
        result = self.process_interaction(user_input, domain=domain)
        return str(result.get("response", ""))

    def _legacy_process(self, user_input: str, domain: str = "general") -> str:
        """
        Legacy standalone PSI implementation retained only for migration comparison.

        Args:
            user_input: The user's natural language input
            domain: Task domain label

        Returns:
            Natural language response string
        """
        # ═══════════════════════════════════════════════════════════
        # Step 1: Perceive
        # ═══════════════════════════════════════════════════════════
        self.last_domain = domain

        if hasattr(self.agent, 'world') and self.agent.world:
            self.agent.world.add_entity(
                name=f"user_input_{self.cycle_count}",
                entity_type=EntityType.ACTION,
                properties={"content": user_input, "domain": domain},
            )

        if hasattr(self.agent, 'conscious') and self.agent.conscious:
            self.agent.conscious.experience(user_input)

        # ─── Causal analysis: learn from message, predict interventions ───
        causal_context = ""
        if hasattr(self.agent, 'causal') and self.agent.causal:
            try:
                # P0-2: 原 causal.observe/add_variable/_find_var/add_edge 方法
                # 在 UnifiedCausalEngine 中均不存在,改为使用真实 API:
                # learn_bond / learn_temporal_link / learn_entity_state
                causal = self.agent.causal
                words = user_input.lower().split()[:5]
                keywords = [w for w in words if len(w) > 3 and w.isalpha()]

                if keywords:
                    # 把每个关键词作为实体状态注入(entity_states)
                    for w in keywords:
                        try:
                            causal.learn_entity_state(
                                entity_id=w,
                                state={"value": 1.0, "domain": domain, "source": "user_input"},
                            )
                        except Exception:
                            # learn_entity_state 可能签名不同,降级为直接写 entity_states
                            causal.entity_states[w] = {
                                "value": 1.0, "domain": domain, "ts": self.cycle_count,
                            }

                    # 关键词之间建立因果键(前一个词 → 后一个词)
                    # learn_bond 签名: (action, target, effect, matched: bool, domain)
                    for i in range(len(keywords) - 1):
                        cause_w, effect_w = keywords[i], keywords[i + 1]
                        try:
                            causal.learn_bond(
                                action=cause_w,
                                target=effect_w,
                                effect=f"{cause_w} 引发 {effect_w}",
                                matched=True,
                                domain=domain,
                            )
                        except Exception as e:
                            logger.debug(f"learn_bond 失败: {e}")

                    # 建立时间因果链(同一序列内)
                    for i in range(len(keywords) - 1):
                        cause_w, effect_w = keywords[i], keywords[i + 1]
                        try:
                            causal.learn_temporal_link(
                                cause=cause_w,
                                effect=effect_w,
                                delay=1.0,
                                confidence=0.35,
                            )
                        except Exception as e:
                            logger.debug(f"learn_temporal_link 失败: {e}")

                cs = causal.stats()
                # UnifiedCausalEngine.stats() 返回 causal_bonds / temporal_links 等
                n_vars = cs.get("entity_states", 0)
                n_bonds = cs.get("causal_bonds", 0)
                if n_vars > 0 or n_bonds > 0:
                    causal_context = (
                        f"[Causal: {n_vars} vars, {n_bonds} bonds, "
                        f"{cs.get('temporal_links', 0)} temporal]"
                    )
            except Exception as e:
                causal_context = f"[Causal: {e}]"

        # ─── Analogical transfer: find cross-domain patterns ───
        analogy_context = ""
        if hasattr(self.agent, 'analogical') and self.agent.analogical:
            try:
                domain_data = {"domain": domain, "user_input": user_input[:200]}
                self.agent.analogical.encode_domain(domain, [domain_data])
                analogies = self.agent.analogical.query_analogies(domain)
                if analogies:
                    analogy_str = "; ".join([f"{a[0]}(conf={a[1]:.2f})" for a in analogies[:3]])
                    analogy_context = f"[Analogies: {analogy_str}]"
                if len(analogies) >= 2:
                    mapping = self.agent.analogical.find_analogy(domain)
                    if mapping and mapping.similarity_score > 0.3:
                        analogy_context += f" [Mapping: {mapping.source_domain}->{mapping.target_domain}, sim={mapping.similarity_score:.2f}]"
            except Exception as e:
                analogy_context = f"[Analogies: {e}]"

        # ─── P0: Kakeya coverage monitoring ───
        kakeya_context = ""
        if self._kakeya and hasattr(self.agent, 'conscious') and self.agent.conscious:
            try:
                cs = self.agent.conscious.stats()
                gaps = self._kakeya.record_cycle(
                    domain=domain,
                    focus=self._last_focus,
                    valence=cs.get('valence', 0),
                    arousal=cs.get('arousal', 0.5),
                )
                if gaps:
                    warnings = self._kakeya.get_warnings()
                    if warnings:
                        kakeya_context = " [CoverageGaps] " + " ".join(warnings)
            except Exception as e:
                logger.debug(f"Kakeya monitor failed: {e}")

        # ═══════════════════════════════════════════════════════════
        # Step 2: Selection (needs/emotion drive attention)
        # ═══════════════════════════════════════════════════════════
        focus = "respond"
        if hasattr(self.agent, 'conscious') and hasattr(
            self.agent.conscious, 'attention'
        ):
            attn = self.agent.conscious.attention
            if hasattr(attn, 'determine_focus'):
                try:
                    raw_focus = attn.determine_focus({"user_input": user_input})
                    focus = raw_focus.value if hasattr(raw_focus, 'value') else str(raw_focus)
                except Exception:
                    focus = "respond"

        self._last_focus = focus

        # ─── Step 2.5: Directional Agent Mesh 编排 ───
        mesh_context = ""
        if self._mesh:
            try:
                # 无 agent_refs 时懒初始化
                if not self._mesh_initialized:
                    agent_refs = {}
                    for key in ["causal", "memory", "world", "self_model",
                                "conscious", "meta", "learning"]:
                        if hasattr(self.agent, key) and getattr(self.agent, key):
                            agent_refs[key] = getattr(self.agent, key)
                    if agent_refs:
                        self._mesh.build_default_mesh(agent_refs)
                        self._mesh_initialized = True
                        logger.info(f"[PSI] Mesh initialized with {len(agent_refs)} modules")

                if self._mesh_initialized:
                    # 收集 Kakeya 偏置信号 → 传给 Mesh
                    kakeya_bias = None
                    if self._kakeya:
                        bias = self._kakeya.get_attention_bias()
                        kakeya_bias = bias if bias else None

                    # 构建任务描述：domain + user_input
                    task_desc = f"{domain}: {user_input[:200]}"

                    resolution = self._mesh.resolve_task(
                        task_description=task_desc,
                        top_k=3,
                        external_bias=kakeya_bias,
                    )

                    activated = resolution.get("activated", [])
                    if activated:
                        labels = [a["label"] for a in activated]
                        mesh_context = f"[Mesh] 激活: {' + '.join(labels)}"
            except Exception as e:
                logger.debug(f"[PSI] Mesh 编排失败: {e}")

        # ═══════════════════════════════════════════════════════════
        # Step 3: Integration
        # ═══════════════════════════════════════════════════════════
        context = self._build_context(domain=domain, focus=focus,
                                     causal_context=causal_context,
                                     analogy_context=analogy_context,
                                     kakeya_context=kakeya_context,
                                     mesh_context=mesh_context)

        # ═══════════════════════════════════════════════════════════
        # Step 4: Action (LLM as sub-processor)
        # ═══════════════════════════════════════════════════════════
        if self.llm:
            response = self.llm(context + "\n\nUser: " + user_input)
        else:
            response = self._fallback_respond(domain)

        # ─── Causal consistency verification ───
        response = self._causal_verify(response)

        # ═══════════════════════════════════════════════════════════
        # Step 5: Learning
        # ═══════════════════════════════════════════════════════════
        self._learn(user_input, response, domain)

        self.cycle_count += 1
        return response

    # ═══════════════════════════════════════════════════════════
    # Latency instrumentation (E1)
    # ═══════════════════════════════════════════════════════════
    #
    # Bottleneck analysis of process() hot path:
    #   • Causal analysis (L89-152): O(n_keywords) writes to the causal
    #     engine — learn_entity_state / learn_bond / learn_temporal_link
    #     are each called per-keyword-pair, plus a stats() query. Each
    #     call may trigger index updates and is wrapped in try/except
    #     (exception machinery adds overhead under failure).
    #   • Analogical transfer (L154-169): encode_domain + query_analogies
    #     + find_analogy may run embedding lookups / similarity sweeps;
    #     query_analogies is called every cycle even when no analogies
    #     exist (no early-exit).
    #   • _build_context calls .stats() on up to four subsystems
    #     (conscious / self_model / world / memory_system) — each stats()
    #     may aggregate over large state.
    #   • Kakeya monitor (new): lightweight Counter update, negligible cost
    #
    # measure_latency() does NOT modify process(). It temporarily wraps
    # the callable entry points of each step with timers, runs one cycle,
    # and restores the originals. perceive is derived by subtraction
    # (it overlaps with several inline agent calls that cannot be
    # wrapped without duplicating process()).

    def measure_latency(
        self, user_input: str = "measure", domain: str = "general"
    ) -> Dict[str, float]:
        """Time each step of one PSI cognition cycle.

        Wraps the callable entry points of perceive/select/integrate/
        decide/learn with timers, runs one ``process()`` cycle, and
        returns per-step latencies in milliseconds.

        Args:
            user_input: Input to feed into ``process()``.
            domain: Domain label passed to ``process()``.

        Returns:
            Dict with keys ``perceive_ms``, ``select_ms``,
            ``integrate_ms``, ``decide_ms``, ``learn_ms``,
            ``total_ms``. ``perceive_ms`` is computed by subtraction
            from the total.
        """
        import time as _time

        timings: Dict[str, float] = {
            "perceive_ms": 0.0,
            "select_ms": 0.0,
            "integrate_ms": 0.0,
            "decide_ms": 0.0,
            "learn_ms": 0.0,
            "total_ms": 0.0,
        }

        def _wrap(step: str, func: callable) -> callable:
            def _timed(*args, **kwargs):
                t0 = _time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    timings[f"{step}_ms"] += (_time.perf_counter() - t0) * 1000.0
            return _timed

        # Save originals of self-owned callables.
        orig = {
            "_build_context": self._build_context,
            "_causal_verify": self._causal_verify,
            "_learn": self._learn,
            "_fallback_respond": self._fallback_respond,
            "llm": self.llm,
        }

        self._build_context = _wrap("integrate", orig["_build_context"])
        self._causal_verify = _wrap("decide", orig["_causal_verify"])
        self._learn = _wrap("learn", orig["_learn"])
        self._fallback_respond = _wrap("decide", orig["_fallback_respond"])
        if self.llm is not None:
            self.llm = _wrap("decide", orig["llm"])

        # Wrap select step (agent.conscious.attention.determine_focus).
        orig_attn = None
        agent = self.agent
        if (
            hasattr(agent, "conscious")
            and agent.conscious
            and hasattr(agent.conscious, "attention")
            and hasattr(agent.conscious.attention, "determine_focus")
        ):
            orig_attn = agent.conscious.attention.determine_focus
            agent.conscious.attention.determine_focus = _wrap("select", orig_attn)

        try:
            t0 = _time.perf_counter()
            self.process(user_input, domain=domain)
            timings["total_ms"] = (_time.perf_counter() - t0) * 1000.0
        finally:
            # Restore originals.
            self._build_context = orig["_build_context"]
            self._causal_verify = orig["_causal_verify"]
            self._learn = orig["_learn"]
            self._fallback_respond = orig["_fallback_respond"]
            self.llm = orig["llm"]
            if orig_attn is not None:
                agent.conscious.attention.determine_focus = orig_attn

        # perceive = total − (select + integrate + decide + learn).
        # Clamp to >= 0 in case of timer jitter.
        perceive = (
            timings["total_ms"]
            - timings["select_ms"]
            - timings["integrate_ms"]
            - timings["decide_ms"]
            - timings["learn_ms"]
        )
        timings["perceive_ms"] = perceive if perceive > 0.0 else 0.0
        return timings

    def _build_context(self, domain: str, focus: str = "respond",
                       causal_context: str = "", analogy_context: str = "",
                       kakeya_context: str = "", mesh_context: str = "") -> str:
        """Build attention-weighted context from all cognitive modules.

        Args:
            kakeya_context: P0 coverage gap warnings injected by Kakeya monitor
            mesh_context: Directional Agent Mesh 激活状态信息
        """
        tiers = {"high": [], "medium": [], "low": []}

        # High tier: conscious state + focus
        if hasattr(self.agent, 'conscious') and self.agent.conscious:
            try:
                cs = self.agent.conscious.stats()
                tiers["high"].append(f"[Conscious: focus={focus}, valence={cs.get('valence', 0):.2f}]")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        if hasattr(self.agent, 'self_model') and self.agent.self_model:
            try:
                sm = self.agent.self_model.stats()
                tiers["high"].append(f"[Self: {sm.get('total_experiences', 0)} exp, {sm.get('skills', 0)} skills]")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        if causal_context:
            tiers["medium"].append(causal_context)
        if analogy_context:
            tiers["medium"].append(analogy_context)
        if kakeya_context:
            tiers["medium"].append(kakeya_context)  # P0: Kakeya 覆盖度缺口
        if mesh_context:
            tiers["medium"].append(mesh_context)    # Directional Agent Mesh 激活状态

        if hasattr(self.agent, 'world') and self.agent.world:
            try:
                wm = f"[World: {len(self.agent.world.entities)} entities, {len(self.agent.world.relations)} relations]"
                tiers["medium"].append(wm)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        if hasattr(self.agent, 'memory_system') and self.agent.memory_system:
            try:
                ms = self.agent.memory_system.stats()
                tiers["low"].append(f"[Memory: {ms.get('total_memories', 0)} episodes]")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        if hasattr(self.agent, 'learning') and self.agent.learning:
            try:
                tiers["low"].append("[Learning: ready]")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        parts = []
        for tier_name in ["high", "medium", "low"]:
            if tiers[tier_name]:
                parts.append(f"[{tier_name.upper()} PRIORITY]")
                parts.extend(tiers[tier_name])

        return chr(10).join(parts) if parts else "[Cognitive context: initializing]"

    def learn(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility learning hook for tool/task integrations."""
        data = payload if isinstance(payload, dict) else {"input": str(payload)}
        self._learn(
            str(data.get("input", data.get("user_input", ""))),
            str(data.get("response", "")),
            str(data.get("domain", "general")),
        )
        return {"learned": True, "canonical": True}

    def _learn(self, user_input: str, response: str, domain: str):
        """Post-interaction learning across all modules."""
        # Self-model learning
        if (
            hasattr(self.agent, 'self_model')
            and self.agent.self_model
            and hasattr(self.agent.self_model, 'record_experience')
        ):
            try:
                self.agent.self_model.record_experience(
                    domain=domain,
                    outcome_score=0.5,
                    predicted_confidence=0.5,
                    is_success=True,
                    description=f"PSI cycle {self.cycle_count}: {user_input[:60]}",
                )
            except Exception as e:
                logger.debug(f"Self-model learn skipped: {e}")

        # Memory system
        if hasattr(self.agent, 'memory_system') and self.agent.memory_system:
            try:
                self.agent.memory_system.remember_episode(
                    event=user_input,
                    context={"response": response, "domain": domain},
                )
            except Exception as e:
                logger.debug(f"Memory learn skipped: {e}")

        # Learning pipeline
        if hasattr(self.agent, 'learning') and self.agent.learning:
            try:
                self.agent.learning.learn(
                    domain=domain,
                    action=user_input[:80],
                    outcome=0.5,
                )
            except Exception as e:
                logger.debug(f"Learning pipeline learn skipped: {e}")

    def _causal_verify(self, response: str) -> str:
        """P1-5: 真正的因果一致性校验。

        从 LLM 响应中抽取 "X causes/affects/leads to Y" 等因果声明,
        调用 UnifiedCausalEngine 查询已学因果键/规则,若声明与已知因果
        矛盾(反向或不存在),在响应末尾追加警告标注。

        Args:
            response: LLM 生成的原始响应

        Returns:
            校验后的响应(可能追加 [Causal Warning] 标注)
        """
        if not self.enable_causal_verification:
            return response
        if not hasattr(self.agent, 'causal') or not self.agent.causal:
            return response
        try:
            import re as _re
            causal = self.agent.causal
            cs = causal.stats()
            # 至少需要 2 个因果键才有校验意义
            if cs.get("causal_bonds", 0) < 2 and cs.get("temporal_links", 0) < 2:
                return response

            # 抽取因果声明:支持 "X causes Y" / "X affects Y" / "X leads to Y"
            # / "X 导致 Y" / "X 引起 Y" / "X 影响 Y"
            patterns = [
                r'(\w+)\s+(?:causes?|affects?|leads?\s+to|triggers?)\s+(\w+)',
                r'(\w+)\s+(?:导致|引起|影响|引发)\s+(\w+)',
            ]
            claims = []
            for pat in patterns:
                claims.extend(_re.findall(pat, response.lower()))

            if not claims:
                return response

            # 已知因果键集合(从 bonds 与 temporal_links 提取)
            known_forward = set()  # (cause, effect)
            known_reverse = set()  # (effect, cause) — 反向
            for bond_key in getattr(causal, 'bonds', {}).keys():
                # bond_key 格式: "action→target:effect"
                try:
                    pair = bond_key.split(':', 1)[0]
                    if '→' in pair:
                        c, e = pair.split('→', 1)
                        known_forward.add((c, e))
                        known_reverse.add((e, c))
                except Exception:
                    pass
            for link_key in getattr(causal, 'temporal_links', {}).keys():
                try:
                    if '→' in link_key:
                        c, e = link_key.split('→', 1)
                        known_forward.add((c, e))
                        known_reverse.add((e, c))
                except Exception:
                    pass

            if not known_forward:
                return response

            violations = []
            for cause_claim, effect_claim in claims:
                cause_claim = cause_claim.strip()
                effect_claim = effect_claim.strip()
                if len(cause_claim) < 2 or len(effect_claim) < 2:
                    continue
                # 检查是否反向(声称 A→B 但已知 B→A)
                if (cause_claim, effect_claim) in known_reverse:
                    violations.append(
                        f"声明 '{cause_claim}→{effect_claim}' 与已知反向因果冲突"
                    )
                # 检查是否完全未知(声称 A→B 但 A 和 B 都在已知集中却无连接)
                elif ((cause_claim, effect_claim) not in known_forward
                      and any(c == cause_claim for c, _ in known_forward)
                      and any(e == effect_claim for _, e in known_forward)):
                    violations.append(
                        f"声明 '{cause_claim}→{effect_claim}' 未在已知因果键中找到"
                    )

            if violations:
                self._causal_violations.extend(violations)
                warning = "\n[Causal Warning] " + "; ".join(violations[:3])
                return response + warning
            return response
        except Exception as e:
            logger.debug(f"_causal_verify 失败: {e}")
            return response

    def _fallback_respond(self, domain: str) -> str:
        """Fallback response when no LLM channel is available."""
        return (
            f"[PSI Driver - {domain}] Processed cycle {self.cycle_count}. "
            "No LLM channel available."
        )

    def stats(self) -> Dict[str, Any]:
        """Return PSI driver statistics."""
        modules_available = sum(
            1 for m in [
                'world', 'self_model', 'conscious', 'causal',
                'analogical', 'memory_system', 'learning',
            ]
            if hasattr(self.agent, m) and getattr(self.agent, m) is not None
        )
        stats = {
            "canonical": True,
            "cycles": self.cycle_count,
            "domain": self.last_domain,
            "focus": self._last_focus,
            "modules_available": modules_available,
            "llm_connected": self.llm is not None,
        }
        if self._kakeya:
            stats["kakeya"] = self._kakeya.stats()
        if self._mesh and self._mesh_initialized:
            stats["mesh"] = self._mesh.stats()
        return stats


def integrate_psi_driver(
    agent: Any,
    llm_channel: Optional[callable] = None,
    enable_causal_verification: bool = False,
    enable_kakeya_monitor: bool = True,
    enable_mesh: bool = True,
) -> PSIDriver:
    """
    Attach a PSI Driver to an AGIAgent instance.

    Sets `agent.psi_driver` to the canonical PSIDriver instance. Subject
    turns enter this driver exactly once; the AGIAgent core remains the
    cognitive module implementation behind the six-stage transaction.

    Args:
        agent: AGIAgent instance (or any object with the expected modules)
        llm_channel: Callable that takes a prompt string and returns a
                     natural language response string. This is the LLM
                     acting as an I/O sub-processor only.
        enable_causal_verification: P1-5 — 若为 True,PSI driver 会从 LLM
                     响应中抽取因果声明,与 UnifiedCausalEngine 已学因果
                     键/规则做一致性校验,矛盾时追加 [Causal Warning]。
        enable_kakeya_monitor: P0 — 若为 True,启用 Kakeya 认知方向覆盖度
                     监控器,检测需求方向采样的不均匀缺口并注入注意力偏置。
        enable_mesh: 若为 True,启用 Directional Agent Mesh 编排器,
                    在 PSI 循环中自动激活方向代理组合。

    Returns:
        The PSIDriver instance
    """
    driver = PSIDriver(
        agent, llm_channel,
        enable_causal_verification=enable_causal_verification,
        enable_kakeya_monitor=enable_kakeya_monitor,
        enable_mesh=enable_mesh,
    )
    agent.psi_driver = driver
    logger.info(
        f"PSI Driver integrated into {getattr(agent, 'name', 'agent')} "
        f"(causal_verification={enable_causal_verification}, "
        f"kakeya_monitor={enable_kakeya_monitor}, "
        f"mesh={enable_mesh})"
    )
    return driver
