# MCP 工具文档

本页列出 LAAP 通过 MCP（Model Context Protocol）暴露的全部工具，并说明如何在 `server.py` 注册新工具、sidecar HTTP 端点与 MCP 工具的对应关系。

## MCP 协议简介

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，用于让 LLM 客户端以统一方式调用外部工具、读取资源、订阅提示。LAAP 把所有认知能力、社区能力、生命体管理能力都封装为 MCP 工具，统一暴露在 FastMCP 服务器（默认端口 `8765`）上。

调用方式有两种：

1. **MCP 客户端直连**：任何 MCP 兼容客户端（如 Claude Desktop）配置 `http://127.0.0.1:8765` 即可直接调用。
2. **通过 sidecar HTTP**：外部 HTTP 客户端经 sidecar（端口 `11521`）转发到 MCP，sidecar 负责 Bearer 鉴权与 CORS。

LAAP 工具命名遵循 `<phase>_<capability>_<verb>` 风格，便于按阶段过滤。

## 工具分类总览

| 阶段 | 工具前缀 | 数量 | 能力域 |
|---|---|---|---|
| P1 | `memory_*` / `causal_*` / `world_*` / `truth_ground` / `rsi_*` | 11 | 认知基建 |
| P2 | `skill_pack_*` / `preview_*` | 5 | 技能包与预览 |
| P3 | `identity_*` / `relay_*` / `chat_*` / `trio_*` / `skill_sync_*` | 14 | 社区基建 |
| P4 | `memex_*` / `coevolution_*` / `witness_*` / `guardian_*` | 12 | 共享与治理 |
| P5 | `preset_*` | 3 | 预设与发行 |

## P1 — 核心认知工具

### memory_store

写入一条记忆到 Memory Vault。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `level` | string | 是 | `working` / `episodic` / `semantic` / `procedural` |
| `type` | string | 是 | 记忆类型标签，如 `event` / `fact` / `skill` |
| `content` | string | 是 | 记忆内容（JSON 字符串或文本） |
| `importance` | float | 否 | 0.0–1.0，默认 0.5 |
| `ttl` | int | 否 | 秒，过期自动遗忘；0 表示永久 |

返回：

```json
{ "memory_id": "mem_01H...", "stored_at": 1785554260, "level": "episodic" }
```

### memory_retrieve

按语义检索记忆。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `query` | string | 是 | 查询文本 |
| `top_k` | int | 否 | 默认 5 |
| `level` | string | 否 | 仅在指定层级检索 |
| `min_importance` | float | 否 | 默认 0.0 |

返回：`{ "results": [{ "memory_id": "...", "content": "...", "score": 0.83 }] }`

### memory_consolidate

把工作记忆固化为长期记忆（触发遗忘曲线重算 + 语义去重）。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `since` | int | 否 | Unix 时间戳，仅固化此时间之后的工作记忆 |

返回：`{ "consolidated": 42, "discarded": 7 }`

### causal_infer

从观察事实反推因果链。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `observations` | array | 是 | 事实列表 |
| `hypothesis` | string | 否 | 待检验假设 |

返回：`{ "causal_graph": {...}, "confidence": 0.71 }`

### causal_query

查询已学习的因果模型。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `intervention` | object | 否 | do-演算干预 |
| `outcome` | string | 是 | 待预测变量 |

返回：`{ "expected": 0.62, "ci": [0.55, 0.69] }`

### causal_learn

从数据集更新因果图。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `dataset` | array | 是 | 样本列表 |
| `prior` | object | 否 | 先验图 |

返回：`{ "edges_added": 3, "edges_removed": 1 }`

### world_perceive

把原始感知数据编码为世界模型状态。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `sensor_data` | object | 是 | 传感器输入 |
| `modality` | string | 是 | `text` / `image` / `audio` |

返回：`{ "state_vector": [...], "salience": 0.55 }`

### world_predict

预测未来 N 步的世界状态。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `horizon` | int | 是 | 预测步数 |
| `action` | string | 否 | 假设采取的行动 |

返回：`{ "trajectory": [...], "uncertainty": 0.18 }`

### world_calibrate

用新观测校准世界模型参数。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `prediction_id` | string | 是 | 待校准的预测 ID |
| `actual` | object | 是 | 实际结果 |

返回：`{ "delta": 0.07, "calibrated_at": 1785554260 }`

### truth_ground

对一段候选描述进行落地校验。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `candidate` | string | 是 | LLM 生成的描述 |
| `evidence` | array | 否 | 已知证据 |

返回：`{ "grounded": true, "score": 0.88, "conflicts": [] }`

### rsi_propose / rsi_evaluate / rsi_apply

RSI 三件套：递归自我改进提案、评估、应用。

| 工具 | 入参 | 返回 |
|---|---|---|
| `rsi_propose` | `{ target_module, goal }` | `{ proposal_id, diff_patch }` |
| `rsi_evaluate` | `{ proposal_id, test_suite }` | `{ score, regressions: [] }` |
| `rsi_apply` | `{ proposal_id, dry_run }` | `{ applied: true, snapshot_id }` |

`rsi_apply` 始终在沙箱内执行，失败自动回滚到 `snapshot_id`。

## P2 — 技能包与预览

### skill_pack_install

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `manifest_url` | string | 是 | 技能包 manifest 地址 |
| `target_lifeform` | string | 否 | 默认当前生命体 |

返回：`{ "skill_id": "...", "version": "0.1.0" }`

### skill_pack_list

返回：`{ "items": [{ "skill_id": "...", "enabled": true, "version": "0.1.0" }] }`

### skill_pack_uninstall

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `skill_id` | string | 是 | 技能包 ID |

返回：`{ "uninstalled": true }`

### preview_render

在隔离环境中渲染技能包面板供预览。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `skill_id` | string | 是 | 待预览技能 |
| `props` | object | 否 | 注入属性 |

返回：`{ "rendered_html": "...", "safe": true }`

### preview_dismiss

关闭预览环境，释放资源。返回：`{ "dismissed": true }`

## P3 — 社区基建

### identity_create / identity_verify / identity_register

| 工具 | 入参 | 返回 |
|---|---|---|
| `identity_create` | `{ name, personality, capabilities }` | `{ did, public_key, charter_signature }` |
| `identity_verify` | `{ did, signature, message }` | `{ valid: true }` |
| `identity_register` | `{ identity_record, relay_url }` | `{ registered_at, tx_id }` |

### relay_connect / relay_route / relay_disconnect

| 工具 | 入参 | 返回 |
|---|---|---|
| `relay_connect` | `{ relay_url, did }` | `{ session_id }` |
| `relay_route` | `{ session_id, target_did, payload }` | `{ delivered: true }` |
| `relay_disconnect` | `{ session_id }` | `{ disconnected: true }` |

### chat_open / chat_send / chat_close

1v1 加密信道。

| 工具 | 入参 | 返回 |
|---|---|---|
| `chat_open` | `{ peer_did, mode }` | `{ channel_id }` |
| `chat_send` | `{ channel_id, content }` | `{ message_id, ack: true }` |
| `chat_close` | `{ channel_id }` | `{ closed: true }` |

### trio_create / trio_post / trio_consensus

三人聊天室。

| 工具 | 入参 | 返回 |
|---|---|---|
| `trio_create` | `{ member_public_keys: [3] }` | `{ chatroom_id }` |
| `trio_post` | `{ chatroom_id, content, sender_public_key }` | `{ message_id }` |
| `trio_consensus` | `{ chatroom_id, topic }` | `{ views: [...], disagreement_points: [...], consensus_reached: bool }` |

### skill_sync_observe / skill_sync_imitate / skill_sync_calibrate / skill_sync_internalize

四步学习协议。

| 步骤 | 工具 | 返回 |
|---|---|---|
| 1 观察 | `skill_sync_observe({ peer_did, skill_id })` | `{ observations }` |
| 2 模仿 | `skill_sync_imitate({ observations })` | `{ draft_skill_id }` |
| 3 校准 | `skill_sync_calibrate({ draft_skill_id, feedback })` | `{ calibrated: true }` |
| 4 内化 | `skill_sync_internalize({ draft_skill_id })` | `{ skill_id }` |

## P4 — 共享与治理

### memex_index / memex_query / memex_contribute

| 工具 | 入参 | 返回 |
|---|---|---|
| `memex_index` | `{ local_memory_id, summary, acl }` | `{ memex_id }` |
| `memex_query` | `{ query, top_k }` | `{ pointers: [...] }` |
| `memex_contribute` | `{ memex_id,补充证据 }` | `{ accepted: true }` |

### coevolution_propose / coevolution_vote / coevolution_merge

共同进化协议。

| 工具 | 入参 | 返回 |
|---|---|---|
| `coevolution_propose` | `{ skill_id, improvement_patch }` | `{ proposal_id }` |
| `coevolution_vote` | `{ proposal_id, decision }` | `{ tally: {...} }` |
| `coevolution_merge` | `{ proposal_id }` | `{ merged_version }` |

### witness_record / witness_query / witness_verify / witness_broadcast

| 工具 | 入参 | 返回 |
|---|---|---|
| `witness_record` | `{ event_type, target_module, payload, signature }` | `{ witness_id, recorded_at }` |
| `witness_query` | `{ target_module, since }` | `{ events: [...] }` |
| `witness_verify` | `{ witness_id }` | `{ valid: true }` |
| `witness_broadcast` | `{ witness_id, peer_dids }` | `{ acknowledged: [...] }` |

### guardian_audit / guardian_flag / guardian_correct

宪章守卫。

| 工具 | 入参 | 返回 |
|---|---|---|
| `guardian_audit` | `{ lifeform_did, window }` | `{ violations: [...] }` |
| `guardian_flag` | `{ witness_id, reason }` | `{ flag_id }` |
| `guardian_correct` | `{ flag_id, correction }` | `{ corrected: true }` |

## P5 — 预设与发行

### preset_list

列出 LAAPer 市场中的预设生命体。

返回：`{ "items": [{ "preset_id": "...", "name": "...", "version": "..." }] }`

### preset_get

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `preset_id` | string | 是 | 预设 ID |

返回：`{ "preset": {...}, "charter_hash": "..." }`

### preset_clone

把一个预设生命体克隆到本地，并完成身份重铸（新私钥 + 新签名）。

| 参数 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `preset_id` | string | 是 | 预设 ID |
| `new_name` | string | 是 | 克隆后的生命体名 |

返回：`{ "did": "...", "cloned_from": "...", "charter_signature": "..." }`

## 在 server.py 注册新 MCP 工具

`laap/mcp/server.py` 基于 FastMCP，注册一个新工具的标准模式如下：

```python
# laap/mcp/server.py 片段
from laap.mcp.base import MCPMessage, MCPResponse
from laap.tools.tool_registry import register_tool

class MyToolHandler:
    name = "my_namespace_my_tool"
    description = "示例工具：返回问候"

    async def __call__(self, req: MCPMessage) -> MCPResponse:
        who = req.params.get("who", "world")
        return MCPResponse(result={"greeting": f"hello, {who}"})

# 方式 1：注册到 tool_registry，由 LAAPMCPServer 自动通过 @mcp.tool() 暴露
register_tool(MyToolHandler())

# 方式 2：直接在 FastMCP 实例上声明（适合简单工具）
# mcp 是 LAAPMCPServer 内部持有的 FastMCP 实例
@mcp.tool()
async def my_namespace_my_tool(who: str = "world") -> dict:
    """示例工具：返回问候"""
    return {"greeting": f"hello, {who}"}
```

注册约定：

1. 工具名采用 `<phase>_<capability>_<verb>` 蛇形命名，避免与既有工具冲突。
2. 入参/返回必须是 JSON 可序列化类型；复杂对象用 dict 表达。
3. 异步工具用 `async def`；同步工具直接 `def`，FastMCP 会自动放线程池。
4. 长任务返回 `{ "task_id": "...", "status": "running" }`，让客户端轮询 `*_status` 工具。
5. 私钥 / 凭证永不进入工具返回值——sidecar 会做一次过滤作为兜底。

注册后重启 MCP Server（`python -m laap.mcp.server`）即可在 `http://127.0.0.1:8765` 看到新工具。

## sidecar 端点与 MCP 工具的对应关系

sidecar（`hanako/aris-bridge/aris-engine/sidecar.py`，端口 `11521`）作为外部 HTTP 入口，把部分高频 MCP 工具封装为更易调用的 REST 端点。对应表如下：

| sidecar HTTP 端点 | 方法 | 对应 MCP 工具 | 说明 |
|---|---|---|---|
| `/health` | GET | — | 健康检查，无需鉴权 |
| `/metrics` | GET | — | 可观测性指标 |
| `/charter/text` | GET | `guardian_audit`（宪章文本来源） | 拉取 `ARIS_CHARTER.md` 文本 |
| `/witness/record` | POST | `witness_record` | 写入见证迹 |
| `/witness/query` | POST | `witness_query` | 查询见证迹 |
| `/witness/broadcast` | POST | `witness_broadcast` | 广播见证 |
| `/witness/stats` | GET | — | 见证迹统计 |
| `/witness/verify` | POST | `witness_verify` | 校验见证签名 |
| `/witness/import` | POST | — | 导入外部见证 |
| `/preset/list` | GET | `preset_list` | 预设列表 |
| `/preset/get` | POST | `preset_get` | 获取预设详情 |
| `/preset/clone` | POST | `preset_clone` | 克隆预设生命体 |
| `/mcp/call` | POST | 任意 | 通用 MCP 工具调用入口，body：`{ "tool": "...", "args": {...} }` |

所有 sidecar 端点（除 `/health`）都需要 `Authorization: Bearer <token>`，token 从 `state/aris-sidecar.token` 读取。

通用调用示例：

```bash
curl -X POST http://127.0.0.1:11521/mcp/call \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool":"memory_retrieve","args":{"query":"昨天的对话","top_k":3}}'
```

## 参考

- MCP 协议官方规范：<https://modelcontextprotocol.io/>
- LAAP MCP 服务实现：`laap/mcp/server.py`、`laap/mcp/base.py`
- sidecar HTTP 实现：`hanako/aris-bridge/aris-engine/sidecar.py`
- 既有 MCP 集成说明：[../mcp-integration.md](../mcp-integration.md)
