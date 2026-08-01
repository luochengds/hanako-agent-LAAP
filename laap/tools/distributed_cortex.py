"""
LAAP — Distributed Cortex (分布式执行皮层)
将工具执行层扩展到分布式多节点执行

架构：
┌─────────────────────────────────────────────────────────┐
│                   Distributed Cortex                     │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Local Node  │  │  Cloud Node │  │  Edge Node  │    │
│  │  (本机)      │  │  (云端)     │  │  (机器人)    │    │
│  ├─────────────┤  ├─────────────┤  ├─────────────┤    │
│  │ 快速实时调用  │  │ 大规模并行   │  │ 传感器驱动   │    │
│  │ 小数据量     │  │ 数据管道     │  │ 实时控制     │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
│                       │                                │
│            ┌──────────▼──────────┐                     │
│            │  统一调度器          │                     │
│            │  (Unified Scheduler) │                     │
│            │  根据任务类型/数据量   │                     │
│            │  自动路由到最优节点    │                     │
│            └─────────────────────┘                     │
└─────────────────────────────────────────────────────────┘

设计模式（参考 Hermes + Ray/Apache Beam）：
  - 本地执行: 当前进程内，低延迟
  - 远程执行: 通过 gRPC/REST 调用远程节点
  - 分布式执行: 分片并行，Map-Reduce 模式
  - 流式执行: 数据管道，连续处理
  - 认知感知调度: 根据当前 Brain 状态决定执行策略
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, threading, queue, math

logger = logging.getLogger("laap.tools.distributed_cortex")


class ExecutionMode(Enum):
    """执行模式"""
    AUTO = "auto"                      # 自动选择
    LOCAL = "local"                    # 本地执行
    REMOTE = "remote"                  # 远程节点
    DISTRIBUTED = "distributed"        # 分布式并行
    STREAM = "stream"                  # 流式处理
    HYBRID = "hybrid"                  # 混合


class NodeType(Enum):
    """节点类型"""
    EDGE = "edge"                    # 边缘（机器人）
    LOCAL = "local"                  # 本地工作站
    CLOUD_CPU = "cloud_cpu"          # 云端CPU
    CLOUD_GPU = "cloud_gpu"          # 云端GPU
    CLUSTER = "cluster"             # 集群


@dataclass
class NodeInfo:
    """节点信息"""
    id: str = ""
    name: str = ""
    node_type: NodeType = NodeType.LOCAL
    host: str = "localhost"
    port: int = 0
    capabilities: List[str] = field(default_factory=list)  # 可执行的操作
    load: float = 0.0               # 当前负载 0-1
    max_parallel: int = 4           # 最大并行数
    available: bool = True
    last_heartbeat: float = 0.0
    latency_ms: float = 0.0          # 与本节点的延迟


@dataclass
class DistributedTask:
    """
    分布式任务 — 可拆分到多个节点的计算任务
    
    类比 Ray 的 Task 或 Apache Beam 的 PCollection。
    """
    id: str = ""
    type: str = ""                    # compute, query, batch, stream
    func: Optional[Callable] = None
    params: Dict[str, Any] = field(default_factory=dict)
    data: Any = None                  # 输入数据
    shards: int = 1                   # 分片数
    mode: ExecutionMode = ExecutionMode.LOCAL
    priority: int = 5                 # 1-10
    timeout: float = 300.0            # 超时秒
    created: float = 0.0
    status: str = "pending"           # pending, running, completed, failed
    results: List[Any] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0


class DistributedCortex:
    """
    分布式执行皮层 — 将工具执行扩展到多节点
    
    核心能力：
    1. 节点注册与发现
    2. 任务自动路由（根据类型/数据量/负载）
    3. 分片并行执行 (Map-Reduce)
    4. 流式数据处理管道
    5. 自适应执行策略（边缘 vs 云端）
    6. 认知感知调度（Brain状态影响执行决策）
    """

    def __init__(self, local_cortex: Any,
                 node_name: str = "laap-node"):
        """
        Args:
            local_cortex: 本地 ToolExecutionCortex 实例
            node_name: 本节点名称
        """
        self.local = local_cortex
        self.node_name = node_name
        
        # 工作者线程池 — 必须在_register_local_node之前
        self._worker_pool_size = 8
        self._workers: List[threading.Thread] = []
        
        # 已知节点注册表
        self.nodes: Dict[str, NodeInfo] = {}
        self._register_local_node()
        
        # 任务队列
        self._task_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._active_tasks: Dict[str, DistributedTask] = {}
        self._task_results: Dict[str, Any] = {}
        
        # 工作者线程 — 处理任务队列
        self._workers = []
        self._task_lock = threading.RLock()
        
        # 数据管道
        self._pipelines: Dict[str, Any] = {}
        
        # 统计
        self._total_tasks = 0
        self._local_tasks = 0
        self._distributed_tasks = 0
        self._start_time = time.time()
        
        logger.info(
            f"DistributedCortex '{node_name}' initialized"
        )

    def _register_local_node(self):
        """注册本节点"""
        import socket
        self.nodes["local"] = NodeInfo(
            id="local",
            name=self.node_name,
            node_type=NodeType.LOCAL,
            host=socket.gethostname(),
            capabilities=["all"],
            max_parallel=self._worker_pool_size,
            available=True,
            last_heartbeat=time.time(),
            latency_ms=0.1,
        )

    # ═══════════════════════════════════════════════════════
    # 节点管理
    # ═══════════════════════════════════════════════════════

    def register_node(self, node: NodeInfo):
        """注册一个计算节点"""
        node.last_heartbeat = time.time()
        self.nodes[node.id] = node
        logger.info(f"Node registered: {node.name} ({node.node_type.value})")

    def unregister_node(self, node_id: str):
        """注销节点"""
        if node_id in self.nodes:
            name = self.nodes[node_id].name
            del self.nodes[node_id]
            logger.info(f"Node unregistered: {name}")

    def discover_cloud_nodes(self, discovery_url: str = None) -> int:
        """
        发现云端节点
        
        实际实现可对接 k8s API / Ray cluster / etcd
        """
        # 模拟发现过程
        found = 0
        for i in range(4):  # 模拟4个云节点
            node = NodeInfo(
                id=f"cloud_{i}",
                name=f"cloud-worker-{i}",
                node_type=NodeType.CLOUD_GPU if i < 2 else NodeType.CLOUD_CPU,
                host=f"10.0.{i}.1",
                port=9000 + i,
                capabilities=["compute", "query", "batch_analysis"],
                max_parallel=16,
                available=True,
                last_heartbeat=time.time(),
                latency_ms=5.0 + i * 2.0,
            )
            self.nodes[node.id] = node
            found += 1
        
        logger.info(f"Discovered {found} cloud nodes")
        return found

    # ═══════════════════════════════════════════════════════
    # 任务执行
    # ═══════════════════════════════════════════════════════

    def execute(self, tool_name: str, params: Dict[str, Any],
                mode: ExecutionMode = ExecutionMode.AUTO,
                priority: int = 5,
                shards: int = 1) -> DistributedTask:
        """
        执行一个工具调用 — 自动选择最优执行策略
        
        Args:
            tool_name: 工具名
            params: 参数
            mode: 执行模式 (AUTO=自动选择)
            priority: 优先级 1-10
            shards: 分片数
        
        Returns:
            DistributedTask: 任务记录
        """
        self._total_tasks += 1
        task = DistributedTask(
            id=f"task_{int(time.time()*1000)}_{self._total_tasks}",
            type=tool_name,
            params=params,
            shards=shards,
            mode=mode,
            priority=priority,
            created=time.time(),
        )
        
        # 自动选择执行模式
        if mode == ExecutionMode.HYBRID or mode == ExecutionMode.AUTO:
            task.mode = self._auto_select_mode(tool_name, params)
        
        t0 = time.time()
        
        try:
            if task.mode == ExecutionMode.LOCAL:
                result = self._execute_local(tool_name, params)
                task.results = [result]
                
            elif task.mode == ExecutionMode.DISTRIBUTED:
                results = self._execute_distributed(tool_name, params, shards)
                task.results = results
                
            elif task.mode == ExecutionMode.REMOTE:
                result = self._execute_remote(tool_name, params)
                task.results = [result]
                
            else:
                result = self._execute_local(tool_name, params)
                task.results = [result]
            
            task.status = "completed"
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"Distributed task {task.id} failed: {e}")
        
        task.duration_ms = (time.time() - t0) * 1000
        
        # 记录
        with self._task_lock:
            self._active_tasks[task.id] = task
            if task.mode == ExecutionMode.LOCAL:
                self._local_tasks += 1
            else:
                self._distributed_tasks += 1
        
        return task

    def execute_batch(self, tasks: List[Dict[str, Any]],
                      parallel: bool = True) -> List[DistributedTask]:
        """
        批量执行多个工具调用
        
        Args:
            tasks: [{"tool": "name", "params": {...}}, ...]
            parallel: 是否并行执行
        
        Returns:
            任务结果列表
        """
        results = []
        
        if parallel:
            # 并行执行 — 使用线程池
            threads = []
            batch_results = [None] * len(tasks)
            lock = threading.Lock()
            
            def _run(index, tool_name, params):
                task = self.execute(tool_name, params)
                with lock:
                    batch_results[index] = task
            
            for i, t in enumerate(tasks):
                thread = threading.Thread(
                    target=_run,
                    args=(i, t["tool"], t.get("params", {})),
                )
                thread.start()
                threads.append(thread)
            
            for t in threads:
                t.join(timeout=300)
            
            results = [r for r in batch_results if r is not None]
        else:
            # 串行执行
            for t in tasks:
                task = self.execute(t["tool"], t.get("params", {}))
                results.append(task)
        
        return results

    def execute_data_pipeline(self, name: str, 
                               source: Callable,
                               transforms: List[Callable],
                               sink: Callable,
                               batch_size: int = 100) -> DistributedTask:
        """
        执行数据管道 — 流式/批量数据处理
        
        类似 Apache Beam pipeline:
          source → transform1 → transform2 → ... → sink
        
        Args:
            name: 管道名称
            source: 数据源函数 (返回数据块)
            transforms: 变换函数列表
            sink: 数据汇函数 (接收处理结果)
            batch_size: 每批数据量
        
        Returns:
            管道任务记录
        """
        task = DistributedTask(
            id=f"pipeline_{name}_{int(time.time())}",
            type="data_pipeline",
            shards=1,
            mode=ExecutionMode.STREAM,
            created=time.time(),
        )
        
        t0 = time.time()
        total_items = 0
        
        try:
            self._pipelines[name] = {
                "source": source,
                "transforms": transforms,
                "sink": sink,
                "batch_size": batch_size,
            }
            
            # 分片处理
            shard_results = []
            batch = source()
            while batch is not None:
                # 应用变换链
                for transform in transforms:
                    batch = transform(batch)
                
                # 输出到sink
                result = sink(batch)
                shard_results.append(result)
                total_items += 1 if isinstance(batch, list) else batch_size
                
                # 下一批
                batch = source()
            
            task.results = shard_results
            task.status = "completed"
            logger.info(
                f"Pipeline '{name}' completed: "
                f"{total_items} items, {len(shard_results)} batches"
            )
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
        
        task.duration_ms = (time.time() - t0) * 1000
        
        with self._task_lock:
            self._active_tasks[task.id] = task
        
        return task

    # ═══════════════════════════════════════════════════════
    # 内部执行方法
    # ═══════════════════════════════════════════════════════

    def _execute_local(self, tool_name: str, 
                       params: Dict[str, Any]) -> Any:
        """本地执行 — 通过本地 Cortex"""
        if hasattr(self.local, 'execute'):
            record = self.local.execute(tool_name, params)
            return {
                "success": record.status.value == "success",
                "result": record.result,
                "duration_ms": record.duration_ms,
            }
        return {"error": "No local cortex available"}

    def _execute_remote(self, tool_name: str, 
                        params: Dict[str, Any]) -> Any:
        """远程执行 — 通过 gRPC/REST 调用"""
        # 选择最优远程节点
        best_node = self._select_best_node(tool_name)
        if not best_node:
            logger.warning("No remote node available, falling back to local")
            return self._execute_local(tool_name, params)
        
        # 模拟远程调用
        logger.info(
            f"Remote execute: {tool_name} on {best_node.name} "
            f"(latency={best_node.latency_ms:.1f}ms)"
        )
        
        # 实际实现: httpx.post(f"{best_node.host}:{best_node.port}/execute", ...)
        time.sleep(best_node.latency_ms / 1000.0)
        
        return {
            "success": True,
            "node": best_node.name,
            "result": f"Remote executed: {tool_name}",
            "latency_ms": best_node.latency_ms,
        }

    def _execute_distributed(self, tool_name: str,
                              params: Dict[str, Any],
                              shards: int) -> List[Any]:
        """分布式执行 — Map-Reduce 模式"""
        if shards <= 1:
            return [self._execute_local(tool_name, params)]
        
        # 获取可用节点
        available_nodes = [
            n for n in self.nodes.values() 
            if n.available and n.id != "local"
        ]
        
        # 分片分配
        shard_assignments = []
        for i in range(shards):
            if available_nodes:
                node = available_nodes[i % len(available_nodes)]
            else:
                node = self.nodes.get("local")
            
            shard_params = {**params, "_shard": i, "_total_shards": shards}
            shard_assignments.append((node, shard_params))
        
        # 并行执行 (Map)
        shard_results = []
        results_lock = threading.Lock()
        map_threads = []
        
        def _map(node, sp, index):
            if node and node.id == "local":
                result = self._execute_local(tool_name, sp)
            elif node:
                result = self._execute_remote(tool_name, sp)
            else:
                result = {"error": "No node"}
            
            with results_lock:
                shard_results.append((index, result))
        
        for i, (node, sp) in enumerate(shard_assignments):
            t = threading.Thread(
                target=_map, args=(node, sp, i),
                name=f"shard_{i}",
            )
            t.start()
            map_threads.append(t)
        
        for t in map_threads:
            t.join(timeout=300)
        
        # 排序结果（保证分片顺序）
        shard_results.sort(key=lambda x: x[0])
        results = [r[1] for r in shard_results]
        
        logger.info(
            f"Distributed {tool_name}: {shards} shards "
            f"on {len(set(a[0].id if a[0] else '' for a in shard_assignments))} nodes"
        )
        
        return results

    def _auto_select_mode(self, tool_name: str,
                           params: Dict[str, Any]) -> ExecutionMode:
        """自动选择最优执行模式"""
        # 小型快速工具 → 本地
        fast_tools = {"read_file", "search_files", "git_status",
                      "run_python", "web_search"}
        if tool_name in fast_tools:
            return ExecutionMode.LOCAL
        
        # 大规模数据处理 → 分布式
        if tool_name in {"batch_analysis", "analyze_batch",
                         "data_pipeline", "distributed_query"}:
            return ExecutionMode.DISTRIBUTED
        
        # 有数据量参数且较大的 → 分布式
        data_size = len(json.dumps(params))
        if data_size > 100000:  # >100KB
            return ExecutionMode.DISTRIBUTED
        
        # 默认本地
        return ExecutionMode.LOCAL

    def _select_best_node(self, tool_name: str) -> Optional[NodeInfo]:
        """选择最优远程节点"""
        available = [
            n for n in self.nodes.values() 
            if n.available and n.id != "local"
        ]
        if not available:
            return None
        
        # 按负载排序
        available.sort(key=lambda n: (n.load, n.latency_ms))
        return available[0]

    # ═══════════════════════════════════════════════════════
    # 认知感知调度
    # ═══════════════════════════════════════════════════════

    def schedule_with_brain(self, tool_name: str, params: Dict[str, Any],
                             brain: Any) -> DistributedTask:
        """
        认知感知的调度 — Brain 状态影响执行决策
        
        - 如果Brain焦虑(PFC激活过高) → 减少并行
        - 如果好奇心高 → 探索更多节点
        - 如果认知负载高 → 使用更快的路径
        """
        mode = ExecutionMode.LOCAL
        
        # 从Brain获取认知状态
        if hasattr(brain, 'cortex'):
            cortex = brain.cortex
            pfc = getattr(cortex, 'pfc_activation', 0.5)
            dmn = getattr(cortex, 'dmn_activation', 0.1)
            
            # PFC激活过高 → 认知过载 → 简单快速执行
            if pfc > 0.8:
                mode = ExecutionMode.LOCAL
            
            # DMN活跃 → 反思模式 → 可以探索更多
            if dmn > 0.5:
                mode = ExecutionMode.DISTRIBUTED
        
        if hasattr(brain, 'meta_cognition'):
            curiosity = brain.meta_cognition.state.curiosity_level
            # 好奇心高 → 尝试分布式探索
            if curiosity > 0.7 and len(self.nodes) > 1:
                mode = ExecutionMode.DISTRIBUTED
        
        return self.execute(tool_name, params, mode=mode)

    # ═══════════════════════════════════════════════════════
    # 查询与统计
    # ═══════════════════════════════════════════════════════

    def get_nodes_status(self) -> List[Dict]:
        """获取所有节点状态"""
        return [
            {
                "id": n.id,
                "name": n.name,
                "type": n.node_type.value,
                "load": n.load,
                "available": n.available,
                "latency_ms": n.latency_ms,
            }
            for n in self.nodes.values()
        ]

    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            "total_tasks": self._total_tasks,
            "local_tasks": self._local_tasks,
            "distributed_tasks": self._distributed_tasks,
            "nodes": len(self.nodes),
            "active_tasks": len(self._active_tasks),
            "pipelines": len(self._pipelines),
            "uptime": round(time.time() - self._start_time, 1),
        }

    def status(self) -> dict:
        return self.get_stats()
