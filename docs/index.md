# LAAP Hanako 文档

LAAP（Living Agent Application Protocol）是一套**数字生命体架构**。Hanako 是它的官方桌面端参考实现。本目录是 LAAP Hanako 的开发者文档总入口，覆盖快速上手、架构、插件开发、MCP 工具、技能包、协议规范等全部主题。

## 文档目录树

```
docs/
├── index.md                       # 本页 —— 文档总入口
├── getting-started/
│   └── index.md                   # 快速开始：安装 / 诞生仪式 / 端口
├── architecture/
│   └── index.md                   # 三层架构 + P1–P5 阶段拆解
├── plugin-dev/
│   └── index.md                   # Hanako 插件开发教程
├── mcp-tools/
│   └── index.md                   # MCP 工具清单与 sidecar 端点对应
├── skill-packs/
│   └── index.md                   # 技能包结构与 skill-sync 四步学习
├── protocols/
│   └── index.md                   # LAAP 七协议规范
│
├── architecture-overview.md       # 既有：代码层分层与多语言策略
├── cognitive-architecture.md      # 既有：PSI / EG-MRSI / Self-Model
├── quickstart.md                  # 既有：CLI 视角的快速开始
├── mcp-integration.md             # 既有：MCP 集成说明
├── security-model.md              # 既有：安全模型
├── cli-commands.md                # 既有：CLI 命令手册
└── ... 其他既有文档
```

新文档以子目录 + `index.md` 的形式组织，既有平铺文档保留不动，两者通过相互引用衔接。

## 快速链接

按角色快速定位：

| 我是… | 推荐路径 |
|---|---|
| 第一次接触 LAAP | [getting-started/](./getting-started/index.md) → [architecture/](./architecture/index.md) |
| 想给 Hanako 写插件 | [plugin-dev/](./plugin-dev/index.md) |
| 想调用 LAAP 的 MCP 工具 | [mcp-tools/](./mcp-tools/index.md) |
| 想把生命体嵌入自己的网站 | `laap/web_sdk/`（`runtime.py` / `laap.js`）+ [skill-packs/](./skill-packs/index.md) |
| 想读 LAAP 协议规范 | [protocols/](./protocols/index.md) |
| 想理解认知引擎 | [../architecture-overview.md](./architecture-overview.md) + [../cognitive-architecture.md](./cognitive-architecture.md) |
| 想看 CLI 命令 | [cli-commands.md](./cli-commands.md) |
| 想了解安全模型 | [security-model.md](./security-model.md) |

## 阶段路线图

LAAP 的工程交付按 P1–P5 五个阶段推进，文档与阶段一一对应：

| 阶段 | 主题 | 主要文档 |
|---|---|---|
| P1 | 核心认知基建（Memory Vault / 因果 / 世界模型 / Truth Grounding / RSI） | [architecture/](./architecture/index.md)、[protocols/](./protocols/index.md) |
| P2 | 泡泡界面与诞生仪式 | [getting-started/](./getting-started/index.md)、[plugin-dev/](./plugin-dev/index.md) |
| P3 | 分布式社区基建（identity-pki / p2p-relay / 1v1 / trio / skill-sync） | [protocols/](./protocols/index.md)、[mcp-tools/](./mcp-tools/index.md) |
| P4 | 共享知识与共同进化（Memex / Coevolution / WitnessTrail / CharterGuardian） | [architecture/](./architecture/index.md)、[protocols/](./protocols/index.md) |
| P5 | 打包发行（installer / laaper-market / docs-api / charter-opensource） | 本页、[skill-packs/](./skill-packs/index.md) |

## Web SDK

P5-docs-api 同时交付了浏览器端 / Python 端 Web SDK，用于把数字生命体能力嵌入任意第三方应用：

| 文件 | 角色 |
|---|---|
| `laap/web_sdk/runtime.py` | Python 端 `WebLifeform` 运行时，封装 sidecar 调用、MCP 调用、宪章签署 |
| `laap/web_sdk/laap.js` | 浏览器端 `LAAPClient` 类，基于 fetch 调用 sidecar HTTP 端点 |
| `laap/web_sdk/__init__.py` | 包入口 |

最小用法（Python）：

```python
from laap.web_sdk.runtime import WebLifeform

w = WebLifeform("my-site-spirit", site_url="https://example.com")
w.connect_sidecar("http://127.0.0.1:11521", token="<ARIS_SIDECAR_TOKEN>")
w.sign_charter()                          # 自动完成宪章签署
result = w.call_mcp("memory_retrieve", {"query": "昨天的对话", "top_k": 3})
print(w.to_dict())
```

最小用法（浏览器）：

```html
<script src="/laap.js"></script>
<script>
  const c = new LAAPClient({ baseUrl: "http://127.0.0.1:11521", token: "<TOKEN>" });
  await c.signCharter("my-site-spirit");
  const presets = await c.listPresets();
</script>
```

完整 API 见源码注释。

## 版本信息

| 项 | 值 |
|---|---|
| 文档版本 | 1.0.0 |
| 对应 Hanako 版本 | 0.6.2+ |
| 对应 LAAP 协议版本 | v1.0 |
| 最后更新 | 2026-08-01 |

如需查看运行时版本，执行：

```bash
laap --version
cat VERSION.json
```

## 反馈

文档问题欢迎在主仓库提 issue，或直接修改对应 `index.md` 后提交 PR。
