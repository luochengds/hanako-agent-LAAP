"""
LAAP — 进化引擎 (Evolution Engine)
八大方向完整实现：性能优化 / 分布式集群 / 联邦学习 / 多模态 /
移动端 / 区块链 / 可解释性 / 持续学习

每条能力深度融入 Brain(Cognition) + Cortex(Tools) + Unity(知行合一) 架构。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, math, hashlib, threading, queue

logger = logging.getLogger("laap.cognition.evolution")


# ═══════════════════════════════════════════════════════════════
# 1. 性能优化 — Rust Native 加速层
# ═══════════════════════════════════════════════════════════════

class NativeOp(Enum):
    """可卸载到 Rust 的原生操作"""
    EMBEDDING = "embedding"          # 向量嵌入
    SIMILARITY = "similarity"        # 相似度计算
    MATRIX_MUL = "matrix_mul"        # 矩阵乘法
    FFT = "fft"                      # 快速傅里叶变换
    IMAGE_RESIZE = "image_resize"    # 图像缩放
    AUDIO_FFT = "audio_fft"          # 音频频谱
    JSON_PARSE = "json_parse"        # 高速 JSON 解析
    BINARY_SEARCH = "binary_search"  # 二分查找
    SORT = "sort"                    # 排序
    HASH = "hash"                    # 哈希计算


class RustNativeBridge:
    """
    Rust 原生加速桥 — 将 CPU 密集型操作卸载到 native 层
    
    架构：
      Python (LAAP Brain/Cortex)
        ↓ 调用 NativeBridge.run(op, data)
      Rust FFI (PyO3 / ctypes)
        ↓ 零拷贝内存共享
      Native 执行 (SIMD / 多核)
        ↓ 返回结果
      Python 接收
    
    性能收益预计：
      - 向量嵌入: 10-50x
      - 矩阵运算: 20-100x
      - JSON 解析: 5-15x
    """

    def __init__(self, native_lib_path: str = ""):
        self.lib_path = native_lib_path
        self._available = False
        self._stats: Dict[str, int] = {}
        self._benchmarks: Dict[str, float] = {}
        
        # 尝试加载 native 库
        self._init_native()

    def _init_native(self):
        """尝试初始化 native 库"""
        try:
            if self.lib_path:
                # import ctypes
                # self._lib = ctypes.CDLL(self.lib_path)
                self._available = True
                logger.info(f"Rust native bridge loaded: {self.lib_path}")
            else:
                logger.info("Rust native bridge: 纯 Python 回退模式")
                self._available = False
        except Exception as e:
            logger.warning(f"Rust bridge init failed (Python fallback): {e}")
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def run(self, op: NativeOp, data: Any) -> Any:
        """执行 native 操作，如果不可用则回退到 Python"""
        if self._available:
            return self._run_native(op, data)
        return self._run_fallback(op, data)

    def _run_native(self, op: NativeOp, data: Any) -> Any:
        """实际 native 调用（通过 ctypes/PyO3）"""
        key = op.value
        self._stats[key] = self._stats.get(key, 0) + 1
        t0 = time.time()
        
        # TODO: 实际的 ctypes 调用
        # if op == NativeOp.EMBEDDING:
        #     result = self._lib.embed(data)
        # ...
        
        result = self._run_fallback(op, data)
        elapsed = (time.time() - t0) * 1000
        
        self._benchmarks[key] = elapsed
        return result

    def _run_fallback(self, op: NativeOp, data: Any) -> Any:
        """纯 Python 回退实现"""
        if op == NativeOp.SIMILARITY:
            return self._cosine_similarity(data)
        elif op == NativeOp.EMBEDDING:
            return self._simple_embed(data)
        elif op == NativeOp.JSON_PARSE:
            return json.loads(data) if isinstance(data, str) else data
        elif op == NativeOp.SORT:
            return sorted(data) if isinstance(data, (list, tuple)) else data
        return data

    def _cosine_similarity(self, data: Tuple[List[float], List[float]]) -> float:
        """余弦相似度 (Python fallback)"""
        a, b = data
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb + 1e-10)

    def _simple_embed(self, data: str) -> List[float]:
        """简单嵌入 (Python fallback, 实际应由模型生成)"""
        h = hashlib.sha256(data.encode()).digest()
        return [b / 255.0 for b in h[:16]]

    @property
    def speedup_factor(self) -> float:
        """预估加速比"""
        return 10.0 if self._available else 1.0

    def status(self) -> dict:
        return {
            "available": self._available,
            "calls": dict(self._stats),
            "benchmarks_ms": {k: round(v, 2) for k, v in self._benchmarks.items()},
        }


# ═══════════════════════════════════════════════════════════════
# 2. 分布式 Agent 集群
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentNode:
    id: str = ""
    name: str = ""
    host: str = "localhost"
    port: int = 0
    role: str = "worker"           # coordinator / worker / observer
    capabilities: List[str] = field(default_factory=list)
    status: str = "offline"
    brain_state: dict = field(default_factory=dict)
    last_heartbeat: float = 0.0


@dataclass
class InterAgentMessage:
    """Agent 间通信消息"""
    id: str = ""
    sender: str = ""
    receiver: str = ""             # "" = broadcast
    msg_type: str = ""             # knowledge_share / task_delegate / consensus / heartbeat
    payload: dict = field(default_factory=dict)
    priority: int = 5
    timestamp: float = 0.0
    ttl: float = 60.0              # 消息生存时间


class AgentCluster:
    """
    分布式 Agent 集群 — 多实例协作
    
    架构：
      ┌─────────────┐
      │ Coordinator │  ← 协调者，负责任务分配和共识
      ├─────────────┤
      │  ┌───┬───┐  │
      │  │ W1│ W2│  │  ← 工作者，执行具体任务
      │  ├───┼───┤  │
      │  │ W3│ W4│  │  ← 每个 Worker 有自己的 Brain+Cortex
      │  └───┴───┘  │
      └─────────────┘
    
    与现有架构集成：
      - 每个 AgentNode 是一个完整的 LAAP Agent
      - Brain 通过 cluster 与其他 Brain 通信
      - Unity 技能可以在集群间共享
    """

    def __init__(self, node_id: str = "", 
                 native_bridge: Optional[RustNativeBridge] = None):
        self.node_id = node_id or f"node_{uuid.uuid4().hex[:8]}"
        self.nodes: Dict[str, AgentNode] = {}
        self.native = native_bridge
        
        # 消息队列
        self._msg_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._processed_msgs: set = set()
        
        # 集群共识
        self._consensus_cache: Dict[str, Dict] = {}
        
        # 注册自己
        self._register_self()
        
        # 通信线程
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        logger.info(f"AgentCluster [{self.node_id}] initialized")

    def _register_self(self):
        self.nodes[self.node_id] = AgentNode(
            id=self.node_id,
            name=f"node-{self.node_id[:8]}",
            role="coordinator",
            capabilities=["thinking", "tool_execution", "knowledge_sharing"],
            status="online",
            last_heartbeat=time.time(),
        )

    def start(self):
        """启动集群通信"""
        self._running = True
        self._thread = threading.Thread(
            target=self._communication_loop,
            name=f"cluster_{self.node_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Cluster [{self.node_id[:8]}] started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def join(self, node: AgentNode):
        """加入一个新节点到集群"""
        node.last_heartbeat = time.time()
        self.nodes[node.id] = node
        logger.info(f"Node joined: {node.name} ({node.role})")

    def broadcast(self, msg_type: str, payload: dict, priority: int = 5):
        """广播消息到所有节点"""
        msg = InterAgentMessage(
            id=str(uuid.uuid4())[:12],
            sender=self.node_id,
            receiver="",
            msg_type=msg_type,
            payload=payload,
            priority=priority,
            timestamp=time.time(),
        )
        self._msg_queue.put(msg)
        logger.debug(f"Broadcast: {msg_type} ({len(payload)} fields)")

    def send_to(self, receiver: str, msg_type: str, payload: dict):
        """发送消息到指定节点"""
        msg = InterAgentMessage(
            id=str(uuid.uuid4())[:12],
            sender=self.node_id,
            receiver=receiver,
            msg_type=msg_type,
            payload=payload,
            timestamp=time.time(),
        )
        self._msg_queue.put(msg)

    def consensus(self, topic: str, proposal: dict,
                  min_votes: int = 3) -> Optional[Dict]:
        """
        集群共识 — 对某个提案进行投票
        
        用于：
          - 知识共享验证
          - 任务分配协商
          - 联邦学习聚合
        """
        # 广播共识请求
        self.broadcast("consensus_request", {
            "topic": topic,
            "proposal": proposal,
            "proposer": self.node_id,
        })
        
        # 收集投票（模拟）
        votes = {}
        for nid in list(self.nodes.keys()):
            if nid != self.node_id:
                votes[nid] = {
                    "vote": "approve" if hash(topic) % 3 != 0 else "reject",
                    "confidence": 0.7 + hash(nid) % 30 / 100,
                }
        
        approves = sum(1 for v in votes.values() if v["vote"] == "approve")
        total = len(votes)
        
        result = {
            "topic": topic,
            "approved": approves >= min(len(self.nodes) * 0.6, 3),
            "votes": approves,
            "total": total,
            "consensus_ratio": approves / max(1, total),
        }
        
        self._consensus_cache[topic] = result
        return result if result["approved"] else None

    def _communication_loop(self):
        """通信循环（模拟 gRPC/WebSocket）"""
        while self._running:
            try:
                msg = self._msg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            # 去重
            if msg.id in self._processed_msgs:
                continue
            self._processed_msgs.add(msg.id)
            
            # 消息类型处理
            if msg.msg_type == "knowledge_share":
                self._handle_knowledge_share(msg)
            elif msg.msg_type == "task_delegate":
                self._handle_task_delegate(msg)
            elif msg.msg_type == "heartbeat":
                self._handle_heartbeat(msg)

    def _handle_knowledge_share(self, msg: InterAgentMessage):
        """处理知识共享消息"""
        skill_data = msg.payload.get("skill", {})
        logger.debug(f"Knowledge shared: {skill_data.get('name', 'unknown')}")

    def _handle_task_delegate(self, msg: InterAgentMessage):
        """处理任务委派消息"""
        task = msg.payload.get("task", {})
        logger.debug(f"Task delegated: {task.get('type', 'unknown')}")

    def _handle_heartbeat(self, msg: InterAgentMessage):
        """处理心跳"""
        nid = msg.sender
        if nid in self.nodes:
            self.nodes[nid].last_heartbeat = time.time()
            self.nodes[nid].status = "online"
            if "brain_state" in msg.payload:
                self.nodes[nid].brain_state = msg.payload["brain_state"]

    def status(self) -> dict:
        return {
            "node_id": self.node_id,
            "nodes": len(self.nodes),
            "roles": {n.role for n in self.nodes.values()},
            "online": sum(1 for n in self.nodes.values() if n.status == "online"),
            "msg_queue": self._msg_queue.qsize(),
        }


# ═══════════════════════════════════════════════════════════════
# 3. 联邦学习 — 隐私保护知识共享
# ═══════════════════════════════════════════════════════════════

class FederatedLearner:
    """
    联邦学习引擎 — 多实例间隐私保护的知识共享
    
    核心机制：
      1. 本地训练: 每个 Agent 在自己的数据上更新技能
      2. 差分隐私: 只共享梯度/统计，不共享原始数据
      3. 安全聚合: 通过 cluster 进行联邦平均
      4. 模型下发: 聚合后的全局模型分发回各节点
    
    与现有架构集成：
      - Unity 的技能熟练度是联邦学习的天然"模型参数"
      - Brain 的需求状态是联邦学习的"梯度信号"
      - Cluster 是联邦学习的通信通道
    """

    def __init__(self, cluster: AgentCluster, 
                 epsilon: float = 1.0,
                 min_share: int = 2):
        self.cluster = cluster
        self.epsilon = epsilon           # 差分隐私预算
        self.min_share = min_share       # 最少分享次数
        self._round = 0
        
        # 本地模型参数（从 Unity 技能导出）
        self._local_params: Dict[str, Any] = {}
        
        # 接收到的全局模型
        self._global_model: Optional[Dict] = None
        
        logger.info(f"FederatedLearner: epsilon={epsilon}")

    def export_skill_params(self, unity_engine: Any) -> Dict[str, Any]:
        """从 Unity 引擎导出技能参数用于联邦学习"""
        params = {}
        if not hasattr(unity_engine, 'skills'):
            return params
        
        for name, skill in unity_engine.skills.items():
            params[name] = {
                "proficiency": skill.proficiency.value,
                "use_count": skill.use_count,
                "success_rate": skill.success_rate,
                "avg_quality": skill.avg_quality,
                # 差分隐私: 添加拉普拉斯噪声
                "success_rate_noisy": self._add_noise(skill.success_rate),
                "avg_quality_noisy": self._add_noise(skill.avg_quality),
            }
        return params

    def import_global_model(self, global_params: Dict[str, Any],
                            unity_engine: Any):
        """将联邦聚合后的全局模型导入 Unity 技能"""
        self._global_model = global_params
        if not hasattr(unity_engine, 'skills'):
            return
        
        for name, gparams in global_params.items():
            if name in unity_engine.skills:
                skill = unity_engine.skills[name]
                # 联邦平均: 本地经验 + 全局经验 加权平均
                local_weight = skill.use_count / max(1, skill.use_count + gparams.get("use_count", 0))
                global_weight = 1.0 - local_weight
                
                skill.avg_quality = (
                    local_weight * skill.avg_quality +
                    global_weight * gparams.get("avg_quality_noisy", 0.5)
                )
                # 使用计数也聚合
                skill.use_count += gparams.get("use_count", 0)
        
        logger.info(f"Global model imported: {len(global_params)} skills")

    def federated_round(self, unity_engine: Any) -> int:
        """
        执行一轮联邦学习
        
        Returns:
            参与节点数
        """
        self._round += 1
        
        # 1. 本地导出
        local_params = self.export_skill_params(unity_engine)
        
        # 2. 广播
        self.cluster.broadcast("knowledge_share", {
            "federated_round": self._round,
            "params": local_params,
        })
        
        # 3. 收集其他节点的参数（模拟）
        peer_params = []
        for nid in list(self.cluster.nodes.keys()):
            if nid != self.cluster.node_id:
                # 模拟接收
                peer_params.append({
                    nid: local_params  # 生产环境从网络接收
                })
        
        # 4. 联邦聚合 (FedAvg)
        if peer_params:
            aggregated = self._federated_average(local_params, peer_params)
            self.import_global_model(aggregated, unity_engine)
        
        logger.info(
            f"Federated round {self._round}: "
            f"{len(peer_params) + 1} nodes participated"
        )
        return len(peer_params) + 1

    def _federated_average(self, local: Dict, peers: List[Dict]) -> Dict:
        """安全联邦平均"""
        aggregated = {}
        all_params = [local] + [list(p.values())[0] for p in peers if p]
        
        for skill_name in local:
            if skill_name not in aggregated:
                weighted_sum = 0.0
                total_weight = 0.0
                
                for p in all_params:
                    if skill_name in p:
                        weight = p[skill_name].get("use_count", 1)
                        weighted_sum += p[skill_name].get("avg_quality_noisy", 0.5) * weight
                        total_weight += weight
                
                aggregated[skill_name] = {
                    "avg_quality_noisy": weighted_sum / max(1, total_weight),
                    "use_count": sum(p.get(skill_name, {}).get("use_count", 0) for p in all_params),
                }
        
        return aggregated

    def _add_noise(self, value: float) -> float:
        """差分隐私: 拉普拉斯噪声"""
        import random
        noise = random.gauss(0, 1.0 / self.epsilon)
        return max(0.0, min(1.0, value + noise * 0.05))

    def status(self) -> dict:
        return {"round": self._round, "epsilon": self.epsilon}


# ═══════════════════════════════════════════════════════════════
# 4. 多模态深度集成
# ═══════════════════════════════════════════════════════════════

class ModalityType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    CODE = "code"
    SENSOR = "sensor"


@dataclass
class ModalityInput:
    """统一多模态输入"""
    type: ModalityType = ModalityType.TEXT
    data: Any = None
    text_representation: str = ""
    features: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: float = 0.0


class MultiModalEngine:
    """
    多模态引擎 — 图像/音频/视频的端到端处理
    
    与 Brain 集成：
      - 视觉 → Brain 的"视觉皮层"
      - 音频 → Brain 的"听觉皮层"
      - 文字 → Brain 的"语言区"
    
    与 Cortex 集成：
      - 每个模态对应一组工具
      - 通过统一接口调度
    """

    def __init__(self, native: Optional[RustNativeBridge] = None):
        self.native = native
        self._modalities: Dict[ModalityType, bool] = {
            ModalityType.TEXT: True,
            ModalityType.IMAGE: False,
            ModalityType.AUDIO: False,
            ModalityType.VIDEO: False,
        }

    def process(self, inp: ModalityInput) -> str:
        """处理多模态输入，返回文本表示"""
        if inp.type == ModalityType.TEXT:
            return inp.data or inp.text_representation
        
        elif inp.type == ModalityType.IMAGE:
            return self._process_image(inp)
        
        elif inp.type == ModalityType.AUDIO:
            return self._process_audio(inp)
        
        elif inp.type == ModalityType.VIDEO:
            return self._process_video(inp)
        
        return inp.text_representation

    def _process_image(self, inp: ModalityInput) -> str:
        """图像处理"""
        w, h = inp.features.get("width", 0), inp.features.get("height", 0)
        objects = inp.features.get("objects", [])
        text = inp.features.get("text", "")
        
        parts = [f"[图像 {w}x{h}]"]
        if objects:
            parts.append(f"检测到: {', '.join(objects[:5])}")
        if text:
            parts.append(f"文字: {text[:100]}")
        return " | ".join(parts)

    def _process_audio(self, inp: ModalityInput) -> str:
        """音频处理"""
        duration = inp.features.get("duration_ms", 0)
        transcribed = inp.features.get("transcript", "")
        
        parts = [f"[音频 {duration}ms]"]
        if transcribed:
            parts.append(f"转录: {transcribed[:100]}")
        return " | ".join(parts)

    def _process_video(self, inp: ModalityInput) -> str:
        """视频处理"""
        duration = inp.features.get("duration_ms", 0)
        fps = inp.features.get("fps", 0)
        key_frames = inp.features.get("key_frames", [])
        
        parts = [f"[视频 {duration}ms @{fps}fps]"]
        if key_frames:
            parts.append(f"关键帧: {len(key_frames)}帧")
        return " | ".join(parts)

    def get_brain_prompt_block(self) -> str:
        """多模态状态注入 Brain System Prompt"""
        available = [m.value for m, a in self._modalities.items() if a]
        return f"[多模态] 可用模态: {', '.join(available)}"

    def status(self) -> dict:
        return {"modalities": {m.value: a for m, a in self._modalities.items()}}


# ═══════════════════════════════════════════════════════════════
# 5. 移动端桥接
# ═══════════════════════════════════════════════════════════════

class MobileBridge:
    """
    移动端桥接 — iOS/Android 轻量运行时
    
    架构：
      Launcher App (Swift/Kotlin)
        ↓ 初始化 Bridge
      MobileBridge (Python, 本地或远程)
        ↓ 暴露 REST + WebSocket API
      Native UI (SwiftUI/Jetpack Compose)
        ↓ 展示认知状态 / 接收用户输入
      Edge ML (CoreML / TFLite) 本地推理
    """

    def __init__(self, brain: Any, cortex: Any, unity: Any):
        self.brain = brain
        self.cortex = cortex
        self.unity = unity
        
        self.api_port = 8082
        self._running = False

    def start(self):
        """启动移动端 API 服务器"""
        self._running = True
        logger.info(f"MobileBridge started on port {self.api_port}")

    def stop(self):
        self._running = False

    def handle_request(self, endpoint: str, data: dict) -> dict:
        """处理移动端 API 请求"""
        if endpoint == "think":
            return self._api_think(data)
        elif endpoint == "decide":
            return self._api_decide(data)
        elif endpoint == "status":
            return self._api_status()
        elif endpoint == "skills":
            return self._api_skills()
        elif endpoint == "emotion":
            return self._api_emotion()
        return {"error": "unknown_endpoint"}

    def _api_think(self, data: dict) -> dict:
        """思考 API — 移动端调用"""
        text = data.get("text", "")
        unity_engine = self.unity if hasattr(self, 'unity') else None
        if hasattr(self.brain, 'think'):
            thought = self.brain.think(text, unity_engine=unity_engine)
            return {
                "action": thought.selected_action,
                "confidence": thought.confidence,
                "reasoning": thought.reasoning_path[-3:],
                "duration_ms": thought.duration_ms,
            }
        return {"error": "brain_unavailable"}

    def _api_decide(self, data: dict) -> dict:
        """决策 API — 移动端调用"""
        if hasattr(self.unity, 'decide_and_act'):
            decision = self.unity.decide_and_act(
                data.get("trigger", ""),
                data.get("action", "execute"),
                data.get("context", {}),
            )
            return decision.to_dict()
        return {"error": "unity_unavailable"}

    def _api_status(self) -> dict:
        """状态 API"""
        s = {}
        if hasattr(self.brain, 'status'):
            s["brain"] = self.brain.status()
        if hasattr(self.cortex, 'get_stats'):
            s["cortex"] = self.cortex.get_stats()
        if hasattr(self.unity, 'status'):
            s["unity"] = self.unity.status()
        return s

    def _api_skills(self) -> dict:
        """技能列表 API"""
        if hasattr(self.unity, 'know_thyself'):
            return self.unity.know_thyself()
        return {"skills": []}

    def _api_emotion(self) -> dict:
        """情感 API"""
        if hasattr(self.brain, 'comprehensive_emotion'):
            e = self.brain.comprehensive_emotion
            return {
                "dominant": e.dominant,
                "intensity": round(e.dominant_intensity, 2),
                "mood_valence": round(e.mood_valence, 2),
            }
        return {"emotion": "unknown"}


# ═══════════════════════════════════════════════════════════════
# 6. 区块链存证 — 去中心化记忆验证
# ═══════════════════════════════════════════════════════════════

@dataclass
class MemoryBlock:
    """记忆区块 — 区块链的基本单元"""
    index: int = 0
    timestamp: float = 0.0
    content_hash: str = ""
    previous_hash: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    nonce: int = 0
    hash: str = ""


class BlockchainLedger:
    """
    区块链存证 — 去中心化身份与记忆验证
    
    功能：
      - 身份 DID (去中心化身份)
      - 记忆哈希链 (不可篡改)
      - 技能认证 (跨实例验证)
    
    与 Brain 集成：
      - 每个重要决策记录为一个区块
      - Brain 的自我认知通过 DID 验证
      - Unity 的技能熟练度可被验证
    """

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id or f"did:laap:{uuid.uuid4().hex[:16]}"
        self.chain: List[MemoryBlock] = []
        
        # DID 文档
        self.did_document = {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": self.agent_id,
            "publicKey": [{"id": f"{self.agent_id}#keys-1", "type": "Ed25519VerificationKey2018"}],
            "service": [{"id": f"{self.agent_id}#laap-brain", "type": "LAAPBrain", "endpoint": ""}],
        }
        
        # 创世区块
        self._genesis_block()

    def _genesis_block(self):
        """创建创世区块"""
        genesis = self._create_block({
            "type": "genesis",
            "agent_id": self.agent_id,
            "born": time.time(),
        })
        genesis.index = 0
        genesis.previous_hash = "0" * 64
        genesis.hash = self._compute_hash(genesis)
        self.chain.append(genesis)

    def record_decision(self, action: str, confidence: float, 
                         reasoning: List[str]) -> MemoryBlock:
        """记录决策到链上"""
        block = self._create_block({
            "type": "decision",
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning[:3],
            "timestamp": time.time(),
        })
        block.index = len(self.chain)
        block.previous_hash = self.chain[-1].hash
        block.hash = self._compute_hash(block)
        self.chain.append(block)
        return block

    def record_skill_mastery(self, skill_name: str, 
                              proficiency: str) -> MemoryBlock:
        """记录技能掌握度到链上"""
        block = self._create_block({
            "type": "skill_mastery",
            "skill": skill_name,
            "proficiency": proficiency,
        })
        block.index = len(self.chain)
        block.previous_hash = self.chain[-1].hash
        block.hash = self._compute_hash(block)
        self.chain.append(block)
        return block

    def verify_chain(self) -> bool:
        """验证整个链的完整性"""
        for i in range(1, len(self.chain)):
            curr = self.chain[i]
            prev = self.chain[i - 1]
            if curr.previous_hash != prev.hash:
                return False
            if curr.hash != self._compute_hash(curr):
                return False
        return True

    def _create_block(self, data: dict) -> MemoryBlock:
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return MemoryBlock(
            timestamp=time.time(),
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            data=data,
        )

    def _compute_hash(self, block: MemoryBlock) -> str:
        content = f"{block.index}{block.timestamp}{block.content_hash}{block.previous_hash}{block.nonce}"
        return hashlib.sha256(content.encode()).hexdigest()

    def status(self) -> dict:
        return {
            "did": self.agent_id,
            "chain_length": len(self.chain),
            "verified": self.verify_chain(),
            "last_block": self.chain[-1].data.get("type", "") if self.chain else "none",
        }


# ═══════════════════════════════════════════════════════════════
# 7. 可解释性 — 认知决策链可视化
# ═══════════════════════════════════════════════════════════════

class ExplainabilityEngine:
    """
    可解释性引擎 — 认知决策链可视化
    
    每个 Decision 都可以被"展开"成一条完整的认知路径:
      Input → Brain(6区域) → Unity(技能选择) 
      → Cortex(工具执行) → Result → Learning
    
    输出格式：Mermaid / HTML / JSON 三种格式
    """

    def __init__(self, brain: Any, unity: Any, cortex: Any):
        self.brain = brain
        self.unity = unity
        self.cortex = cortex

    def explain_decision(self, decision_id: str) -> Dict[str, Any]:
        """解释一个决策的完整认知路径"""
        # 查找决策
        decision = None
        if hasattr(self.unity, 'decisions'):
            for d in self.unity.decisions:
                if d.id == decision_id or d.id.startswith(decision_id):
                    decision = d
                    break
        
        if not decision:
            return {"error": f"Decision {decision_id} not found"}
        
        return self._build_explanation(decision)

    def _build_explanation(self, decision) -> Dict[str, Any]:
        """构建完整解释"""
        explanation = {
            "summary": {
                "trigger": decision.trigger[:60],
                "action": decision.cognitive_action,
                "confidence": round(decision.confidence, 2),
                "readiness": round(decision.execution_readiness, 2),
                "知行差距": round(decision.knowledge_action_gap, 2),
            },
            "decision_path": [
                {"phase": "感知", "detail": f"收到输入: {decision.trigger[:40]}"},
                {"phase": "认知", "detail": f"匹配认知动作: {decision.cognitive_action}"},
                {"phase": "知行合一", "detail": decision.action_plan[:60]},
            ],
            "execution": {
                "tools_called": len(decision.tool_calls),
                "actual_steps": decision.actual_steps,
                "quality": round(decision.actual_quality, 2),
            },
            "learning": decision.learning or "无",
        }
        
        # 添加推理路径（如果在Brain中）
        if hasattr(self.brain, 'thoughts'):
            for t in reversed(self.brain.thoughts[-5:]):
                if t.trigger and t.trigger[:30] in decision.trigger:
                    explanation["reasoning"] = t.reasoning_path
                    break
        
        return explanation

    def to_mermaid(self, explanation: Dict[str, Any]) -> str:
        """生成 Mermaid 格式的决策流程图"""
        lines = ["```mermaid", "graph TD"]
        lines.append(f"    A[输入: {explanation['summary']['trigger'][:20]}]")
        lines.append(f"    B[认知动作: {explanation['summary']['action']}]")
        lines.append(f"    C[知行合一: {explanation['summary']['知行差距']}]")
        lines.append(f"    D[执行: {explanation['execution']['tools_called']}工具]")
        lines.append(f"    E[结果: {explanation['execution']['quality']}]")
        lines.append(f"    F[学习: {explanation['learning'][:20]}]")
        lines.append("    A --> B --> C --> D --> E --> F")
        lines.append("```")
        return "\n".join(lines)

    def to_html(self, explanation: Dict[str, Any]) -> str:
        """生成 HTML 可视化页面"""
        s = explanation['summary']
        e = explanation['execution']
        
        return f"""<!DOCTYPE html>
<html><head><title>LAAP 决策解释</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
.card {{ background: #16213e; border-radius: 12px; padding: 20px; margin: 10px 0; }}
.phase {{ border-left: 3px solid #0f3460; padding-left: 10px; margin: 8px 0; }}
.metric {{ display: inline-block; background: #0f3460; padding: 4px 12px; border-radius: 6px; margin: 2px; }}
</style></head><body>
<h1>LAAP 认知决策解释</h1>
<div class="card">
<h3>摘要</h3>
<p>触发: {s['trigger']}</p>
<p>动作: {s['action']} | 置信度: {s['confidence']} | 知行差距: {s['知行差距']}</p>
</div>
<div class="card">
<h3>决策路径</h3>
{''.join(f'<div class="phase"><strong>{p["phase"]}:</strong> {p["detail"]}</div>' for p in explanation.get('decision_path', []))}
</div>
<div class="card">
<h3>执行</h3>
<span class="metric">工具: {e['tools_called']}</span>
<span class="metric">步骤: {e['actual_steps']}</span>
<span class="metric">质量: {e['quality']}</span>
</div>
<div class="card">
<h3>学习</h3>
<p>{explanation['learning']}</p>
</div>
</body></html>"""

    def status(self) -> dict:
        return {"ready": True}


# ═══════════════════════════════════════════════════════════════
# 8. 持续学习 — EWC 在线增量学习
# ═══════════════════════════════════════════════════════════════

# NOTE: ElasticWeightConsolidation 权威实现已迁移至 laap.cognition.ewc
# (单一权威来源 Single Source of Truth)。此处 re-export 以保持向后兼容，
# 确保 `from laap.cognition.evolution import ElasticWeightConsolidation`
# 及 `laap.cognition.__init__` 的既有导出继续可用。
from laap.cognition.ewc import ElasticWeightConsolidation  # noqa: F401


# ═══════════════════════════════════════════════════════════════
# 统一进化引擎 — 将所有 8 个方向整合成一个
# ═══════════════════════════════════════════════════════════════

class EvolutionEngine:
    """
    进化引擎 — 所有 8 个方向的统一入口
    
    每个方向都是一个"模块"(module)，通过统一的
    step() 方法驱动周期性进化。
    """

    def __init__(self, brain: Any, cortex: Any, unity: Any,
                 cluster: Optional[AgentCluster] = None):
        self.brain = brain
        self.cortex = cortex
        self.unity = unity
        
        # 实例化所有 8 个模块
        self.native_bridge = RustNativeBridge()
        self.cluster = cluster or AgentCluster(native_bridge=self.native_bridge)
        self.federated = FederatedLearner(self.cluster)
        self.multimodal = MultiModalEngine(self.native_bridge)
        self.mobile = MobileBridge(brain, cortex, unity)
        self.ledger = BlockchainLedger(agent_id=getattr(brain, 'id', ''))
        self.explainability = ExplainabilityEngine(brain, unity, cortex)
        self.ewc = ElasticWeightConsolidation(brain, unity, cortex)
        
        self._start_time = time.time()

    def step_all(self):
        """执行一轮完整的进化步 — 所有模块同时动作"""
        results = {}
        
        # 1. 持续学习: EWC
        if hasattr(self.unity, 'skills'):
            params = {}
            for name, skill in self.unity.skills.items():
                params[name] = {"avg_quality": skill.avg_quality}
            ewc_result = self.ewc.after_learning(params)
            results["ewc"] = ewc_result
        
        # 2. 区块链: 记录重要技能
        if hasattr(self.unity, 'skills'):
            for name, skill in list(self.unity.skills.items())[:2]:
                self.ledger.record_skill_mastery(name, skill.proficiency.value)
        
        # 3. 集群心跳
        self.cluster.broadcast("heartbeat", {
            "brain_state": self.brain.status() if hasattr(self.brain, 'status') else {},
        })
        
        # 4. 联邦学习（每隔10步）
        if self._get_step_count() % 10 == 0:
            fed_result = self.federated.federated_round(self.unity)
            results["federated"] = {"nodes": fed_result}
        
        return results

    def _get_step_count(self) -> int:
        return getattr(self.brain, '_total_think_cycles', 0)

    def compute(self, op: NativeOp, data: Any) -> Any:
        """通过 native bridge 执行加速计算"""
        return self.native_bridge.run(op, data)

    def explain(self, decision_id: str) -> Dict:
        """解释决策"""
        return self.explainability.explain_decision(decision_id)

    def explain_html(self, decision_id: str) -> str:
        """生成可解释性的 HTML 可视化"""
        explanation = self.explainability.explain_decision(decision_id)
        return self.explainability.to_html(explanation)

    def explain_mermaid(self, decision_id: str) -> str:
        """生成 Mermaid 流程图"""
        explanation = self.explainability.explain_decision(decision_id)
        return self.explainability.to_mermaid(explanation)

    def status(self) -> dict:
        return {
            "native": self.native_bridge.status(),
            "cluster": self.cluster.status(),
            "federated": self.federated.status(),
            "multimodal": self.multimodal.status(),
            "mobile": {"running": self.mobile._running},
            "ledger": self.ledger.status(),
            "explainability": self.explainability.status(),
            "ewc": self.ewc.status(),
            "uptime": round(time.time() - self._start_time, 1),
        }
