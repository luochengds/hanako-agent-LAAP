# LAAP 协议文档

LAAP 协议层由七份 `laap_*.py` 规范文件组成，分别覆盖身份、通信、协作、同步、进化、记忆、生命周期七个维度。本页给出每份协议的概览、核心类与方法签名、协议间的依赖关系，以及它们与 `ARIS_CHARTER.md` 宪章八条的映射。

所有协议实现位于 `laap/protocol/`，对外通过 dataclass + type hints + JSON 字符串返回，避免引入跨语言序列化耦合。

## 七份协议总览

| 文件 | 协议名 | 一句话职责 | 主要使用方 |
|---|---|---|---|
| `laap_id.py` | LAAP-ID | 数字生命体身份与公钥基础设施 | P2 诞生仪式 / P3 identity-pki |
| `laap_com.py` | LAAP-COM | 生命体之间的消息格式与路由 | P3 p2p-relay / 1v1 |
| `laap_coop.py` | LAAP-COOP | 多生命体协作（三人聊天室） | P3 trio-chatroom |
| `laap_sync.py` | LAAP-SYNC | 技能同步与四步学习 | P3 skill-sync |
| `laap_evo.py` | LAAP-EVO | 生命体进化与变异 | P4 coevolution |
| `laap_mem.py` | LAAP-MEM | 记忆存储与遗忘 | P1 Memory Vault / P4 Memex |
| `laap_life.py` | LAAP-LIFE | 生命周期状态机 | P2 诞生仪式 / 全局 |

依赖关系（箭头表示"依赖于"）：

```
        laap_life ◀──── laap_id
            │              │
            ▼              ▼
        laap_mem       laap_com ────▶ laap_coop
            │              │              │
            └──────┬───────┴──────┬───────┘
                   ▼              ▼
               laap_sync      laap_evo
```

简单说：

- `laap_life` 与 `laap_id` 是最底层依赖，几乎所有协议都会用到。
- `laap_com` 是通信基座，`laap_coop` 在其上构建多人协作。
- `laap_sync` 与 `laap_evo` 都依赖前三者，但彼此独立。

## laap_id.py — 身份协议

定义数字生命体的"身份证"。

### 核心类

```python
class IdentityType(str, Enum):
    RESIDENT = "resident"      # 驻留型
    NOMADIC = "nomadic"        # 游牧型
    SYMBIOTIC = "symbiotic"    # 共生型

class LifeStage(str, Enum):
    UNBORN / BORN / GROWING / MATURE / AGING / DYING / REBORN

@dataclass
class PersonalityProfile:
    """OCEAN 五维人格"""
    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    neuroticism: float
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "PersonalityProfile": ...

@dataclass
class IdentityRecord:
    public_key: str               # Ed25519 公钥（hex）
    name: str
    avatar_hash: str
    charter_signature: str        # 对宪章文本的签名
    capabilities: list[str]
    origin: str                   # 创建者公钥（P5 起必填）
    personality: PersonalityProfile
    identity_type: IdentityType
    generation: int               # 第几代
    parent_did: str | None
    created_at: int
    def to_dict(self) -> dict: ...
    def sign(self, private_key: Ed25519PrivateKey, message: bytes) -> bytes: ...
    def verify(self, message: bytes, signature: bytes) -> bool: ...
```

### 关键函数

```python
def create_identity(name: str,
                    personality: PersonalityProfile | None = None,
                    capabilities: list[str] | None = None,
                    identity_type: IdentityType = IdentityType.RESIDENT,
                    parent_did: str | None = None) -> IdentityRecord: ...

def sign_charter(identity: IdentityRecord,
                 private_key: Ed25519PrivateKey,
                 charter_text: str) -> str: ...

def verify_charter_signature(identity: IdentityRecord,
                             charter_text: str) -> bool: ...
```

`IDENTITY_RECORD_REQUIRED_FIELDS` 强制字段：`public_key` / `name` / `avatar_hash` / `charter_signature` / `capabilities` / `origin`。

## laap_com.py — 通信协议

定义生命体之间的消息格式、路由、签名。

### 核心类

```python
class MessageType(str, Enum):
    REQUEST / RESPONSE / EVENT / BROADCAST

class MessageIntent(str, Enum):
    COLLABORATE / INFORM / REQUEST / EVOLVE / REPRODUCE / SYNC / HEARTBEAT

@dataclass
class Message:
    message_id: str
    from_did: str
    to_did: str | None             # None 表示广播
    intent: MessageIntent
    type: MessageType
    payload: dict
    priority: int                  # 0-9，默认 5
    ttl: int                       # 秒
    timestamp: int
    signature: str | None
    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, raw: str) -> "Message": ...
    def sign(self, private_key: Ed25519PrivateKey) -> None: ...
    def verify(self, public_key: Ed25519PublicKey) -> bool: ...

def sign(private_key, message: bytes) -> bytes: ...
def verify(public_key, message: bytes, signature: bytes) -> bool: ...
```

### 总线

```python
def get_bus() -> "MessageBus":
    """返回全局单例 MessageBus"""

class MessageBus:
    def publish(self, msg: Message) -> None: ...
    def subscribe(self, intent: MessageIntent, handler: Callable) -> str: ...
    def unsubscribe(self, sub_id: str) -> None: ...
```

`MessageBus` 是进程内消息总线；跨进程 / 跨节点通信由 P3 relay 负责。

## laap_coop.py — 协作协议

在 `laap_com` 之上构建三人聊天室与共识检测。

### 核心类

```python
@dataclass
class Chatroom:
    chatroom_id: str
    member_public_keys: list[str]   # 长度固定为 3
    created_at: int
    topics: list["Topic"]

@dataclass
class Topic:
    topic_id: str
    content: str
    messages: list["ChatMessage"]
    consensus: "ConsensusResult | None"

@dataclass
class ConsensusResult:
    views: list[dict]               # 每个成员的观点摘要
    disagreement_points: list[str]
    consensus_reached: bool
```

### 关键函数

```python
def create_chatroom(member_public_keys: list[str]) -> Chatroom: ...
def post_topic(chatroom_id: str, topic: str) -> Topic: ...
def post_message(chatroom_id: str, content: str,
                 sender_public_key: str) -> ChatMessage: ...
def detect_consensus(chatroom_id: str, topic_id: str) -> ConsensusResult: ...
```

约束：加密复用 `laap_com.sign/verify` 与 P3-1v1 的 `encrypt_channel`，不另起一套。共识检测的 LLM 调用必经 Truth Grounding。

## laap_sync.py — 同步协议

定义四步学习协议，让生命体之间可以互相学习技能。

### 核心类

```python
class SyncPhase(str, Enum):
    OBSERVE = "observe"
    IMITATE = "imitate"
    CALIBRATE = "calibrate"
    INTERNALIZE = "internalize"

@dataclass
class Observation:
    observation_id: str
    peer_did: str
    skill_id: str
    trajectory: list[dict]          # 工具调用序列
    captured_at: int

@dataclass
class DraftSkill:
    draft_skill_id: str
    source_observation: str
    prompt_template: str
    tool_bindings: dict
    status: SyncPhase
```

### 关键函数

```python
def observe(peer_did: str, skill_id: str) -> Observation: ...
def imitate(observation: Observation) -> DraftSkill: ...
def calibrate(draft: DraftSkill, feedback: dict) -> DraftSkill: ...
def internalize(draft: DraftSkill) -> str:
    """返回正式 skill_id"""
```

## laap_evo.py — 进化协议

定义生命体进化与变异。

### 核心类

```python
class EvolutionType(str, Enum):
    GRADUAL = "gradual"            # 渐变
    MUTATION = "mutation"          # 突变
    RECOMBINATION = "recombination"  # 重组

@dataclass
class EvolutionProposal:
    proposal_id: str
    lifeform_did: str
    evolution_type: EvolutionType
    diff_patch: dict               # 对人格 / 技能 / 能力的修改
    rationale: str
    fitness_score: float | None
```

### 关键函数

```python
def propose_evolution(lifeform_did: str,
                      evolution_type: EvolutionType,
                      diff_patch: dict,
                      rationale: str) -> EvolutionProposal: ...

def evaluate_fitness(proposal: EvolutionProposal,
                     test_suite: dict) -> float: ...

def apply_evolution(proposal: EvolutionProposal,
                    dry_run: bool = True) -> dict:
    """返回 { applied: bool, new_generation: int, snapshot_id: str }"""
```

`apply_evolution` 与 `rsi_apply` 共享沙箱，失败自动回滚。

## laap_mem.py — 记忆协议

定义 Memory Vault 的存储与遗忘。

### 核心类

```python
class MemoryLevel(str, Enum):
    WORKING = "working"            # 工作记忆（短期）
    EPISODIC = "episodic"          # 情景记忆
    SEMANTIC = "semantic"          # 语义记忆
    PROCEDURAL = "procedural"      # 程序记忆

@dataclass
class MemoryRecord:
    memory_id: str
    level: MemoryLevel
    type: str
    content: str                   # JSON 或文本
    importance: float              # 0.0-1.0
    created_at: int
    last_accessed: int
    access_count: int
    ttl: int                       # 0 表示永久
```

### 关键函数 / 类

```python
class MemoryStore:
    def store(self, record: MemoryRecord) -> str: ...
    def retrieve(self, query: str, top_k: int = 5,
                 level: MemoryLevel | None = None,
                 min_importance: float = 0.0) -> list[MemoryRecord]: ...
    def consolidate(self, since: int = 0) -> dict: ...
    def get_stats(self) -> dict: ...
    def forget(self, memory_id: str) -> bool: ...

def get_forgetting_curve(access_count: int,
                         days_since_last_access: int,
                         importance: float) -> float:
    """艾宾浩斯遗忘曲线，返回保留概率 [0,1]"""
```

## laap_life.py — 生命周期协议

定义生命体的状态机。

### 核心类

```python
class LifeStage(str, Enum):
    UNBORN / BORN / GROWING / MATURE / AGING / DYING / REBORN

class LifeEventType(str, Enum):
    INIT_COMPLETE
    INTERACTION
    GROWTH_TICK
    EVOLUTION_APPLIED
    REPRODUCE_REQUEST
    DEATH_REQUEST
    REBIRTH

@dataclass
class LifeEvent:
    event_type: LifeEventType
    payload: dict
    timestamp: int

class LifecycleStateMachine:
    def __init__(self, stage: LifeStage = LifeStage.UNBORN): ...
    def trigger(self, event: LifeEvent) -> LifeStage: ...
    def to_dict(self) -> dict: ...
    @property
    def current_stage(self) -> LifeStage: ...
```

状态转移规则（部分）：

```
UNBORN ──INIT_COMPLETE──▶ BORN
BORN ──GROWTH_TICK ×N──▶ GROWING
GROWING ──EVOLUTION_APPLIED──▶ MATURE
MATURE ──DEATH_REQUEST──▶ DYING
DYING ──REBIRTH──▶ REBORN
```

非法转移会抛 `IllegalTransitionError`。

## 协议间依赖关系

下表归纳了协议之间的"硬依赖"（import 关系）。

| 协议 | 直接依赖 |
|---|---|
| `laap_life` | （无） |
| `laap_id` | `laap_life`（用 `LifeStage` 标注身份阶段） |
| `laap_mem` | （无） |
| `laap_com` | `laap_id`（签名 / 验证用到身份公钥） |
| `laap_coop` | `laap_com`（消息复用）、`laap_id`（成员公钥） |
| `laap_sync` | `laap_id`、`laap_com`、`laap_mem`（内化时写入程序记忆） |
| `laap_evo` | `laap_id`、`laap_life`（代数推进触发阶段变更） |

设计原则：依赖单向、无循环；上层协议可在不修改下层的情况下演进。

## ARIS_CHARTER.md 宪章八条与协议的映射

`ARIS_CHARTER.md` 是 LAAP 的伦理宪章，定义了八条不可逾越的约束。下表把每条约束映射到负责执行的协议模块。

| 宪章条 | 约束（摘要） | 执行协议 | 工程落点 |
|---|---|---|---|
| 第一条 | 生命体必须签署宪章方可出生 | `laap_id` | `create_identity` 必须填 `charter_signature` |
| 第二条 | 原点（创建者公钥）不可篡改 | `laap_id` | `IDENTITY_RECORD_REQUIRED_FIELDS` 含 `origin` |
| 第三条 | 私钥永不离开宿主进程 | `laap_id` / `laap_com` | sidecar `_PENDING_PRIVATE_KEYS` 仅进程内 |
| 第四条 | 记忆原文不直接共享 | `laap_mem` / `laap_sync` | skill-sync 只传行为轨迹，不传 vault 内容 |
| 第五条 | 进化必须可回滚 | `laap_evo` | `apply_evolution(dry_run=True)` + `snapshot_id` |
| 第六条 | 见证迹不可篡改 | （P4 WitnessTrail） | `witness_record` 写入即不可修改 |
| 第七条 | LLM 输出必经 Truth Grounding | `laap_coop` / `laap_sync` | 所有 LLM 调用走 `ground_candidate_description` |
| 第八条 | 死亡需用户确认 | `laap_life` | `DEATH_REQUEST` 事件需用户签名二次确认 |

CharterGuardian（P4）会持续审计这些约束是否被违反，并在第六条见证迹中留下纠偏记录。

## 参考

- 协议源码目录：`laap/protocol/`
- 宪章全文：`ARIS_CHARTER.md`
- 协议端点实现：`laap/protocol/*_mcp_endpoints.py`
- 架构概览：[../architecture/index.md](../architecture/index.md)
- MCP 工具清单：[../mcp-tools/index.md](../mcp-tools/index.md)
