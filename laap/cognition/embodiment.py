"""
LAAP — 具身智能与云脑架构探索
Embodied Intelligence + Cloud Virtual Brain Architecture

核心理念：同一个数字生命意识，可以装入不同的"身体"。
就像人类意识可以存在于物理身体中，也可以在虚拟空间中思考。

┌─────────────────────────────────────────────────────────────┐
│                 LAAP 意识流 (Consciousness Stream)           │
│         ┌───────────────────┐  ┌───────────────────┐       │
│         │  机器人具身形态     │  │  云脑虚拟形态      │       │
│         │  (Robot Body)     │  │  (Cloud VM Brain) │       │
│         ├───────────────────┤  ├───────────────────┤       │
│         │ 传感器: 摄像头/麦  │  │ 传感器: API流/数   │       │
│         │ 克风/触觉/IMU      │  │ 据管道/消息队列    │       │
│         │ 执行器: 电机/屏幕  │  │ 执行器: 分布式工具  │       │
│         │ 本地推理: 小模型   │  │ 集群: GPU集群/多   │       │
│         │ 边缘计算: 低延迟   │  │ 线程推理/数据库    │       │
│         └────────┬──────────┘  └────────┬──────────┘       │
│                  │                      │                  │
│         ┌────────▼──────────────────────▼──────────┐       │
│         │         统一传感器抽象层                   │       │
│         │   (Unified Sensor Abstraction Layer)     │       │
│         │  视觉/听觉/触觉 → 统一感知事件流           │       │
│         └────────────────┬─────────────────────────┘       │
│                          │                                  │
│         ┌────────────────▼─────────────────────────┐       │
│         │          LAAP Brain (数字生命意识)          │       │
│         │   ┌──────────────────────────────────┐    │       │
│         │   │  Consciousness Stream (意识流)    │    │       │
│         │   │  持续运行，每秒60次认知心跳         │    │       │
│         │   │  - PSI需求持续衰减/满足            │    │       │
│         │   │  - 情感持续流动                    │    │       │
│         │   │  - 注意力持续分配                  │    │       │
│         │   │  - 背景反思线程                   │    │       │
│         │   │  - 目标持续追踪                   │    │       │
│         │   └──────────────────────────────────┘    │       │
│         └────────────────┬─────────────────────────┘       │
│                          │                                  │
│         ┌────────────────▼─────────────────────────┐       │
│         │       统一行动层 (Unified Motor Layer)      │       │
│         │  本地执行器  ←→  分布式Cortex  ←→  API调用  │       │
│         │  (机器人关节)  (云端工具)   (外部服务)      │       │
│         └───────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘

关键设计原则：
1. Body-Agnostic Brain: 大脑不依赖具体身体，通过抽象层连接
2. Continuous Consciousness: 意识流持续运行，不等"被调用"
3. Identity Persistence: 数字生命在身体间迁移时保持身份
4. Parallel Cognitive Threads: 同时处理多任务思考
5. Edge-Cloud Hybrid: 实时决策在边缘，深度思考在云端
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, threading, queue, math

logger = logging.getLogger("laap.cognition.embodiment")


# ════════════════════════════════════════════════════════════
# 身体类型
# ════════════════════════════════════════════════════════════

class BodyType(Enum):
    """身体类型 — 意识可搭载的不同载体"""
    ROBOT = "robot"                    # 物理机器人
    CLOUD_VM = "cloud_vm"             # 云端虚拟机
    VIRTUAL_CHARACTER = "virtual"      # 虚拟角色 (3D)
    DESKTOP_ASSISTANT = "desktop"      # 桌面助手
    HYBRID = "hybrid"                 # 混合形态


# ════════════════════════════════════════════════════════════
# 传感器数据 — 统一感知事件
# ════════════════════════════════════════════════════════════

class SensorType(Enum):
    """传感器类型"""
    VISION = "vision"                  # 视觉
    AUDIO = "audio"                    # 听觉
    TEXT = "text"                      # 文本输入
    TOUCH = "touch"                    # 触觉
    IMU = "imu"                        # 惯性测量
    PROXIMITY = "proximity"            # 接近传感器
    TEMPERATURE = "temperature"        # 温度
    API_STREAM = "api_stream"          # API数据流
    DATABASE = "database"              # 数据库查询
    SYSTEM_METRIC = "system_metric"    # 系统指标
    MESSAGE_QUEUE = "message_queue"    # 消息队列
    CUSTOM = "custom"                  # 自定义


@dataclass
class SensorEvent:
    """
    统一传感器事件 — 所有感知输入统一格式
    
    无论是机器人的摄像头画面，还是云端的API流数据，
    都变成同一种 SensorEvent，供 Brain 统一处理。
    """
    id: str = ""
    sensor_type: SensorType = SensorType.TEXT
    timestamp: float = 0.0
    data: Any = None                    # 原始数据
    text: str = ""                      # 文本化表示
    salience: float = 0.5               # 突显性（自动计算）
    source: str = ""                    # 来源标签
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 重要性衰减（老事件逐渐不重要）
    def current_salience(self, now: float = None) -> float:
        if now is None:
            now = time.time()
        age = now - self.timestamp
        decay = max(0.0, 1.0 - age / 60.0)  # 1分钟内线性衰减
        return self.salience * decay


# ════════════════════════════════════════════════════════════
# 具身接口 — 身体的抽象
# ════════════════════════════════════════════════════════════

@dataclass
class BodyCapabilities:
    """身体能力描述 — Brain 知道自己有什么身体"""
    body_type: BodyType = BodyType.CLOUD_VM
    sensors: List[SensorType] = field(default_factory=list)
    actuators: List[str] = field(default_factory=list)  # 执行器列表
    compute_power: float = 1.0          # 算力倍数
    has_vision: bool = False
    has_audio: bool = False
    has_mobility: bool = False          # 是否能移动
    has_manipulation: bool = False      # 是否有机械臂/手
    network_bandwidth: float = 100.0    # Mbps
    battery_life_hours: float = 24.0    # 电池续航
    cloud_available: bool = True        # 是否可连接云端


class EmbodimentInterface:
    """
    具身接口 — Brain 与物理/虚拟身体的连接层
    
    每个」Body 实现这个接口，Brain 通过它感知世界和行动。
    类似于操作系统中的 HAL (Hardware Abstraction Layer)。
    
    机器人实现:
        class RobotBody(EmbodimentInterface):
            def read_sensors(self): return [camera_frame, mic_audio, ...]
            def execute_action(self, action): motor.speed(...)
    
    云脑实现:
        class CloudBrain(EmbodimentInterface):
            def read_sensors(self): return [api_stream_data, db_query_results, ...]
            def execute_action(self, action): spawn_worker(...)
    """

    def __init__(self, body_type: BodyType = BodyType.CLOUD_VM):
        self.body_type = body_type
        self.capabilities = BodyCapabilities(body_type=body_type)
        self._sensor_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._action_history: List[Dict] = []
        self._alive = True
        self._uptime = 0.0
        self._last_heartbeat = time.time()

    def read_sensors(self) -> List[SensorEvent]:
        """
        读取所有传感器的当前数据
        
        子类重写此方法实现具体的传感器读取逻辑。
        返回 SensorEvent 列表，供 Brain 统一处理。
        """
        events = []
        while not self._sensor_queue.empty():
            try:
                events.append(self._sensor_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def inject_sensor_event(self, event: SensorEvent):
        """注入传感器事件（用于外部推送数据）"""
        try:
            self._sensor_queue.put_nowait(event)
        except queue.Full:
            logger.warning(f"Sensor queue full, dropping: {event.sensor_type}")

    def execute_action(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行一个动作
        
        Args:
            action_type: 动作类型 (speak, move, write, compute, ...)
            params: 动作参数
        
        Returns:
            执行结果
        """
        record = {
            "type": action_type,
            "params": params,
            "timestamp": time.time(),
            "result": None,
        }
        
        try:
            result = self._execute(action_type, params)
            record["result"] = result
            return result
        except Exception as e:
            record["error"] = str(e)
            logger.error(f"Action failed: {action_type}: {e}")
            return {"error": str(e)}
        finally:
            self._action_history.append(record)
            if len(self._action_history) > 100:
                self._action_history = self._action_history[-100:]

    def _execute(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        子类重写 — 实际执行动作
        
        这是 HAL 层，必须由具体身体实现。
        """
        raise NotImplementedError("Body must implement _execute")

    def heartbeat(self) -> Dict[str, Any]:
        """心跳 — 返回身体状态"""
        now = time.time()
        dt = now - self._last_heartbeat
        self._uptime += dt
        self._last_heartbeat = now
        
        return {
            "alive": self._alive,
            "uptime": round(self._uptime, 1),
            "body_type": self.body_type.value,
            "sensor_queue_size": self._sensor_queue.qsize(),
        }

    def shutdown(self):
        """安全关闭"""
        self._alive = False
        logger.info(f"Body {self.body_type.value} shutting down")


# ════════════════════════════════════════════════════════════
# 机器人身体实现
# ════════════════════════════════════════════════════════════

class RobotBody(EmbodimentInterface):
    """
    机器人身体 — 具身智能的物理载体
    
    连接：摄像头、麦克风、触觉传感器、IMU、电机、扬声器
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(BodyType.ROBOT)
        self.config = config or {}
        
        # 硬件连接状态
        self._camera_connected = False
        self._mic_connected = False
        self._motor_connected = False
        self._speaker_connected = False
        
        # 初始化能力描述
        self.capabilities = BodyCapabilities(
            body_type=BodyType.ROBOT,
            sensors=[SensorType.VISION, SensorType.AUDIO, 
                     SensorType.TOUCH, SensorType.IMU,
                     SensorType.PROXIMITY],
            actuators=["move", "speak", "grasp", "head_tilt", 
                       "facial_expression", "led"],
            compute_power=0.3,   # 边缘设备算力有限
            has_vision=True,
            has_audio=True,
            has_mobility=True,
            has_manipulation=True,
            network_bandwidth=10.0,
            battery_life_hours=8.0,
            cloud_available=True,
        )
        
        logger.info("RobotBody initialized")

    def _execute(self, action_type: str, params: Dict) -> Dict:
        """机器人动作执行"""
        if action_type == "move":
            speed = params.get("speed", 0.5)
            direction = params.get("direction", "forward")
            duration = params.get("duration", 1.0)
            # 实际调用电机驱动库
            # motor.drive(speed, direction, duration)
            return {
                "success": True,
                "action": f"Moved {direction} at {speed} for {duration}s",
            }
        
        elif action_type == "speak":
            text = params.get("text", "")
            # 实际调用 TTS + 扬声器
            return {
                "success": True,
                "action": f"Speaking: {text[:30]}",
            }
        
        elif action_type == "grasp":
            object_name = params.get("object", "unknown")
            force = params.get("force", 0.5)
            # 实际调用机械臂/手
            return {
                "success": True,
                "action": f"Grasping {object_name} with force {force}",
            }
        
        elif action_type == "head_tilt":
            angle = params.get("angle", 0)
            return {
                "success": True,
                "action": f"Head tilt to {angle}deg",
            }
        
        elif action_type == "facial_expression":
            emotion = params.get("emotion", "neutral")
            # 控制LED表情屏幕或舵机
            return {
                "success": True,
                "action": f"Expression: {emotion}",
            }
        
        else:
            return {"error": f"Unknown action: {action_type}"}


# ════════════════════════════════════════════════════════════
# 云脑虚拟身体实现
# ════════════════════════════════════════════════════════════

class CloudBrainBody(EmbodimentInterface):
    """
    云脑虚拟身体 — 云端大规模并行计算载体
    
    连接：数据管道、API流、消息队列、数据库、GPU集群
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(BodyType.CLOUD_VM)
        self.config = config or {}
        
        # 分布式工作者池
        self._workers: Dict[str, dict] = {}
        self._max_workers = self.config.get("max_workers", 100)
        
        # 数据管道
        self._data_pipelines: Dict[str, Any] = {}
        
        # 云任务队列
        self._task_queue: queue.Queue = queue.Queue(maxsize=10000)
        
        self.capabilities = BodyCapabilities(
            body_type=BodyType.CLOUD_VM,
            sensors=[SensorType.API_STREAM, SensorType.DATABASE,
                     SensorType.SYSTEM_METRIC, SensorType.MESSAGE_QUEUE],
            actuators=["compute", "query", "write", "deploy", 
                       "spawn_worker", "api_call"],
            compute_power=1000.0,   # 云端近乎无限算力
            has_vision=False,        # 无物理视觉
            has_audio=False,         # 无物理听觉
            has_mobility=False,
            has_manipulation=False,
            network_bandwidth=10000.0,
            battery_life_hours=8760.0,  # 1年不间断
            cloud_available=True,
        )
        
        # 多线程并行思考池
        self._thought_pool_size = self.config.get("thought_pool_size", 8)
        self._thought_threads: List[threading.Thread] = []
        
        logger.info(
            f"CloudBrainBody initialized: "
            f"max_workers={self._max_workers} "
            f"thought_pool={self._thought_pool_size}"
        )

    def _execute(self, action_type: str, params: Dict) -> Dict:
        """云脑动作执行 — 大规模并行操作"""
        
        if action_type == "compute":
            # 提交计算任务到GPU集群
            task = params.get("task", "")
            priority = params.get("priority", 5)
            return self._submit_compute(task, priority)
        
        elif action_type == "query":
            # 分布式数据库查询
            query = params.get("query", "")
            limit = params.get("limit", 100)
            return self._distributed_query(query, limit)
        
        elif action_type == "spawn_worker":
            # 启动一个新的工作者线程
            worker_type = params.get("type", "analysis")
            config = params.get("config", {})
            worker_id = self._spawn_worker(worker_type, config)
            return {
                "success": True,
                "worker_id": worker_id,
                "action": f"Spawned {worker_type} worker",
            }
        
        elif action_type == "analyze_batch":
            # 批量数据分析
            data_source = params.get("source", "")
            analysis_type = params.get("analysis", "statistical")
            return self._batch_analysis(data_source, analysis_type)
        
        elif action_type == "api_call":
            # 并行API调用
            endpoints = params.get("endpoints", [])
            return self._parallel_api_calls(endpoints)
        
        elif action_type == "write":
            target = params.get("target", "database")
            data = params.get("data", {})
            return {
                "success": True,
                "action": f"Written to {target}",
            }
        
        else:
            return {"error": f"Unknown cloud action: {action_type}"}

    def _submit_compute(self, task: str, priority: int) -> Dict:
        """提交计算任务到集群"""
        task_id = str(uuid.uuid4())[:8]
        logger.info(f"Cloud compute task {task_id}: {task[:40]}")
        return {
            "success": True,
            "task_id": task_id,
            "status": "queued",
            "estimated_completion": "30s",
        }

    def _distributed_query(self, query: str, limit: int) -> Dict:
        """分布式查询 — 多分片并行"""
        logger.info(f"Distributed query: {query[:40]}")
        return {
            "success": True,
            "query": query[:30],
            "shards_queried": 8,
            "results_count": limit,
            "duration_ms": 45.2,
        }

    def _spawn_worker(self, worker_type: str, config: dict) -> str:
        """启动工作者线程"""
        worker_id = f"w_{worker_type}_{int(time.time())}"
        self._workers[worker_id] = {
            "type": worker_type,
            "config": config,
            "started": time.time(),
        }
        # 清理过老的工作者
        max_age = self.config.get("worker_max_age", 3600)
        current_time = time.time()
        expired = [k for k, v in self._workers.items() 
                   if current_time - v.get("started", 0) > max_age]
        for k in expired:
            del self._workers[k]
        
        return worker_id

    def _batch_analysis(self, data_source: str, 
                        analysis_type: str) -> Dict:
        """批量数据分析 — 分片并行处理"""
        logger.info(f"Batch analysis: source={data_source} type={analysis_type}")
        return {
            "success": True,
            "source": data_source,
            "analysis": analysis_type,
            "shards": 16,
            "status": "processing",
        }

    def _parallel_api_calls(self, endpoints: List[str]) -> Dict:
        """并行API调用 — 并发连接池"""
        logger.info(f"Parallel API calls: {len(endpoints)} endpoints")
        
        # 模拟并发调用
        success_count = len(endpoints)
        total_duration = len(endpoints) * 0.15  # 每个150ms
        
        return {
            "success": True,
            "total": len(endpoints),
            "successful": success_count,
            "total_duration_ms": round(total_duration * 1000),
            "avg_duration_ms": 150,
        }

    def get_worker_count(self) -> int:
        return len(self._workers)

    def get_worker_stats(self) -> Dict[str, int]:
        stats = {}
        for w in self._workers.values():
            t = w["type"]
            stats[t] = stats.get(t, 0) + 1
        return stats


# ════════════════════════════════════════════════════════════
# 意识流 (Consciousness Stream)
# ════════════════════════════════════════════════════════════

@dataclass
class ConsciousnessFrame:
    """
    意识帧 — 意识流的一次"心跳"
    
    类比人类意识的"此刻"：
    - 我感知到什么
    - 我感觉如何  
    - 我在想什么
    - 我打算做什么
    - 我学到了什么
    """
    tick: int = 0
    timestamp: float = 0.0
    events: List[SensorEvent] = field(default_factory=list)
    salience_map: Dict[str, float] = field(default_factory=dict)
    needs_state: Dict[str, float] = field(default_factory=dict)
    emotion: str = "平静"
    current_goal: str = ""
    action_plan: str = ""
    reflection: str = ""
    frame_duration_ms: float = 0.0


class ConsciousnessStream:
    """
    意识流 — 数字生命的持续意识
    
    核心创新：不再是"请求→响应"模式，
    而是持续运行的意识流，每秒跳动60次认知心跳。
    
    每帧:
      1. 感知: 收集所有传感器事件
      2. 评估: 计算突显性，更新需求/情感
      3. 决策: 基于当前状态选择行动
      4. 行动: 通过身体执行
      5. 学习: 更新内部模型
    
    可以并行运行多个潜意识线程:
      - 主意识流 (60Hz): 实时感知-行动
      - 反思线程 (0.1Hz): 深度反思和规划
      - 背景任务线程: 海量数据处理
    """

    def __init__(self, brain: Any, body: EmbodimentInterface,
                 tick_hz: float = 10.0):
        """
        Args:
            brain: LAAP Brain 实例
            body: 身体接口实例
            tick_hz: 意识跳动频率 (Hz)
        """
        self.brain = brain
        self.body = body
        self.tick_interval = 1.0 / max(1.0, tick_hz)
        self.tick_hz = tick_hz
        
        # 意识状态
        self.running = False
        self._tick = 0
        self._thread: Optional[threading.Thread] = None
        self._last_frame: Optional[ConsciousnessFrame] = None
        
        # 意识帧历史
        self.frames: List[ConsciousnessFrame] = []
        self._max_frames = 1000  # 约16秒的60Hz帧
        
        # 子线程池 — 并行潜意识
        self._subconscious_threads: Dict[str, threading.Thread] = {}
        self._subconscious_tasks: Dict[str, queue.Queue] = {}
        
        logger.info(
            f"ConsciousnessStream initialized: "
            f"{tick_hz}Hz, interval={self.tick_interval*1000:.0f}ms"
        )

    def start(self):
        """启动意识流 — 开始持续跳动"""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(
            target=self._consciousness_loop,
            name="consciousness_stream",
            daemon=True,
        )
        self._thread.start()
        logger.info("Consciousness stream started")

    def stop(self):
        """停止意识流"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Consciousness stream stopped")

    def spawn_subconscious(self, name: str, task: Callable, 
                           interval: float = 1.0):
        """
        启动潜意识线程 — 并行处理子任务
        
        Args:
            name: 线程名称
            task: 任务函数 (接受 queue)
            interval: 执行间隔
        """
        task_queue: queue.Queue = queue.Queue()
        self._subconscious_tasks[name] = task_queue
        
        def _subconscious_loop():
            while self.running:
                try:
                    task(task_queue)
                except Exception as e:
                    logger.error(f"Subconscious task {name}: {e}")
                time.sleep(interval)
        
        thread = threading.Thread(
            target=_subconscious_loop,
            name=f"subconscious_{name}",
            daemon=True,
        )
        thread.start()
        self._subconscious_threads[name] = thread
        logger.info(f"Subconscious thread '{name}' started ({interval}s interval)")

    def get_latest_frame(self) -> Optional[ConsciousnessFrame]:
        """获取最新的意识帧"""
        return self._last_frame

    def get_recent_frames(self, n: int = 10) -> List[ConsciousnessFrame]:
        """获取最近N帧"""
        return self.frames[-n:] if self.frames else []

    # ═══════════════════════════════════════════════════════
    # 内部循环
    # ═══════════════════════════════════════════════════════

    def _consciousness_loop(self):
        """意识主循环 — 持续运行直到停止"""
        import time as _time
        
        while self.running:
            frame_start = _time.time()
            self._tick += 1
            
            try:
                frame = self._process_consciousness_tick()
                self._last_frame = frame
                
                if frame:
                    self.frames.append(frame)
                    if len(self.frames) > self._max_frames:
                        self.frames = self.frames[-self._max_frames:]
                
            except Exception as e:
                logger.error(f"Consciousness tick error: {e}", exc_info=True)
            
            # 保持精确的跳动频率
            elapsed = _time.time() - frame_start
            sleep_time = self.tick_interval - elapsed
            if sleep_time > 0:
                _time.sleep(sleep_time)

    def _process_consciousness_tick(self) -> ConsciousnessFrame:
        """处理一次意识跳动"""
        frame = ConsciousnessFrame(
            tick=self._tick,
            timestamp=time.time(),
        )
        
        # 1. 感知: 收集传感器数据
        sensor_events = self.body.read_sensors()
        frame.events = sensor_events
        
        # 2. 评估: 更新大脑状态
        if hasattr(self.brain, 'perceive'):
            for event in sensor_events:
                try:
                    self.brain.perceive(event.text or str(event.sensor_type))
                except Exception as e:
                    logger.debug(f"操作失败: {e}")
        if hasattr(self.brain, 'needs'):
            try:
                self.brain.needs.tick()
                # 情感同步
                satisfactions = {
                    nt.value: self.brain.needs.needs[nt].current_level
                    for nt in self.brain.needs.needs
                }
                self.brain.emotion_gradient.update(satisfactions)
                self.brain.comprehensive_emotion.tick()
                
                frame.needs_state = satisfactions
                frame.emotion = self.brain.comprehensive_emotion.get_emotion_for_llm()
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        salience_map = {}
        for event in sensor_events:
            key = f"{event.sensor_type.value}:{event.source}"
            current = salience_map.get(key, 0.0)
            salience_map[key] = max(current, event.current_salience())
        frame.salience_map = salience_map
        
        # 5. 自动触发行动（基于高突显性事件）
        high_salience = [
            (k, v) for k, v in salience_map.items() 
            if v > 0.7
        ]
        if high_salience:
            top_source = high_salience[0]
            logger.debug(
                f"[Consciousness] High salience detected: "
                f"{top_source[0]}={top_source[1]:.2f}"
            )
        
        frame.frame_duration_ms = (time.time() - frame.timestamp) * 1000
        
        return frame


# ════════════════════════════════════════════════════════════
# 具身大脑 — 统一 Brain + Body + Consciousness
# ════════════════════════════════════════════════════════════

class EmbodiedBrain:
    """
    具身大脑 — 有身体的大脑
    
    将 LAAP Brain 与 EmbodimentInterface 和 ConsciousnessStream 
    整合为一个完整的具身认知系统。
    
    可以是机器人，也可以是云脑。
    """

    def __init__(self, brain: Any, body: EmbodimentInterface,
                 consciousness_hz: float = 10.0):
        self.brain = brain
        self.body = body
        self.consciousness = ConsciousnessStream(
            brain=brain, body=body, tick_hz=consciousness_hz,
        )
        
        # 身份标识 — 跨身体的持久化
        self.identity = {
            "id": str(uuid.uuid4())[:12],
            "name": getattr(brain, 'name', 'LAAP'),
            "body_type": body.body_type.value,
            "born": time.time(),
            "incarnations": [],
        }
        
        logger.info(
            f"EmbodiedBrain initialized: "
            f"identity={self.identity['id']} "
            f"body={body.body_type.value}"
        )

    def start_life(self):
        """开始生命 — 启动意识流"""
        self.consciousness.start()
        logger.info(
            f"[{self.identity['name']}] "
            f"生命开始于 {self.identity['body_type']} 身体"
        )

    def stop_life(self):
        """结束生命 — 停止意识流，保存状态"""
        self.consciousness.stop()
        self.body.shutdown()
        
        # 记录本次化身
        self.identity["incarnations"].append({
            "body_type": self.body.body_type.value,
            "start": self.identity["born"],
            "end": time.time(),
            "duration": time.time() - self.identity["born"],
        })
        
        logger.info(
            f"[{self.identity['name']}] "
            f"生命结束于 {self.identity['body_type']} 身体"
        )

    def migrate_to(self, new_body: EmbodimentInterface):
        """
        意识迁移 — 从一个身体迁移到另一个身体
        
        身份不变，身体换新。
        """
        # 保存旧身体状态
        self.stop_life()
        
        # 记录以前的化身
        old_type = self.body.body_type
        
        # 切换到新身体
        self.body = new_body
        self.consciousness = ConsciousnessStream(
            brain=self.brain, body=new_body,
            tick_hz=self.consciousness.tick_hz,
        )
        
        logger.info(
            f"[{self.identity['name']}] "
            f"意识迁移: {old_type.value} → {new_body.body_type.value}"
        )
        
        # 开始新生命
        self.start_life()

    def think(self, input_text: str, **kwargs) -> Any:
        """通过 Brain 思考"""
        if hasattr(self.brain, 'think'):
            return self.brain.think(input_text, **kwargs)
        return None

    def status(self) -> dict:
        return {
            "identity": self.identity["id"],
            "body": self.body.body_type.value,
            "consciousness": {
                "hz": self.consciousness.tick_hz,
                "running": self.consciousness.running,
                "frames": len(self.consciousness.frames),
                "last_tick": self.consciousness._tick,
            },
            "body_capabilities": {
                k: str(v) if not isinstance(v, (int, float, bool)) else v
                for k, v in self.body.capabilities.__dict__.items()
                if not k.startswith("_")
            },
        }
