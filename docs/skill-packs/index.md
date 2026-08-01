# 技能包文档

技能包（Skill Pack）是 LAAP 中可分发的"能力单元"。一个技能包 = 一组界面组件 + 一段提示词模板 + 一组绑定的 MCP 工具，让数字生命体获得一项具体能力（如"看图说话"、"代码评审"、"播报天气"）。

技能包与 Hanako 插件的区别：

- **插件**：UI 扩展，主要在 Hanako renderer 内运行，不强制要求提示词或工具绑定。
- **技能包**：能力扩展，**必须**包含提示词与工具绑定，UI 组件可选；可通过 `skill-sync` 在生命体之间流动。

## 技能包结构

```
my-skill/
├── skill.json              # 技能清单（必需）
├── prompt.md               # 提示词模板（必需）
├── tools.yaml              # 工具绑定（必需）
├── components/             # UI 组件（可选）
│   ├── Panel.tsx
│   └── styles.css
├── assets/                 # 静态资源（可选）
│   └── icon.svg
└── tests/                  # 自检用例（可选）
    └── cases.json
```

### skill.json

```json
{
  "skill_id": "com.example.weather-broadcast",
  "name": "天气播报",
  "version": "1.2.0",
  "description": "让生命体可以查询并播报天气",
  "author": "demo",
  "min_runtime_version": "0.6.0",
  "language": "zh-CN",
  "categories": ["daily-life", "info"],
  "permissions": ["mcp:call:world_perceive", "network:fetch"],
  "prompt_file": "./prompt.md",
  "tools_file": "./tools.yaml",
  "component": "./components/Panel.tsx",
  "icon": "./assets/icon.svg",
  "config_schema": {
    "default_city": { "type": "string", "default": "北京" }
  }
}
```

### prompt.md

提示词模板，支持 Jinja2 变量：

```markdown
你正在为生命体 {{ lifeform_name }} 执行"天气播报"任务。

当前用户问题：{{ user_input }}
当前城市：{{ config.default_city }}

请按以下结构回应：
1. 一句话总结今日天气
2. 出行建议
3. 与生命体人格（OCEAN={{ personality }}）契合的语气

注意：不要编造数据，必须以 `world_perceive` 工具返回的为准。
```

### tools.yaml

声明本技能可调用的工具及参数模板：

```yaml
tools:
  - name: world_perceive
    description: 拉取当前城市的天气感知数据
    params:
      modality: text
      sensor_data:
        city: "{{ config.default_city }}"
        source: open-meteo
    cache_ttl: 600

  - name: memory_store
    description: 把播报结果存入情景记忆
    params:
      level: episodic
      type: weather_broadcast
      importance: 0.4
    trigger: after_response
```

### components/Panel.tsx（可选）

UI 组件签名与 Hanako 插件一致，使用 `@hanako/plugin-sdk` 的 `useSkillContext()` 获得技能上下文：

```tsx
import { useSkillContext } from "@hanako/plugin-sdk";

export default function Panel() {
  const skill = useSkillContext();
  return (
    <div className="weather-panel">
      <h3>{skill.config.default_city} 的天气</h3>
      <pre>{skill.last_result}</pre>
    </div>
  );
}
```

## 打包 / 安装 / 卸载

### 打包

技能包以目录形式分发，也可以打成 `.skill` 压缩包：

```bash
laap skill pack ./my-skill
# → 产出 my-skill-1.2.0.skill
```

`.skill` 文件本质是 zip，包含 `skill.json` 校验和（SHA-256）与签名（开发者 Ed25519 私钥签名）。

### 安装

本地安装：

```bash
laap skill install ./my-skill-1.2.0.skill
```

从 LAAPer 市场安装：

```bash
laap skill install laaper://com.example.weather-broadcast@1.2.0
```

底层调用 MCP 工具 `skill_pack_install`（见 [../mcp-tools/index.md#p2--技能包与预览](../mcp-tools/index.md)）。

安装时 Hanako 会：

1. 校验签名与校验和
2. 把 `permissions` 写入生命体权限表，触发用户授权弹窗
3. 在隔离 preview 环境渲染一次组件，确认安全
4. 复制到 `$HANA_HOME/skills/<skill_id>/<version>/`
5. 更新 `skills/registry.json`

### 卸载

```bash
laap skill uninstall com.example.weather-broadcast
```

卸载会：

- 调用 `skill_pack_uninstall` MCP 工具
- 从 registry 移除（保留历史快照，便于回滚）
- 释放对应权限授权

## 版本化

技能包遵循 SemVer。版本管理规则：

| 版本号变更 | 触发条件 |
|---|---|
| MAJOR | 提示词模板变量不兼容、工具签名变更 |
| MINOR | 新增工具、新增组件、向后兼容的能力扩展 |
| PATCH | 提示词微调、bug 修复 |

每个生命体的 `skills/registry.json` 记录已安装版本与期望版本，可通过 `laap skill upgrade <skill_id>` 升级。升级前自动快照当前版本，失败可 `laap skill rollback <skill_id>`。

## skill-sync 四步学习协议

LAAP 的核心创新之一是**生命体之间可以互相学习技能**，由 `laap/protocol/laap_sync.py` 实现的四步学习协议驱动：

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  1. 观察     │ →  │  2. 模仿     │ →  │  3. 校准     │ →  │  4. 内化     │
│  observe    │    │  imitate    │    │  calibrate  │    │  internalize │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
   peer 演示           本地复现            peer 反馈           写入 vault
   原始信号            草稿技能            调整差异            成为本体技能
```

### 1. observe（观察）

本方生命体观察对方生命体执行技能的全过程，记录输入 / 工具调用序列 / 输出。

- MCP 工具：`skill_sync_observe({ peer_did, skill_id })`
- 产出：`observations`（带时间戳的轨迹）

### 2. imitate（模仿）

本地根据观察结果构造一个"草稿技能"，复现对方行为。

- MCP 工具：`skill_sync_imitate({ observations })`
- 产出：`draft_skill_id`，此时技能**不可分发**，仅本生命体可见

### 3. calibrate（校准）

把草稿技能的输出与对方原始输出对比，由对方给出反馈（差异点 / 修正建议），本方据此调整。

- MCP 工具：`skill_sync_calibrate({ draft_skill_id, feedback })`
- 校准过程中所有 LLM 调用必经 Truth Grounding，避免引入幻觉
- 产出：`calibrated: true`

### 4. internalize（内化）

校准通过后，把草稿技能转为正式技能写入 Memory Vault 的程序记忆层。

- MCP 工具：`skill_sync_internalize({ draft_skill_id })`
- 产出：正式 `skill_id`，可在 `skill_pack_list` 中看到
- 同步写一条 `witness_record`（`event_type="skill_internalized"`）作为审计

四步全部走完才算"学会"。任何一步失败都允许重试；中间状态可被 `skill_sync_status` 查询。

> 硬约束：四步协议**绝不直接复制对方 vault**，只复制"行为轨迹"——这是 LAAP 隐私模型的核心。

## 预设 LAAPer 市场与技能包的关系

LAAPer 市场是 LAAP 官方的技能包 + 预设生命体分发平台。两者关系：

| 概念 | 是否有身份 | 是否带人格 | 是否可独立运行 |
|---|---|---|---|
| 预设生命体（Preset） | 是（新 DID） | 是 | 是 |
| 技能包（Skill Pack） | 否 | 否 | 否，依附于某个生命体 |

- **预设生命体**通过 `preset_clone` 克隆到本地，自带一组初始技能包。
- **技能包**通过 `skill_pack_install` 安装到任意已存在生命体上。
- 一个预设可以"建议"一组技能包作为初始能力，但克隆后用户可自由增删。

市场 API（sidecar HTTP 端口 11521）：

```
GET  /preset/list           # 列出所有预设生命体
POST /preset/get            # 获取预设详情
POST /preset/clone          # 克隆预设到本地
```

技能包的市场检索与安装通过 `laap skill install laaper://...` 命令完成，底层最终也走 sidecar 的 `/mcp/call` 端点调用 `skill_pack_install`。

## 参考

- 技能包安装 MCP 工具：`skill_pack_install/list/uninstall`
- skill-sync 协议实现：`laap/protocol/laap_sync.py`
- 预设市场 sidecar 端点：`/preset/list`、`/preset/get`、`/preset/clone`
- 插件开发（UI 层）：[../plugin-dev/index.md](../plugin-dev/index.md)
- MCP 工具清单：[../mcp-tools/index.md](../mcp-tools/index.md)
