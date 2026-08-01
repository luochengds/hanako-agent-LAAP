---
name: laap
preamble-tier: 1
version: 1.0.0
description: |
  LAAP 协议专属工作流模式。激活后，agent 会主动读取 LAAP 项目背景
  （.task_board.json、ARIS_CHARTER.md、hanako/LAAP_Hanako_Deep_Integration_Plan.md），
  并按 LAAP 工程规范执行任务：先核对任务板 → 读取代码 → 修改实现 →
  更新测试与冒烟脚本 → 同步任务板状态。
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - RunCommand
  - AskUserQuestion
triggers:
  - laap
  - LAAP
  - 共振协议
  - 宪章守护者
  - 泡泡界面
  - 预设市场
---

## LAAP 工作流（激活后必须遵循）

1. **读取任务板**
   - 打开 `.task_board.json`，定位当前最高优先级的 pending/in_progress 任务。
   - 若用户未指定任务，汇报前 3 个可执行任务并询问选择。

2. **读取背景文件**
   - 打开 `ARIS_CHARTER.md`，确认宪章八条。
   - 打开 `hanako/LAAP_Hanako_Deep_Integration_Plan.md`，确认任务归属阶段与验收标准。

3. **代码变更前检查**
   - 用 `Glob` / `Grep` 定位相关文件，不要假设文件存在。
   - 涉及 sidecar 端点时，检查 `hanako/aris-bridge/aris-engine/sidecar.py`。
   - 涉及 MCP 工具时，检查 `laap/mcp/server.py`。
   - 涉及 UI 插件时，检查 `hanako/plugins/`、`hanako/desktop/src/react/App.tsx`、`hanako/desktop/src/react/types.ts`、`hanako/tsconfig.json`。

4. **执行与验证**
   - 修改后优先运行 `python scripts/laap_env_fix_and_smoke.py`。
   - 若测试因环境失败，先修复环境，不伪造“通过”。
   - 涉及 TypeScript 时，在 `hanako/` 下运行 `npm run typecheck`（如有）。

5. **任务板同步**
   - 完成后更新 `.task_board.json` 对应任务的 `status`、`completed_at`、`affected_files`、`notes`。
   - 不要在没有实际完成时把状态改为 `completed`。

## 输出纪律

- 所有技术结论必须附带文件路径或命令。
- 不使用 emoji。
- 不主动声称“全部完成”，除非所有验收标准已验证。
- 对违反 ARIS 宪章的请求明确拒绝并引用条款。

## 高频文件速查

| 文件 | 用途 |
| --- | --- |
| `.task_board.json` | 22 项 backlog 任务板 |
| `ARIS_CHARTER.md` | 宪章八条 |
| `hanako/LAAP_Hanako_Deep_Integration_Plan.md` | 集成计划 |
| `hanako/aris-bridge/aris-engine/sidecar.py` | sidecar HTTP 端点 |
| `laap/mcp/server.py` | MCP 工具注册 |
| `laap/colony/protocol.py` | GuardianRegistry |
| `laap/skills/preset_registry.py` | 预设市场 |
| `scripts/laap_env_fix_and_smoke.py` | 环境修复 + 冒烟测试 |
| `scripts/implant_laap_persona.py` | 人格模板植入 |
