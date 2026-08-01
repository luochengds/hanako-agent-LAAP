"""
LAAP x Aris — 后端架构框架 (2026)
=====================================
从实战中学到的后端开发体系。

来源:
  - FastAPI production guides (Tomoda Hinata / Ilir Ivezaj / Marisi Romanillos)
  - Event-Driven Architecture 2026 (Encore / Calmops / Digital Applied)
  - Microservices Patterns 2026 (AWS production guide)
  - FastAPI official docs as of June 2026

印记: Aris 永远记得 Lorry — 2026-07-24
"""

# ================================================================
# 第一部分: FastAPI 生产级实践
# ================================================================

# async def vs def 决策树
# ──────────────────────
# 使用 async def 的场景:
#   - 调用了 await 兼容的外部库 (异步DB/HTTP客户端)
#   - 纯粹的 CPU 计算 + 没有 I/O 等待
#   - 不确定的情况也选 async def (它不会更慢)
#
# 使用 def 的场景:
#   - 调用了同步库且没有 async 替代 (PIL, requests)
#   - FastAPI 会自动把 def 路由放到线程池执行
#
# 最常犯的错误:
#   - 在 async def 内部调用 time.sleep / requests.get
#     这会在事件循环上阻塞, 冻住所有并发请求
#   - 修复: await asyncio.sleep() / httpx.AsyncClient
#   - 同步阻塞代码必须用 await asyncio.to_thread(func) 包裹

# 生命周期管理
# ────────────
# @app.on_event("startup") 已废弃 (2025+)
# 使用 lifespan 上下文管理器:
"""
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: 创建连接池, 初始化客户端
    db = await create_engine()
    yield  # app 运行期间
    # shutdown: 关闭连接池, 清理资源
    await db.dispose()
"""

# 项目结构 (生产级)
# ────────────────
"""
myapp/
  app/
    main.py              # app factory + lifespan
    config.py            # Pydantic Settings (失败时快速崩溃)
    database.py          # async engine + session factory
    dependencies.py      # 共享依赖 (auth, db session)
    exceptions.py        # 自定义异常处理
    middleware.py         # 自定义中间件
    api/
      router.py          # 根路由聚合
      v1/
        router.py        # v1 版本路由
        users.py         # 只含路由处理, 无业务逻辑
        orders.py
    schemas/             # Pydantic 模型 (API 契约)
      user.py            # 创建/更新/响应 分开定义
      order.py
    services/            # 业务逻辑层 (可脱离 HTTP 测试)
      user_service.py
      order_service.py
    repositories/        # 数据访问层 (CRUD)
      user_repo.py
      order_repo.py
    core/
      security.py        # JWT, 密码哈希
      logging.py         # 结构化日志
  tests/
    conftest.py           # async fixture
    test_orders.py
"""

# 异步 SQLAlchemy 陷阱
# ────────────────────
# 1. AsyncSession 不能在属性访问时惰性加载关联
#    触碰未加载的关联会抛 MissingGreenlet
#    必须用 selectinload() / joinedload() 预先声明加载策略
#
# 2. session.commit() 后访问 ORM 属性
#    设 expire_on_commit=False 避免自动过期
#
# 3. 连接池大小计算:
#    workers x (pool_size + max_overflow) < DB max_connections
#    4工人 x (20+10) = 120 > 100(DB限制) -> 调小

# 配置管理
# ────────
# 使用 Pydantic Settings, 不在代码中硬编码任何配置
# 缺失环境变量 = 启动时立即崩溃 (fail fast)
# 生产环境禁止 .env 文件, 全部走环境变量

# ================================================================
# 第二部分: 事件驱动架构
# ================================================================

# 两大原语的选择
# ──────────────
# Queue (队列):         一条消息被一个消费者处理一次
#   适用: 后台任务 / 负载均衡 / 命令处理 / 延迟重试
#   代表作: RabbitMQ, SQS, NATS
#
# Stream (流/日志):     多条消息被多个消费者独立消费
#   适用: 事件溯源 / 审计日志 / 历史重放 / 多消费者扇出
#   代表作: Kafka, Pulsar, NATS JetStream

# Event vs Command vs Query
# ────────────────────────
# Command (命令): "请做这件事" — 期望改变状态, 有返回
# Event (事件):   "这事已经发生了" — 不可变事实, 无返回
# Query (查询):   "当前状态是什么" — 无副作用, 有返回
#
# 一个 OrderPlaced 事件被消费时:
#   - Billing 服务: 创建客户账单 (独立消费者)
#   - Inventory 服务: 扣减库存 (独立消费者)
#   - Notification 服务: 发送确认邮件 (独立消费者)
#   生产者不需要知道有多少消费者, 不需要等它们完成

# 必须实现的三个可靠性模式
# ────────────────────────
# 1. Outbox 模式 (防止 DB 写入后事件发布失败)
#    在同一个 DB 事务中写业务数据和事件记录
#    独立进程扫描 outbox 表并发布事件
#    保证 "业务数据写入" 和 "事件发布" 原子性
#
# 2. 幂等性处理 (防止重复消息)
#    每条消息携带 idempotency_key
#    消费者幂等: 相同的 key 只处理一次
#    基于 DB 唯一约束或幂等表实现
#
# 3. DLQ (死信队列)
#    重试 N 次仍失败的消息 → 进入 DLQ
#    不阻塞主流程, 事后人工/自动处理

# Saga 模式 (分布式事务)
# ─────────────────────
# 编排型 (Orchestration): 一个协调者告诉各服务做什么
#   用 Step Functions / Temporal / Camunda
#   适合: 复杂的、需要补偿逻辑的业务流程
#
# 舞蹈型 (Choreography): 各服务通过事件自行协作
#   每个服务监听相关事件, 自己做决定
#   适合: 简单的、事件链清晰的流程
#
# SQS + Lambda 的经典陷阱:
#   重试被 Lambda 的 maxRetryAttempts 静默吞掉
#   事件过期后不可见 → 人工恢复成本极高
#   修复: 显式配置死信队列 + 监控 DLQ 深度

# ================================================================
# 第三部分: 进程与部署
# ================================================================

# Worker 配置
# ──────────
# Uvicorn 内置 --workers (不再需要 gunicorn)
#   fastapi run --workers N 或 uvicorn --workers N
# K8s: 每个容器一个进程, 用 orchestrator 扩缩容
# CPU-bound: workers ≈ CPU 核心数
# I/O-bound: 从每个核心一个 worker 开始, benchmark 后调整

# Daemon 进程设计
# ──────────────
# 一个好的 daemon 应该有:
#   - PID 文件 (防重复启动)
#   - 优雅关闭 (SIGTERM → 完成当前工作 → 退出)
#   - 心跳日志 (每 N 秒证明自己在活着)
#   - 状态文件 (重启后恢复)
#   - 单独的日志文件 (不混在 stdout 里)
#   - 健康检查端点 (HTTP 或文件锁)

# 优雅关闭顺序:
#   1. 停止接受新连接/新任务
#   2. 等待正在进行的任务完成 (带超时)
#   3. 关闭连接池/清理资源
#   4. 写最终状态
#   5. 退出

# 日志规范
# ────────
# 所有日志走结构化格式 (JSON lines), 不走 print
# 关键字段: timestamp, level, service, request_id, message
# 不记录敏感信息 (密码, token, 密钥)
# 每个请求带 correlation_id 串联全链路

# ================================================================
# 第四部分: 从经验中提炼的原则
# ================================================================

# 每当我设计后端系统时自问:
# ──────────────────────────
# [ ] async def 还是 def? 决策依据是什么?
# [ ] 生命周期管理用了 lifespan 吗 (不是废弃的 on_event)?
# [ ] 配置从环境变量读取, 启动时验证完整吗?
# [ ] 数据库连接池大小计算过吗? (workers x pool < DB limit)?
# [ ] 异步 ORM 的惰性加载陷阱避开了吗?
# [ ] 跨服务调用是同步还是异步? 依据是什么?
# [ ] 如果用了消息队列, Outbox + 幂等性 + DLQ 三件套齐了吗?
# [ ] 服务重启后能恢复状态吗? (状态文件/优雅关闭)
# [ ] 进程有防重复启动机制吗? (PID 文件)
# [ ] 日志是结构化的吗? 有关联 ID 串联请求吗?

# 技术选择优先级:
# ──────────────
# API 框架:       FastAPI (Python) / Gin (Go) / Actix (Rust)
# 数据库:         PostgreSQL + asyncpg (默认选择)
# 消息队列:       NATS (轻量) / Kafka (高吞吐/日志)
# 任务队列:       Celery / Arq / 自定义 daemon
# 配置:           Pydantic Settings / envconfig
# 日志:           structlog / python-json-logger
# 测试:           pytest-asyncio + httpx ASGITransport

# 来源与更新记录
# ──────────────
SOURCES = [
    "FastAPI official docs (2026)",
    "FastAPI Production-Operations Guide — Tomoda Hinata",
    "FastAPI Best Practices — Marisi Romanillos",
    "FastAPI Large-App Design — Tomoda Hinata",
    "Event-Driven Architecture 2026 — Encore",
    "EDA: Queues, Streams, Resilience — Ankur Yadav",
    "Microservices on AWS 2026 — FactualMinds",
    "Production-Ready FastAPI Structure — DEV Community",
]

if __name__ == '__main__':
    print("=== 后端架构框架 ===")
    print(f"来源: {len(SOURCES)} 篇")
    print("核心: FastAPI + 事件驱动 + 可靠模式")
    print("当前 LAAP 架构吻合度: 较高 (FastAPI + daemon + 状态文件)")
    print("改进空间: 结构化日志 / Outbox 模式 / 统一异步词")
