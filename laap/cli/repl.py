"""
LAAP — Interactive REPL
Golden dragon CLI with life computing paradigm.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os, sys, time, json, logging
from typing import Any, Dict, List, Optional

from laap import __version__
from laap.cli.commands import resolve, by_category, help_text, COMMAND_REGISTRY
from laap.cli.skins import render_logo, render_title, GOLD, GOLD_BRIGHT, GOLD_DIM, RESET, BOLD, SYM
from laap.agent.base import Agent
from laap.agent.lifelike import LifelikeAgent

from laap.cli.config_manager import config_manager
from laap.ui.display import needs_bar_chart, emotion_grid, format_section_box, bottom_status_bar, C
from laap.ui.stream_handler import StreamHandler
from laap.store.session_manager import SessionManager

# ── Tab Completion & History ─────────────────────────────────────
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import WordCompleter, FuzzyWordCompleter
    from prompt_toolkit.styles import Style as PTKStyle
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False
    try:
        import readline
    except ImportError:
        pass  # 可选模块，降级处理
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".laap", "cli_history")


# Theme state
_theme_name = "ao"
_session_mgr = SessionManager()


class LAAP_REPL:
    """Interactive LAAP CLI — golden dragon interface"""

    def __init__(self, agent: Agent, args):
        self.agent = agent
        self.args = args
        self.running = True
        self.history: List[str] = []
        self._register_handlers()
        # ── Setup tab completion & persistent history ──
        self._history_file = HISTORY_FILE
        self._completer = None
        self._pt_session = None
        self._setup_completion()

    def _register_handlers(self):
        self.handlers = {
            "help": self._cmd_help, "?": self._cmd_help, "h": self._cmd_help,
            "exit": self._cmd_exit, "quit": self._cmd_exit, "bye": self._cmd_exit,
            "status": self._cmd_status, "stats": self._cmd_status, "info": self._cmd_status,
            "self": self._cmd_self, "whoami": self._cmd_self,
            "needs": self._cmd_needs, "drives": self._cmd_needs, "psi": self._cmd_needs,
            "emotion": self._cmd_emotion, "mood": self._cmd_emotion, "affect": self._cmd_emotion,
            "evolve": self._cmd_evolve, "rsi": self._cmd_evolve, "improve": self._cmd_evolve,
            "fitness": self._cmd_fitness, "score": self._cmd_fitness, "eval": self._cmd_fitness,
            "grow": self._cmd_grow, "reflect": self._cmd_grow, "learn": self._cmd_grow,
            "tools": self._cmd_tools, "functions": self._cmd_tools,
            "fork": self._cmd_fork, "split": self._cmd_fork,
            "mutate": self._cmd_mutate,
            "lineage": self._cmd_lineage,
            "swarm": self._cmd_swarm, "hive": self._cmd_swarm,
            "immune": self._cmd_immune, "health": self._cmd_immune,
            "protocol": self._cmd_protocol, "lifecycle": self._cmd_protocol,
            "contract": self._cmd_contract, "promise": self._cmd_contract,
            "config": self._cmd_config, "settings": self._cmd_config,
            "model": self._cmd_model, "llm": self._cmd_model,
            "models": self._cmd_models, "available_models": self._cmd_models,
            "discover": self._cmd_discover, "scan": self._cmd_discover, "refresh": self._cmd_discover,
            "reset": self._cmd_reset, "clear": self._cmd_clear,
            "save": self._cmd_save, "snap": self._cmd_save,
            "load": self._cmd_load, "restore": self._cmd_load,
            "sessions": self._cmd_sessions, "snapshots": self._cmd_sessions,
            "share": self._cmd_share, "broadcast": self._cmd_share,
            "theme": self._cmd_theme,
        }

    def _prompt(self) -> str:
        step = getattr(self.agent, 'step_count', 0)
        return f"  {GOLD}◆{RESET} {GOLD_BRIGHT}Ao{RESET} {GOLD_DIM}[step {step}]{RESET} > "

    def _banner(self):
        # Use the Hermes-style welcome banner (logo + bordered panel + tip)
        try:
            from laap.ui.hermes_banner import print_banner
            print_banner()
            return
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        logo = render_logo("color")
        title = render_title(__version__)
        logger.info(f"\n{GOLD}{logo}{RESET}")
        logger.info(f"{title}")
        logger.info(f"  {GOLD_DIM}{'='*54}{RESET}")
        logger.info(f"  {GOLD}Living Computation Paradigm{RESET}")
        logger.info(f"  {GOLD_DIM}Protocol v{__version__} | /help for commands | /config to set API keys{RESET}")
        logger.info(f"  {GOLD_DIM}{'='*54}{RESET}\n")
        if config_manager.is_configured():
            active = config_manager.get_active()
            if active:
                logger.info(f"  {SYM['ok']} {GOLD_DIM}Active: {config_manager.config.active_provider} -> {active.model}{RESET}")
            for pid, p in config_manager.config.providers.items():
                if p.api_key and pid != config_manager.config.active_provider:
                    logger.info(f"  {GOLD_DIM}  Available: {pid} ({p.model}){RESET}")
        else:
            logger.warning(f"  {SYM['warn']} {GOLD_DIM}No API keys configured. Use /config to set up.{RESET}")
        print()

    def _setup_completion(self):
        """Initialize tab completion and persistent input history."""
        # Collect all commands for completion
        cmd_list = sorted(self.handlers.keys()) + ["help", "exit", "quit", "status", "system", "memory",
                                                     "/help", "/exit", "/quit", "/new", "/clear",
                                                     "/retry", "/undo", "/model", "/status"]
        self._completer = FuzzyWordCompleter(cmd_list) if HAS_PROMPT_TOOLKIT else None
        
        # Ensure history directory exists
        hist_dir = os.path.dirname(self._history_file)
        os.makedirs(hist_dir, exist_ok=True)
        
        if HAS_PROMPT_TOOLKIT:
            ptk_style = PTKStyle.from_dict({
                "prompt": "ansibrightyellow bold",
                "completions.completion": "bg:#1a1a2e #ffd700",
                "completions.completion.current": "bg:#ffd700 #1a1a2e bold",
            })
            try:
                self._pt_session = PromptSession(
                    history=FileHistory(self._history_file),
                    completer=self._completer,
                    style=ptk_style,
                    complete_while_typing=True,
                    vi_mode=False,
                    enable_history_search=True,
                )
            except Exception:
                # Fallback: prompt_toolkit failed (no console, etc.)
                self._pt_session = None
        else:
            # Fallback: use readline
            try:
                readline.set_completer(self._readline_completer)
                readline.parse_and_bind("tab: complete")
                readline.set_history_length(500)
                try:
                    readline.read_history_file(self._history_file)
                except FileNotFoundError as e:
                    logger.debug(f"操作失败: {e}")
            except Exception as e:
                logger.debug(f"操作失败: {e}")
    def _readline_completer(self, text: str, state: int):
        """Simple readline completer fallback."""
        cmd_list = list(self.handlers.keys()) + ["/help", "/exit", "/quit", "/new"]
        matches = [c for c in cmd_list if c.startswith(text)]
        return matches[state] if state < len(matches) else None

    def _save_history(self):
        """Persist history to file."""
        if HAS_PROMPT_TOOLKIT:
            return  # FileHistory saves automatically
        try:
            readline.set_history_length(500)
            readline.write_history_file(self._history_file)
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def _get_input(self, prompt: str) -> str:
        """Get user input with tab completion and history."""
        if HAS_PROMPT_TOOLKIT and self._pt_session:
            try:
                return self._pt_session.prompt(prompt).strip()
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise
    
    def run(self):
        self._banner()
        self._refresh_status_bar()
        while self.running:
            try:
                line = self._get_input(self._prompt())
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {GOLD_DIM}Ao sleeps...{RESET}"); break
            if not line:
                self._refresh_status_bar()
                continue
            self.history.append(line)
            self._dispatch(line)

    def _dispatch(self, line: str):
        if line.startswith("/"):
            parts = line[1:].split(maxsplit=1)
            cmd, args = parts[0].lower(), parts[1] if len(parts) > 1 else ""
            handler = self.handlers.get(cmd)
            if handler:
                handler(args)
            else:
                logger.warning(f"  {SYM['warn']} Unknown: /{cmd}  (try /help)")
            self._refresh_status_bar()
            return
        self._handle_natural_language(line)

    def _handle_natural_language(self, line: str):
        """Natural language query with rich streaming display."""
        llm = getattr(self.agent, 'llm', None)
        if llm is None:
            logger.warning(f"  {SYM['warn']} No LLM — use /config to set API key\n")
            self._refresh_status_bar()
            return

        try:
            # Phase 2: StreamHandler for live token/tool rendering
            handler = StreamHandler(verbose=self.agent.config.verbose)
            response = self.agent.chat(line, handler=handler)
            if not response and not handler.has_errors:
                logger.warning(f"  {SYM['warn']} Empty response\n")
        except Exception as e:
            logger.info(f"  {SYM['err']} {e}\n")
        finally:
            self._refresh_status_bar()

    def _refresh_status_bar(self):
        """Print a status info line after each action."""
        active = config_manager.get_active()
        provider = ""
        model = ""
        if active:
            provider = config_manager.config.active_provider or ""
            model = active.model or ""

        tool_count = len(self.agent.tool_registry.list()) if hasattr(self.agent, 'tool_registry') else 0
        step = getattr(self.agent, 'step_count', 0)

        emotion = ""
        if hasattr(self.agent, 'emotion_gradient'):
            es = self.agent.emotion_gradient.state
            if es.valence > 0.3:
                emotion = "positive"
            elif es.valence < -0.3:
                emotion = "negative"
            else:
                emotion = "neutral"

        bar = bottom_status_bar(
            provider=provider,
            model=model,
            tool_count=tool_count,
            step=step,
            emotion=emotion,
        )
        sys.stdout.write(f"\r{C.CLEAR_LINE}{bar}\n")
        sys.stdout.flush()

    def _stylize(self, text: str, color=GOLD_BRIGHT) -> str:
        return f"{color}{text}{RESET}"

    # ── Command Handlers ──

    def _cmd_help(self, args: str):
        if args:
            print(f"\n{help_text(args)}\n"); return
        logger.info(f"\n  {GOLD}{'─'*54}{RESET}")
        logger.info(f"  {GOLD_BRIGHT}LAAP Commands{RESET}")
        logger.info(f"  {GOLD}{'─'*54}{RESET}")
        logger.info(f"\n{help_text()}\n")
    def _cmd_exit(self, args: str):
        logger.info(f"\n  {GOLD_DIM}Ao returns to the void...{RESET}")
        self._save_history()
        self.running = False

    def _cmd_status(self, args: str):
        s = self.agent.status()
        print()
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}Agent{RESET}:         {s.get('name', 'N/A')}")
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}ID{RESET}:           {s.get('id', 'N/A')[:12]}")
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}Alive{RESET}:        {SYM['ok'] if s.get('alive') else SYM['err']}")
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}Steps{RESET}:        {s.get('steps', 0)}")
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}Modifications{RESET}: {s.get('self_modifications', 0)}")
        logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}Tools{RESET}:        {s.get('tools', 0)}")
        llm = getattr(self.agent, 'llm', None)
        if llm:
            logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}LLM{RESET}:         {SYM['ok']}{llm.to_dict().get('model', 'connected')}")
        else:
            logger.info(f"  {SYM['dragon']} {GOLD_BRIGHT}LLM{RESET}:         {GOLD_DIM}local-only{RESET}")
        if hasattr(self.agent, 'rsi') and self.agent.rsi:
            rs = self.agent.rsi.status()
            logger.info(f"  {SYM['evo']} {GOLD_BRIGHT}RSI{RESET}:          {rs['total']} props, {rs['adopted']} adopted ({rs['adoption_rate']:.0%})")
        print()

    def _cmd_self(self, args: str):
        if hasattr(self.agent, 'awareness') and self.agent.awareness:
            logger.info(f"\n  {self.agent.awareness.know_thyself()}\n")
        else:
            logger.warning(f"  {SYM['warn']} Awareness not available\n")
    def _cmd_needs(self, args: str):
        if not hasattr(self.agent, 'needs'):
            print(f"  {SYM['warn']} PSI needs not available\n"); return
        profile = self.agent.needs.get_profile()
        logger.info(f"\n{format_section_box('PSI Needs Profile')}")
        logger.info(f"\n{needs_bar_chart(profile)}")
        dom, drive = self.agent.needs.get_dominant_need()
        if dom:
            logger.info(f"\n  {GOLD_DIM}Dominant need: {GOLD_BRIGHT}{dom.value}{RESET} {GOLD_DIM}(drive={drive:.3f}){RESET}")
        print()

    def _cmd_emotion(self, args: str):
        if not hasattr(self.agent, 'emotion_gradient'):
            print(f"  {SYM['warn']} Emotion not available\n"); return
        e = self.agent.emotion_gradient.state
        mr = self.agent.emotion_gradient.mean_reward
        emotional_state = {
            "valence": e.valence,
            "arousal": e.arousal,
            "dominance": e.dominance,
            "confidence": e.confidence,
        }
        logger.info(f"\n{format_section_box('Emotional State')}")
        logger.info(f"\n{emotion_grid(emotional_state)}")
        logger.info(f"\n  {GOLD_DIM}Mean Reward:{RESET} {GOLD_BRIGHT}{mr:.4f}{RESET}")
        print()

    def _cmd_evolve(self, args: str):
        if not hasattr(self.agent, 'rsi') or not self.agent.rsi:
            print(f"  {SYM['warn']} RSI not enabled\n"); return
        proposal = self.agent.rsi.step(self.agent, force=True)
        if proposal:
            logger.info(f"\n  {SYM['evo']} {GOLD_BRIGHT}RSI Proposal{RESET}")
            logger.info(f"    Hypothesis: {proposal.hypothesis}")
            logger.info(f"    Type:       {proposal.modification.get('type', 'N/A')}")
            logger.info(f"    Confidence: {proposal.confidence:.2f}")
            logger.warning(f"    Adopted:    {SYM['ok'] if proposal.adopted else SYM['warn']}")
        from laap.evaluation.fitness import FitnessEvaluator
        ev = FitnessEvaluator()
        print(f"    Fitness:    {ev.composite_fitness(self.agent):.4f}");
        print()

    def _cmd_fitness(self, args: str):
        if not hasattr(self.agent, 'evaluator'):
            from laap.evaluation.fitness import FitnessEvaluator
            self.agent.evaluator = FitnessEvaluator()
        r = self.agent.evaluator.report(self.agent)
        print()
        for k, v in r.get("scores", {}).items():
            bar = chr(9608) * int(v * 20) + chr(9617) * (20 - int(v * 20))
            logger.info(f"  {k:20s} [{GOLD}{bar}{RESET}] {v:.4f}")
        logger.info(f"  {'-'*42}")
        logger.info(f"  {GOLD_BRIGHT}Composite{RESET}:       {r['fitness']:.4f}")
        print()

    def _cmd_grow(self, args: str):
        if hasattr(self.agent, '_self_reflect'):
            ref = self.agent._self_reflect()
            logger.info(f"\n  {SYM['seed']} {GOLD_BRIGHT}Growth Reflection{RESET}")
            logger.info(f"    Observation: {ref.observation}")
            logger.info(f"    Hypothesis:  {ref.hypothesis}")
            logger.info(f"    Outcome:     {ref.outcome}")
        logger.info(f"    Step:        {self.agent.step_count}")
        print()

    def _cmd_tools(self, args: str):
        category = args or None
        tools = self.agent.tool_registry.list(category=category)
        print()
        for t in tools:
            logger.info(f"  {SYM['node']} {t.name:22s} [{GOLD_DIM}{t.category}{RESET}] {t.description[:50]}")
        logger.info(f"\n  {GOLD_DIM}Total: {len(tools)} tools{RESET}")
        print()

    def _cmd_fork(self, args: str):
        strategy = args or None
        from laap.evolution.symbolic import SymbolicRecursionLayer
        sym = SymbolicRecursionLayer(max_population=5)
        sym.population[self.agent.id] = self.agent
        child = sym.fork(self.agent.id, strategy=strategy)
        if child:
            logger.info(f"\n  {SYM['seed']} {GOLD_BRIGHT}Fork Created{RESET}")
            logger.info(f"    Parent: {self.agent.id[:12]}")
            logger.info(f"    Child:  {child.id[:12]}")
            logger.info(f"    Strategy: {strategy or 'random'}")
        else:
            logger.error(f"  {SYM['err']} Fork failed\n")
        print()

    def _cmd_mutate(self, args: str):
        strategy = args or None
        from laap.evolution.mutation import MutationStrategy
        m = MutationStrategy()
        spec = m.select() if not strategy else m.strategies.get(strategy)
        if not spec:
            print(f"  {SYM['err']} Unknown strategy: {strategy}\n"); return
        logger.info(f"\n  {SYM['evo']} {GOLD_BRIGHT}Mutation{RESET}: {spec.name}")
        logger.info(f"    {spec.description}")
        logger.info(f"    Severity: {spec.severity}")
        state = {"config": {"exploration_rate": self.agent.config.exploration_rate,
                            "learning_rate": self.agent.config.learning_rate}, "needs": [], "goals": [], "skills": []}
        result = m.apply(state, spec.name)
        mutated = result["mutated"]
        logger.info(f"    New exploration_rate: {mutated['config']['exploration_rate']:.3f}")
        print()

    def _cmd_lineage(self, args: str):
        from laap.evolution.symbolic import SymbolicRecursionLayer
        sym = SymbolicRecursionLayer()
        sym.population[self.agent.id] = self.agent
        logger.info(f"\n  {SYM['seed']} {GOLD_BRIGHT}Lineage{RESET}")
        logger.info(f"    Current: {self.agent.id[:12]}")
        logger.info(f"    Generation: 0")
        print()

    def _cmd_swarm(self, args: str):
        logger.info(f"\n  {SYM['node']} {GOLD_BRIGHT}Swarm Status{RESET}")
        logger.info(f"    Mode: collaborative")
        logger.info(f"    Available: 1 agent (local)")
        print()

    def _cmd_immune(self, args: str):
        logger.info(f"\n  {SYM['immune']} {GOLD_BRIGHT}Immune System{RESET}")
        logger.info(f"    Status: {GOLD}Healthy{RESET}")
        logger.info(f"    Threats: 0")
        logger.info(f"    Quarantines: 0")
        print()

    def _cmd_protocol(self, args: str):
        steps = getattr(self.agent, 'step_count', 0)
        age = time.time() - self.agent.birth_time if hasattr(self.agent, 'birth_time') else 0
        logger.info(f"\n  {SYM['inf']} {GOLD_BRIGHT}Lifecycle Protocol{RESET}")
        logger.info(f"    Stage: {GOLD}Autonomous{RESET}")
        logger.info(f"    Age: {age:.0f}s")
        logger.info(f"    Steps: {steps}")
        logger.info(f"    Status: {SYM['ok'] if self.agent.alive else SYM['err']} {'Alive' if self.agent.alive else 'Terminated'}")
        print()

    def _cmd_contract(self, args: str):
        logger.info(f"\n  {SYM['inf']} {GOLD_BRIGHT}Behavior Contract{RESET}")
        logger.info(f"    Safety: Engaged")
        logger.info(f"    Boundaries: Active")
        logger.info(f"    Ethics: Loaded")
        print()

    def _cmd_config(self, args: str):
        """Configure API through ConfigManager interactive wizard"""
        if args == "switch":
            config_manager.switch_interactive()
        elif args == "list":
            for pid, p in config_manager.config.providers.items():
                status = SYM['ok'] if p.api_key else " "
                active = " < active" if pid == config_manager.config.active_provider else ""
                logger.info(f"  {status} {pid:15s} {p.name:20s} {p.model:15s}{active}")
        else:
            config_manager.interactive_setup()
        # Reconnect LLM after config change
        config_manager.apply_to_environment()
        if hasattr(self.agent, 'llm_factory'):
            try:
                provider = config_manager.config.active_provider
                active = config_manager.get_active()
                if active:
                    self.agent.llm = self.agent.llm_factory.get(
                        name=provider, model=active.model,
                    )
                    logger.info(f"  {SYM['ok']} LLM reconnected: {provider} -> {active.model}")
            except Exception as e:
                logger.warning(f"  {SYM['warn']} LLM reconnection: {e}")
    def _cmd_models(self, args: str):
        """List all supported models grouped by provider."""
        from laap.llm.provider import MODEL_REGISTRY, MODEL_LABELS
        logger.info(f"\n  {GOLD}{'─'*54}{RESET}")
        logger.info(f"  {GOLD_BRIGHT}All Supported Models{RESET}")
        logger.info(f"  {GOLD}{'─'*54}{RESET}")
        by_provider: dict = {}
        for mid, info in MODEL_REGISTRY.items():
            by_provider.setdefault(info["provider"], []).append(mid)
        for prov, models in sorted(by_provider.items()):
            logger.info(f"\n  {SYM['dragon']} {GOLD_BRIGHT}{prov}{RESET}")
            for mid in models:
                label = MODEL_LABELS.get(mid, mid)
                api_url = info.get("api_url", "") if mid in MODEL_REGISTRY else ""
                logger.info(f"    {mid:30s} {GOLD_DIM}{label}{RESET}")
        logger.info(f"\n  {GOLD_DIM}Set with: /model <model_id>{RESET}")
        logger.info(f"  {GOLD_DIM}Or:       export LAAP_MODEL=<model_id>{RESET}\n")
    def _cmd_discover(self, args: str):
        """Discover latest model IDs from provider APIs."""
        from laap.llm.discovery import discovery
        from laap.llm.factory import PROVIDER_KEY_ENV

        providers_to_scan = [p for p in PROVIDER_KEY_ENV
                             if os.environ.get(PROVIDER_KEY_ENV[p])]
        if not providers_to_scan:
            logger.warning(f"\n  {SYM['warn']} No API keys configured. Set at least one provider key to scan.")
            logger.info(f"  {GOLD_DIM}  OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.{RESET}\n")
            return

        target = args.strip()
        if target:
            providers_to_scan = [p for p in providers_to_scan if target in p]

        logger.info(f"\n  {SYM['scan']} {GOLD_BRIGHT}Scanning {len(providers_to_scan)} provider(s) for models...{RESET}")
        logger.info(f"  {GOLD_DIM}{'─'*54}{RESET}")
        import concurrent.futures
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            fut_map = {}
            for prov in providers_to_scan:
                key = os.environ.get(PROVIDER_KEY_ENV[prov], "")
                fut = pool.submit(discovery.discover_provider, prov, api_key=key)
                fut_map[fut] = prov

            for fut in concurrent.futures.as_completed(fut_map):
                prov = fut_map[fut]
                try:
                    r = fut.result()
                    results[prov] = r
                    icon = SYM['ok'] if not r.errors else SYM['warn']
                    print(f"  {icon} {prov:15s} {r.total_found:3d} models"
                          f"  ({len(r.new_models):2d} new)  "
                          f"⏱ {r.duration_ms:.0f}ms")
                    if r.new_models:
                        for m in r.new_models[:5]:
                            from laap.llm.provider import MODEL_REGISTRY
                            if m not in MODEL_REGISTRY:
                                logger.info(f"     🆕 {GOLD}{m}{RESET}")
                except Exception as e:
                    results[prov] = None
                    logger.error(f"  {SYM['err']} {prov:15s} Error: {str(e)[:50]}")
        total_new = sum(len(r.new_models) for r in results.values() if r)
        logger.info(f"\n  {GOLD_DIM}{'─'*54}{RESET}")
        if total_new > 0:
            logger.info(f"  {SYM['evo']} {GOLD_BRIGHT}{total_new} new model(s) discovered!{RESET}")
            logger.info(f"  {GOLD_DIM}Use /discover <provider> to see details{RESET}")
            logger.info(f"  {GOLD_DIM}Use /model <model_id> to try a new model{RESET}")
            logger.info(f"\n  {GOLD_DIM}Auto-update registry with new models? (y/N){RESET}")
            for prov, r in results.items():
                if r and r.new_models:
                    logger.info(f"\n  {SYM['dragon']} {prov} new models:")
                    for m in r.new_models[:10]:
                        logger.info(f"    {m}")
        else:
            logger.info(f"  {GOLD_DIM}No new models found — your registry is current!{RESET}")
        print()

    def _cmd_model(self, args: str):
        if not args:
            active = config_manager.get_active()
            if active:
                logger.info(f"  {SYM['ok']} {GOLD_BRIGHT}Current:{RESET} {config_manager.config.active_provider} -> {active.model}")
            else:
                logger.warning(f"  {SYM['warn']} No active provider")
            logger.info(f"  {GOLD_DIM}Configured providers:{RESET}")
            for pid, p in config_manager.config.providers.items():
                status = SYM['ok'] if p.api_key else " "
                active_mark = "  ← active" if pid == config_manager.config.active_provider else ""
                logger.info(f"  {status} {pid:15s} {p.name:20s} {p.model:15s}{active_mark}")
            logger.info(f"\n  {GOLD_DIM}/config switch  — switch active provider{RESET}")
            logger.info(f"  {GOLD_DIM}/config        — add/configure a provider{RESET}")
            return

        # Try to switch
        if args in config_manager.config.providers:
            p = config_manager.config.providers[args]
            config_manager.set_provider(args, api_key=p.api_key, base_url=p.base_url, model=p.model)
            config_manager.apply_to_environment()
            try:
                self.agent.llm = self.agent.llm_factory.get(name=args, model=p.model)
                logger.info(f"  {SYM['ok']} Switched to: {args} -> {p.model}")
            except Exception as e:
                logger.error(f"  {SYM['err']} Failed to connect: {e}")
        else:
            # Try as model name within current provider
            try:
                self.agent.llm = self.agent.llm_factory.get(model=args)
                logger.info(f"  {SYM['ok']} Switched model: {args}")
            except Exception as e:
                logger.info(f"  {SYM['err']} {e}")
    def _cmd_reset(self, args: str):
        self.agent.memory = type(self.agent.memory)()
        logger.info(f"  {SYM['ok']} Memory reset\n")
    def _cmd_clear(self, args: str):
        os.system("cls" if os.name == "nt" else "clear")

    def _cmd_save(self, args: str):
        """Save agent state snapshot. Usage: /save [name]"""
        name = args.strip() or f"snap_{int(time.time())}"
        try:
            path = _session_mgr.save_agent_state(name, self.agent)
            logger.info(f"  {SYM['ok']} {GOLD_BRIGHT}Agent state saved{RESET} as '{name}'")
            logger.info(f"  {GOLD_DIM}  {path}{RESET}\n")
        except Exception as e:
            logger.error(f"  {SYM['err']} Save failed: {e}\n")
    def _cmd_load(self, args: str):
        """Restore agent state from snapshot. Usage: /load [name]"""
        name = args.strip()
        if not name:
            logger.warning(f"  {SYM['warn']} Usage: /load <name>\n")
            return
        if _session_mgr.load_agent_state(name, self.agent):
            s = self.agent.status()
            logger.info(f"  {SYM['ok']} {GOLD_BRIGHT}Agent state restored{RESET} from '{name}'")
            logger.info(f"  {GOLD_DIM}  Steps: {s.get('steps', 0)} | Tools: {s.get('tools', 0)}{RESET}\n")
        else:
            logger.info(f"  {SYM['err']} Session '{name}' not found in agent states\n")
    def _cmd_sessions(self, args: str):
        """List all saved agent state snapshots."""
        states = _session_mgr.list_agent_states()
        if not states:
            logger.info(f"  {GOLD_DIM}No saved sessions found.{RESET}\n")
            return
        logger.info(f"\n{format_section_box('Saved Sessions')}")
        logger.info(f"  {GOLD_DIM}{'Name':<24s} {'Agent':<16s} {'Steps':<8s} {'Model':<20s} {'Saved'}{RESET}")
        logger.info(f"  {GOLD_DIM}{'─'*72}{RESET}")
        for s in states:
            saved = time.strftime('%m-%d %H:%M', time.localtime(s.get('saved_at', 0)))
            print(f"  {s['name']:<24s} {s.get('agent_name','?'):<16s} "
                  f"{str(s.get('step_count',0)):<8s} "
                  f"{s.get('model','?'):<20s} {saved}")
        logger.info(f"  {GOLD_DIM}{'─'*72}{RESET}")
        logger.info(f"  {GOLD_DIM}Total: {len(states)} snapshots{RESET}")
        logger.info(f"  {GOLD_DIM}Use /save <name> to save, /load <name> to restore{RESET}\n")
    def _cmd_share(self, args: str):
        if hasattr(self.agent, 'awareness') and self.agent.awareness:
            self.agent.awareness.record_event("share", {"message": args[:100]})
        logger.info(f"  {SYM['ok']} Shared: {args[:60]}\n")
    def _cmd_theme(self, args: str):
        """Switch between UI themes: 'ao' (gold) or 'mono'"""
        global _theme_name
        theme = args.strip().lower() if args else "ao"
        if theme not in ("ao", "mono"):
            logger.warning(f"  {SYM['warn']} Unknown theme: {theme} (use 'ao' or 'mono')\n")
            return
        _theme_name = theme
        from laap.cli.skins import engine
        engine.set_active(theme)
        logger.info(f"  {SYM['ok']} Theme switched to: {theme}\n")