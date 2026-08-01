# 插件开发教程

本教程介绍如何为 Hanako 桌面端开发一个插件。Hanako 的插件系统由 `hanako/packages/plugin-sdk` 提供统一接口，所有插件遵循相同的目录结构与生命周期。

## 插件结构

一个最小可用的插件目录结构如下：

```
my-plugin/
├── manifest.json       # 清单文件（必需）
├── index.ts            # 入口脚本（必需）
├── Panel.tsx           # 主面板组件（按需）
├── Overlay.tsx         # 浮层组件（按需）
├── styles.css          # 样式（按需）
└── icon.svg            # 插件图标（按需）
```

- `manifest.json`：声明插件元信息、权限要求、入口文件。
- `index.ts`：实现 `onload` / `onunload` 生命周期钩子。
- 组件文件：插件可挂载到 Hanako 主面板（`ActivePanel`）或作为浮层（`overlay`）出现在泡泡之上。
- 样式与图标：与组件同目录，构建时一起打包。

## manifest.json 字段说明

`manifest.json` 是插件的"身份证"，Hanako 加载插件时第一个读取的就是它。完整字段如下：

```json
{
  "id": "com.example.my-plugin",
  "name": "我的插件",
  "version": "0.1.0",
  "description": "一个示例插件，演示 Hanako 插件结构",
  "author": "your-name <you@example.com>",
  "homepage": "https://example.com/my-plugin",
  "minAppVersion": "0.6.0",
  "entry": "./index.ts",
  "panel": "./Panel.tsx",
  "overlay": "./Overlay.tsx",
  "styles": ["./styles.css"],
  "icon": "./icon.svg",
  "permissions": ["cognitive-bus:read", "memory:write", "mcp:call"],
  "config": {
    "defaultGreeting": "你好"
  },
  "activationPoints": ["bubble-click", "command:my-plugin.hello"]
}
```

字段含义：

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 全局唯一插件 ID，建议用反向域名 |
| `name` | string | 是 | 显示名 |
| `version` | string | 是 | 语义化版本号 |
| `description` | string | 否 | 一句话描述 |
| `author` | string | 否 | 作者信息 |
| `homepage` | string | 否 | 项目主页 |
| `minAppVersion` | string | 是 | 兼容的最低 Hanako 版本 |
| `entry` | string | 是 | 入口脚本（相对路径） |
| `panel` | string | 否 | 主面板组件路径 |
| `overlay` | string | 否 | 浮层组件路径 |
| `styles` | string[] | 否 | 样式文件列表 |
| `icon` | string | 否 | 图标 SVG |
| `permissions` | string[] | 是 | 权限声明，详见下表 |
| `config` | object | 否 | 默认配置，用户可在设置中覆盖 |
| `activationPoints` | string[] | 否 | 触发时机（如点击泡泡、命令面板） |

权限取值：

| 权限 | 含义 |
|---|---|
| `cognitive-bus:read` | 只读 CognitiveBus 事件流 |
| `cognitive-bus:write` | 向 CognitiveBus 发指令 |
| `memory:read` / `memory:write` | 访问 Memory Vault |
| `mcp:call` | 调用任意 MCP 工具 |
| `mcp:call:tool_name` | 仅允许调用指定 MCP 工具 |
| `network:fetch` | 允许发起外部网络请求 |
| `fs:read` / `fs:write` | 文件系统访问（受沙箱约束） |

## 插件生命周期

插件生命周期由 `plugin-sdk` 的 `PluginContext` 管理，入口脚本需要导出 `onload` 与 `onunload` 两个函数：

```typescript
// index.ts
import type { PluginContext } from "@hanako/plugin-sdk";

export async function onload(ctx: PluginContext): Promise<void> {
  // ctx 提供：
  //   ctx.bus        —— CognitiveBus 读写句柄
  //   ctx.memory     —— Memory Vault 客户端
  //   ctx.mcp        —— MCP 工具调用器
  //   ctx.config     —— 用户配置（已与默认值合并）
  //   ctx.logger     —— 日志器
  //   ctx.registerCommand(id, handler)
  //   ctx.registerPanel(id, component)
  //   ctx.registerOverlay(id, component)

  ctx.logger.info("my-plugin loaded");

  ctx.registerCommand("my-plugin.hello", () => {
    ctx.bus.emit("ui:notify", { text: ctx.config.defaultGreeting });
  });

  // 监听 CognitiveBus 事件
  ctx.bus.on("lifeform:interaction", (evt) => {
    ctx.logger.debug("interaction seen", evt);
  });
}

export async function onunload(ctx: PluginContext): Promise<void> {
  // 资源清理：取消订阅、关闭句柄
  ctx.logger.info("my-plugin unloaded");
}
```

生命周期触发时机：

| 事件 | 触发 |
|---|---|
| `onload` | 用户在设置中启用插件，或 Hanako 启动时插件已被启用 |
| `onunload` | 用户禁用插件、Hanako 关闭、热重载前 |

`onunload` 必须可重入且幂等——所有订阅都应在 `ctx` 内自动跟踪，卸载时由 sdk 统一清理。

## 在 App.tsx 挂载插件

Hanako renderer 的入口 `hanako/renderer/src/App.tsx` 通过 `PluginHost` 加载所有已启用插件。挂载一个新插件分三步：

### 1. 在 plugin registry 注册

```typescript
// hanako/renderer/src/plugins/registry.ts
import { lazy } from "react";

export const pluginRegistry = {
  "com.example.my-plugin": {
    manifest: () => import("./my-plugin/manifest.json"),
    entry: lazy(() => import("./my-plugin/index")),
    panel: lazy(() => import("./my-plugin/Panel")),
    overlay: lazy(() => import("./my-plugin/Overlay")),
  },
};
```

使用 `lazy` + 动态 `import()` 让插件代码进入独立 chunk，避免拖慢首屏。

### 2. 在 ActivePanel 中渲染

```tsx
// App.tsx 片段
import { pluginRegistry } from "./plugins/registry";
import { ActivePanel } from "./components/ActivePanel";

function App() {
  const [activePluginId, setActivePluginId] = useState<string | null>(null);

  return (
    <div className="hanako-shell">
      <BubbleLayer onActivate={setActivePluginId} />
      <ActivePanel pluginId={activePluginId} registry={pluginRegistry} />
      <OverlayLayer registry={pluginRegistry} />
    </div>
  );
}
```

`ActivePanel` 内部会根据 `pluginId` 在 registry 中找到 `panel` 组件并 lazy 渲染：

```tsx
// components/ActivePanel.tsx
import { Suspense } from "react";

export function ActivePanel({ pluginId, registry }) {
  if (!pluginId || !registry[pluginId]?.panel) return null;
  const Panel = registry[pluginId].panel;
  return (
    <Suspense fallback={<div className="panel-fallback">加载中…</div>}>
      <Panel />
    </Suspense>
  );
}
```

### 3. overlay 层

`OverlayLayer` 监听 `bus.on("overlay:show")` 事件，根据 `pluginId` 渲染对应 overlay 组件，z-index 高于 ActivePanel，用于临时浮层（如确认对话框、技能预览）。

## tsconfig.json include 配置

为了让 TypeScript 编译器识别插件目录，需要在 `hanako/renderer/tsconfig.json` 的 `include` 中加入插件路径：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "baseUrl": ".",
    "paths": {
      "@hanako/plugin-sdk": ["../packages/plugin-sdk/src/index.ts"]
    }
  },
  "include": [
    "src/**/*",
    "src/plugins/**/*",
    "../packages/plugin-sdk/src/**/*"
  ]
}
```

关键点：

- `include` 必须覆盖 `src/plugins/**/*`，否则插件代码不会被编译。
- `paths` 把 `@hanako/plugin-sdk` 别名指向 sdk 源码，方便本地联调。
- 插件目录建议放在 `src/plugins/<plugin-id>/` 下，与 registry 路径对齐。

## 示例：hello-world 插件

下面给出一个完整可运行的 hello-world 插件。

### manifest.json

```json
{
  "id": "com.example.hello-world",
  "name": "Hello World",
  "version": "0.1.0",
  "description": "最小可运行的 Hanako 插件示例",
  "author": "demo",
  "minAppVersion": "0.6.0",
  "entry": "./index.ts",
  "panel": "./Panel.tsx",
  "styles": ["./styles.css"],
  "permissions": ["cognitive-bus:read", "cognitive-bus:write"],
  "config": {
    "defaultGreeting": "你好，世界"
  },
  "activationPoints": ["command:hello-world.show"]
}
```

### index.ts

```typescript
import type { PluginContext } from "@hanako/plugin-sdk";

export async function onload(ctx: PluginContext): Promise<void> {
  ctx.logger.info("hello-world loaded");

  ctx.registerCommand("hello-world.show", () => {
    ctx.bus.emit("ui:notify", { text: ctx.config.defaultGreeting });
  });

  ctx.bus.on("lifeform:interaction", (evt) => {
    ctx.logger.debug("see interaction:", evt);
  });
}

export async function onunload(ctx: PluginContext): Promise<void> {
  ctx.logger.info("hello-world unloaded");
}
```

### Panel.tsx

```tsx
import { useEffect, useState } from "react";
import { usePluginContext } from "@hanako/plugin-sdk";

export default function Panel() {
  const ctx = usePluginContext();
  const [count, setCount] = useState(0);

  useEffect(() => {
    const off = ctx.bus.on("lifeform:interaction", () => setCount((c) => c + 1));
    return () => off();
  }, [ctx]);

  return (
    <div className="hello-panel">
      <h2>Hello World</h2>
      <p>已捕获 {count} 次生命体交互</p>
      <button onClick={() => ctx.bus.emit("ui:notify", { text: ctx.config.defaultGreeting })}>
        打招呼
      </button>
    </div>
  );
}
```

### styles.css

```css
.hello-panel {
  padding: 16px;
  color: #FFD700;
  background: rgba(26, 26, 46, 0.9);
  border-radius: 12px;
}
.hello-panel button {
  margin-top: 8px;
  padding: 6px 12px;
  background: #FFD700;
  color: #1a1a2e;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
```

把上面四个文件放到 `hanako/renderer/src/plugins/hello-world/`，在 registry 中注册后重启 Hanako 即可在命令面板看到 `hello-world.show`。

## 调试

### 本地预览

Hanako renderer 基于 Vite，支持热重载。在 `hanako/` 目录下执行：

```bash
npm run dev
```

Vite 启动后会监听 `http://localhost:5173`，Hanako Electron 主进程会自动加载这个地址。修改插件代码后浏览器自动刷新，无需重启 Electron。

### 日志查看

- Renderer 日志：DevTools Console（`Ctrl+Shift+I`）。
- Main 进程日志：`hanako/logs/main.log`。
- Plugin 日志（通过 `ctx.logger` 写入）：`hanako/logs/plugins/<plugin-id>.log`。

### 单元测试

`plugin-sdk` 提供 `mockPluginContext()` 工厂，可在 Node 环境模拟 ctx：

```typescript
import { describe, it, expect } from "vitest";
import { mockPluginContext } from "@hanako/plugin-sdk/testing";
import { onload } from "../src/index";

describe("hello-world", () => {
  it("registers show command on load", async () => {
    const ctx = mockPluginContext();
    await onload(ctx);
    expect(ctx.registerCommand.mock.calls[0][0]).toBe("hello-world.show");
  });
});
```

运行：

```bash
cd hanako
npm test -- hello-world
```

### 权限调试

如果插件在调用 MCP 工具或写 Memory 时被拒绝，先检查：

1. `manifest.json` 的 `permissions` 是否包含所需权限。
2. 用户是否在设置中授予了该权限（首次启用插件会弹出授权框）。
3. sidecar 日志 `state/logs/aris-sidecar.log` 中是否有 `403` 记录。

## 进阶

- 想让插件响应 MCP 工具调用 → 在 `onload` 中用 `ctx.mcp.register("my-plugin.tool", handler)`。
- 想把插件打包成技能包分发 → 参考 [../skill-packs/index.md](../skill-packs/index.md)。
- 想让插件跨生命体同步 → 用 `ctx.bus` 监听 `skill-sync:*` 事件。

完整 API 签名见 `hanako/packages/plugin-sdk/src/index.ts`。
