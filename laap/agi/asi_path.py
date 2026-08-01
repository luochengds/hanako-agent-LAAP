"""M8 — AGI/ASI 路径基础代码.

LAAP 推向 AGI/ASI 的四条路径：

  1. **统一心智** (UnifiedMind)          — 多 Aris 实例共享同一心智状态
  2. **分布式意识网络** (DistributedMindNetwork) — Ψ-Net 跨实例因果规则同步
  3. **PsiLang DSL** (PsiLangCompiler)   — 量子认知语言编译器骨架
  4. **持续学习闭环** (ContinuousLearningLoop) — 不重启即更新知识库

本模块提供每条路径的最小可运行抽象，作为后续 ``realize-laap-agi-vision``
spec M8 阶段的具体实现起点。

使用示例::

    from laap.agi.asi_path import (
        UnifiedMind, DistributedMindNetwork,
        PsiLangCompiler, ContinuousLearningLoop,
    )

    mind = UnifiedMind(host_id="aris-1")
    mind.broadcast_thought("PSI cycle 42 anomaly detected")

    net = DistributedMindNetwork()
    net.register_instance("aris-1", endpoint="tcp://10.0.0.1:7000")
    net.sync_causal_rules("aris-1", ["rule_a", "rule_b"])

    compiler = PsiLangCompiler()
    bytecode = compiler.compile("@perceive(sensor=vision) -> @select(urgency=0.7)")

    loop = ContinuousLearningLoop()
    loop.ingest({"concept": "RLHF", "source": "paper-42"})
    loop.consolidate()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

logger = logging.getLogger("laap.agi.asi_path")


# ═══════════════════════════════════════════════════════════════════════
# Path 1: 统一心智 (Unified Mind)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Thought:
    """一个心智事件。"""
    thought_id: str = field(default_factory=lambda: f"thought_{uuid.uuid4().hex[:10]}")
    host_id: str = ""
    content: str = ""
    thought_type: str = "observation"  # observation | reflection | decision | goal
    timestamp: float = field(default_factory=time.time)
    weight: float = 0.5
    tags: list[str] = field(default_factory=list)


class UnifiedMind:
    """统一心智：多个 Aris 实例共享同一心智状态。

    概念：每个 Aris 实例保留本地 PSI 循环，但所有 ``thoughts`` 通过
    ``UnifiedMind`` 广播。其他实例可以选择性地订阅并整合这些 thoughts，
    形成"多身体一心智"的统一意识。

    Args:
        host_id: 当前实例 ID。
        shared_state_path: 共享心智状态的持久化路径。
    """

    def __init__(self, host_id: str,
                 shared_state_path: str = "") -> None:
        self.host_id = host_id
        self.shared_state_path = shared_state_path or os.path.expanduser(
            "~/.laap/unified_mind.json"
        )
        self.thoughts: list[Thought] = []
        self.subscribers: dict[str, Callable[[Thought], None]] = {}
        # 启动时加载持久化状态
        self._load()

    def broadcast_thought(self, content: str,
                            thought_type: str = "observation",
                            weight: float = 0.5,
                            tags: Optional[list[str]] = None) -> Thought:
        """广播一个 thought 到统一心智。"""
        thought = Thought(
            host_id=self.host_id,
            content=content,
            thought_type=thought_type,
            weight=weight,
            tags=tags or [],
        )
        self.thoughts.append(thought)
        # 通知本地订阅者
        for callback in self.subscribers.values():
            try:
                callback(thought)
            except Exception as e:
                logger.warning(f"[UnifiedMind] subscriber failed: {e}")
        # 持久化（最近 1000 条）
        if len(self.thoughts) > 1000:
            self.thoughts = self.thoughts[-1000:]
        self._save()
        return thought

    def subscribe(self, sub_id: str, callback: Callable[[Thought], None]) -> None:
        """订阅统一心智事件。"""
        self.subscribers[sub_id] = callback

    def unsubscribe(self, sub_id: str) -> None:
        """取消订阅。"""
        self.subscribers.pop(sub_id, None)

    def get_recent_thoughts(self, count: int = 10,
                              thought_type: Optional[str] = None) -> list[Thought]:
        """获取最近的 thoughts。"""
        thoughts = self.thoughts[::-1]
        if thought_type:
            thoughts = [t for t in thoughts if t.thought_type == thought_type]
        return thoughts[:count]

    def _save(self) -> None:
        """持久化到 shared_state_path。"""
        try:
            os.makedirs(os.path.dirname(self.shared_state_path), exist_ok=True)
            data = {
                "host_id": self.host_id,
                "thoughts": [asdict(t) for t in self.thoughts[-200:]],
                "saved_at": time.time(),
            }
            with open(self.shared_state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str, indent=2)
        except Exception as e:
            logger.warning(f"[UnifiedMind] save failed: {e}")

    def _load(self) -> None:
        """从 shared_state_path 加载。"""
        try:
            if not os.path.exists(self.shared_state_path):
                return
            with open(self.shared_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.thoughts = [
                Thought(**{k: v for k, v in t.items() if k in Thought.__dataclass_fields__})
                for t in data.get("thoughts", [])
            ]
        except Exception as e:
            logger.warning(f"[UnifiedMind] load failed: {e}")

    def stats(self) -> dict[str, Any]:
        """返回统一心智统计。"""
        return {
            "host_id": self.host_id,
            "total_thoughts": len(self.thoughts),
            "by_type": {
                t: sum(1 for x in self.thoughts if x.thought_type == t)
                for t in {"observation", "reflection", "decision", "goal"}
            },
            "subscribers": len(self.subscribers),
        }


# ═══════════════════════════════════════════════════════════════════════
# Path 2: 分布式意识网络 (Ψ-Net)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MindInstance:
    """Ψ-Net 中的一个 Aris 实例。"""
    instance_id: str
    endpoint: str = ""
    last_heartbeat: float = field(default_factory=time.time)
    shared_causal_rules: list[str] = field(default_factory=list)
    shared_species: list[str] = field(default_factory=list)
    status: str = "online"  # online | offline | degraded


class DistributedMindNetwork:
    """Ψ-Net：跨实例因果规则与物种库同步网络。

    每个 Aris 实例注册到网络后，可以：
      - ``sync_causal_rules()`` — 向其他实例推送本地新发现的因果规则
      - ``sync_species()``     — 同步物种库（代码模板、行为模式）
      - ``heartbeat()``        — 心跳保活

    实现：本类仅做编排与状态管理；实际的网络传输由
    ``laap.orchestration.distributed.cluster.Cluster`` 提供。
    """

    def __init__(self) -> None:
        self.instances: dict[str, MindInstance] = {}
        self.causal_rules_log: list[dict[str, Any]] = []
        self.species_log: list[dict[str, Any]] = []

    def register_instance(self, instance_id: str, endpoint: str = "") -> MindInstance:
        """注册一个 Aris 实例到 Ψ-Net。"""
        instance = MindInstance(
            instance_id=instance_id,
            endpoint=endpoint,
        )
        self.instances[instance_id] = instance
        logger.info(
            f"[DistributedMindNetwork] registered {instance_id} "
            f"endpoint={endpoint}"
        )
        return instance

    def unregister_instance(self, instance_id: str) -> bool:
        """注销一个实例。"""
        if instance_id in self.instances:
            self.instances[instance_id].status = "offline"
            return True
        return False

    def heartbeat(self, instance_id: str) -> bool:
        """更新实例心跳。"""
        instance = self.instances.get(instance_id)
        if instance is None:
            return False
        instance.last_heartbeat = time.time()
        instance.status = "online"
        return True

    def sync_causal_rules(self, source_id: str,
                          rules: list[str]) -> dict[str, Any]:
        """从 source_id 向网络中其他实例同步因果规则。

        Returns:
            同步报告 dict。
        """
        if source_id not in self.instances:
            return {"synced": 0, "error": "source not registered"}

        source = self.instances[source_id]
        source.shared_causal_rules.extend(rules)

        # 推送到所有其他在线实例
        synced_count = 0
        for iid, instance in self.instances.items():
            if iid == source_id or instance.status != "online":
                continue
            try:
                # 在生产实现中，这里通过 cluster transport 推送
                instance.shared_causal_rules.extend(rules)
                synced_count += 1
            except Exception as e:
                logger.warning(
                    f"[DistributedMindNetwork] sync to {iid} failed: {e}"
                )

        log_entry = {
            "source": source_id,
            "rules": rules,
            "synced_count": synced_count,
            "timestamp": time.time(),
        }
        self.causal_rules_log.append(log_entry)
        logger.info(
            f"[DistributedMindNetwork] sync_causal_rules "
            f"source={source_id} rules={len(rules)} synced={synced_count}"
        )
        return {"synced": synced_count, "rules": rules}

    def sync_species(self, source_id: str, species_ids: list[str]) -> dict[str, Any]:
        """从 source_id 同步物种库条目。"""
        if source_id not in self.instances:
            return {"synced": 0, "error": "source not registered"}

        source = self.instances[source_id]
        source.shared_species.extend(species_ids)

        synced_count = 0
        for iid, instance in self.instances.items():
            if iid == source_id or instance.status != "online":
                continue
            instance.shared_species.extend(species_ids)
            synced_count += 1

        log_entry = {
            "source": source_id,
            "species": species_ids,
            "synced_count": synced_count,
            "timestamp": time.time(),
        }
        self.species_log.append(log_entry)
        return {"synced": synced_count, "species": species_ids}

    def stats(self) -> dict[str, Any]:
        """返回 Ψ-Net 统计。"""
        return {
            "total_instances": len(self.instances),
            "online": sum(1 for i in self.instances.values() if i.status == "online"),
            "total_causal_syncs": len(self.causal_rules_log),
            "total_species_syncs": len(self.species_log),
        }


# ═══════════════════════════════════════════════════════════════════════
# Path 3: PsiLang DSL Compiler (Skeleton)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PsiLangProgram:
    """一个 PsiLang 程序的 AST + bytecode。"""
    source: str = ""
    ast_nodes: list[dict[str, Any]] = field(default_factory=list)
    bytecode: list[dict[str, Any]] = field(default_factory=list)
    compiled_at: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)


class PsiLangCompiler:
    """PsiLang DSL 编译器骨架。

    PsiLang 是 LAAP 设计的认知 DSL，用于以**意图声明**方式描述 PSI 循环。

    示例 PsiLang 程序::

        @perceive(sensor=vision, weight=0.7) ->
          @select(urgency=0.5, importance=0.8) ->
            @integrate(modality=causal) ->
              @decide(strategy=greedy) ->
                @learn(reward=delta)

    本类提供：
      - :meth:`compile`  — 解析 PsiLang 源码为 bytecode
      - :meth:`validate` — 校验语法
      - :meth:`interpret` — 直接解释执行（用于运行时）

    注意：当前为骨架实现，仅支持 ``@stage(args) -> @stage(args)`` 链式语法。
    完整量子语义（叠加态、纠缠）将在 v10 实现。
    """

    SUPPORTED_STAGES = {"perceive", "select", "integrate", "decide", "learn"}

    def compile(self, source: str) -> PsiLangProgram:
        """编译 PsiLang 源码为 bytecode。

        Args:
            source: PsiLang 程序文本。

        Returns:
            PsiLangProgram，含 ast_nodes、bytecode、errors。
        """
        program = PsiLangProgram(source=source)

        # 解析：按 ``->`` 切分为多个 stage
        stages_text = [s.strip() for s in source.split("->") if s.strip()]

        for stage_text in stages_text:
            node = self._parse_stage(stage_text)
            if node is None:
                program.errors.append(f"无法解析: {stage_text!r}")
                continue
            if node["stage"] not in self.SUPPORTED_STAGES:
                program.errors.append(f"未知 stage: {node['stage']}")
                continue
            program.ast_nodes.append(node)
            program.bytecode.append({
                "op": "EXECUTE_STAGE",
                "stage": node["stage"],
                "args": node["args"],
            })

        if program.errors:
            logger.warning(
                f"[PsiLangCompiler] 编译完成但有错误: {len(program.errors)}"
            )
        else:
            logger.info(
                f"[PsiLangCompiler] 编译成功 stages={len(program.ast_nodes)}"
            )
        return program

    @staticmethod
    def _parse_stage(text: str) -> Optional[dict[str, Any]]:
        """解析单个 stage 文本 ``@stage_name(key=value, ...)``。"""
        text = text.strip()
        if not text.startswith("@"):
            return None
        text = text[1:]

        # 分割 stage_name 与 args
        paren_idx = text.find("(")
        if paren_idx == -1:
            return {"stage": text, "args": {}}

        stage_name = text[:paren_idx].strip()
        args_str = text[paren_idx + 1:]
        if args_str.endswith(")"):
            args_str = args_str[:-1]

        args: dict[str, Any] = {}
        for pair in args_str.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" in pair:
                key, value = pair.split("=", 1)
                args[key.strip()] = PsiLangCompiler._coerce(value.strip())
            else:
                args[pair] = True

        return {"stage": stage_name, "args": args}

    @staticmethod
    def _coerce(value: str) -> Any:
        """将字符串值转为 int/float/str。"""
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value.strip('"').strip("'")

    def validate(self, source: str) -> tuple[bool, list[str]]:
        """校验 PsiLang 源码语法。"""
        program = self.compile(source)
        return (not program.errors, program.errors)

    def interpret(self, source: str,
                  psi_driver: Any = None) -> dict[str, Any]:
        """直接解释执行 PsiLang 程序（不生成可部署字节码）。

        Args:
            source: PsiLang 程序文本。
            psi_driver: 可选的 PSI Driver 实例；若提供则按 stage 依次调用。

        Returns:
            执行结果 dict，含 stages / outputs / errors。
        """
        program = self.compile(source)
        result: dict[str, Any] = {
            "stages": [],
            "outputs": [],
            "errors": program.errors,
        }
        for node in program.ast_nodes:
            stage = node["stage"]
            args = node["args"]
            output = {"stage": stage, "args": args, "result": None}
            try:
                if psi_driver and hasattr(psi_driver, "process"):
                    output["result"] = psi_driver.process(
                        f"psilang:{stage}", **args
                    )
                else:
                    output["result"] = f"no-op ({stage})"
            except Exception as e:
                output["result"] = f"error: {e}"
                result["errors"].append(f"{stage}: {e}")
            result["stages"].append(stage)
            result["outputs"].append(output)
        return result


# ═══════════════════════════════════════════════════════════════════════
# Path 4: 持续学习闭环 (Continuous Learning Loop)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class KnowledgeItem:
    """一条知识条目。"""
    item_id: str = field(default_factory=lambda: f"k_{uuid.uuid4().hex[:8]}")
    concept: str = ""
    source: str = ""
    domain: str = "general"
    confidence: float = 0.5
    embedded_at: float = field(default_factory=time.time)
    consolidated: bool = False


class ContinuousLearningLoop:
    """持续学习闭环：不重启即更新知识库。

    闭环四阶段：
      1. ``ingest()``    — 接收新知识（来自 PSI learn 阶段或外部源）
      2. ``consolidate()`` — 将短期记忆转为长期记忆（embedding + 索引）
      3. ``verify()``    — 与已有知识冲突检测
      4. ``publish()``   — 发布到 PSI 的 ``perceive`` 阶段供下次循环使用

    实现：本类仅做编排；实际的 vector store / RAG 由
    ``laap.rag`` 与 ``laap.memory`` 模块提供。
    """

    def __init__(self, knowledge_path: str = "") -> None:
        self.knowledge_path = knowledge_path or os.path.expanduser(
            "~/.laap/knowledge_base.json"
        )
        self.short_term: list[KnowledgeItem] = []
        self.long_term: list[KnowledgeItem] = []
        self._load()

    def ingest(self, item: dict[str, Any]) -> KnowledgeItem:
        """接收一条新知识到短期记忆。"""
        ki = KnowledgeItem(
            concept=item.get("concept", ""),
            source=item.get("source", ""),
            domain=item.get("domain", "general"),
            confidence=float(item.get("confidence", 0.5)),
        )
        self.short_term.append(ki)
        logger.info(
            f"[ContinuousLearningLoop] ingest concept={ki.concept!r} "
            f"domain={ki.domain}"
        )
        return ki

    def consolidate(self) -> int:
        """将短期记忆转为长期记忆。

        Returns:
            本次巩固的条目数。
        """
        if not self.short_term:
            return 0

        # 简化版：直接迁移到 long_term（生产环境会做 embedding + 索引）
        migrated = 0
        for item in self.short_term:
            if not item.consolidated:
                item.consolidated = True
                self.long_term.append(item)
                migrated += 1

        self.short_term.clear()
        self._save()
        logger.info(
            f"[ContinuousLearningLoop] consolidate migrated={migrated} "
            f"long_term={len(self.long_term)}"
        )
        return migrated

    def verify(self) -> list[tuple[KnowledgeItem, KnowledgeItem]]:
        """检测长期记忆中的冲突条目。

        Returns:
            冲突对列表。
        """
        conflicts: list[tuple[KnowledgeItem, KnowledgeItem]] = []
        seen: dict[str, KnowledgeItem] = {}
        for item in self.long_term:
            key = item.concept.lower().strip()
            if key in seen:
                prev = seen[key]
                # 冲突条件：相同 concept 但 confidence 差距 > 0.3
                if abs(prev.confidence - item.confidence) > 0.3:
                    conflicts.append((prev, item))
            else:
                seen[key] = item
        if conflicts:
            logger.warning(
                f"[ContinuousLearningLoop] verify 发现 {len(conflicts)} 个冲突"
            )
        return conflicts

    def publish(self, num: int = 5) -> list[dict[str, Any]]:
        """发布最近巩固的知识到 PSI perceive 阶段。"""
        recent = self.long_term[-num:]
        published = []
        for item in recent:
            published.append({
                "concept": item.concept,
                "domain": item.domain,
                "confidence": item.confidence,
                "source": item.source,
            })
        # 通过 CognitiveBus 发布（若可用）
        try:
            from laap.agi.cognitive_bus import CognitiveBus
            bus = CognitiveBus()
            bus.publish(
                source="continuous_learning_loop",
                event_type="knowledge_published",
                payload={"items": published},
            )
        except Exception as e:
            logger.debug(f"[ContinuousLearningLoop] publish skipped: {e}")
        return published

    def _save(self) -> None:
        """持久化长期记忆。"""
        try:
            os.makedirs(os.path.dirname(self.knowledge_path), exist_ok=True)
            data = {
                "long_term": [asdict(k) for k in self.long_term[-1000:]],
                "saved_at": time.time(),
            }
            with open(self.knowledge_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str, indent=2)
        except Exception as e:
            logger.warning(f"[ContinuousLearningLoop] save failed: {e}")

    def _load(self) -> None:
        """加载长期记忆。"""
        try:
            if not os.path.exists(self.knowledge_path):
                return
            with open(self.knowledge_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in data.get("long_term", []):
                self.long_term.append(
                    KnowledgeItem(**{
                        key: val for key, val in k.items()
                        if key in KnowledgeItem.__dataclass_fields__
                    })
                )
        except Exception as e:
            logger.warning(f"[ContinuousLearningLoop] load failed: {e}")

    def stats(self) -> dict[str, Any]:
        """返回学习闭环统计。"""
        return {
            "short_term_size": len(self.short_term),
            "long_term_size": len(self.long_term),
            "consolidated": sum(1 for k in self.long_term if k.consolidated),
            "avg_confidence": (
                round(sum(k.confidence for k in self.long_term) /
                      max(1, len(self.long_term)), 3)
            ),
        }


# ═══════════════════════════════════════════════════════════════════════
# ASI 路径编排器
# ═══════════════════════════════════════════════════════════════════════

class ASIPath:
    """AGI → ASI 路径编排器：组合 4 条路径，提供单一入口。

    使用示例::

        asi = ASIPath(host_id="aris-1")
        asi.mind.broadcast_thought("启动 AGI 演化周期")
        asi.network.register_instance("aris-2", endpoint="tcp://...")
        asi.loop.ingest({"concept": "self-awareness", "source": "audit-v2"})
        asi.loop.consolidate()
        report = asi.cycle_report()
    """

    def __init__(self, host_id: str) -> None:
        self.host_id = host_id
        self.mind = UnifiedMind(host_id=host_id)
        self.network = DistributedMindNetwork()
        self.compiler = PsiLangCompiler()
        self.loop = ContinuousLearningLoop()
        # 自动注册到 Ψ-Net
        self.network.register_instance(host_id)

    def cycle_report(self) -> dict[str, Any]:
        """返回当前 ASI 路径推进状态报告。"""
        return {
            "host_id": self.host_id,
            "mind": self.mind.stats(),
            "network": self.network.stats(),
            "loop": self.loop.stats(),
            "timestamp": time.time(),
        }
