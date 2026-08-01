# LAAP 项目置顶记忆（pinned）

## 当前活跃目标

- 完成 LAAP 与 Hanako 的深度集成验收。
- 保持 22 项共振协议 backlog 的任务板与代码状态一致。
- 建立 LAAP 独立的更新源与 patch 分支。

## 关键文件路径

- 任务板：`D:\LAAP\.task_board.json`
- 宪章：`D:\LAAP\ARIS_CHARTER.md`
- 集成计划：`D:\LAAP\hanako\LAAP_Hanako_Deep_Integration_Plan.md`
- 安装入口：`D:\LAAP\setup_aris_hanako.cmd`
- 环境修复脚本：`D:\LAAP\scripts\laap_env_fix_and_smoke.py`
- 人格植入脚本：`D:\LAAP\scripts\implant_laap_persona.py`

## 高频工作流

1. **修改 LAAP 功能**：先读 `.task_board.json` → 改 `laap/` 或 `hanako/` → 跑 `python scripts/laap_env_fix_and_smoke.py`。
2. **新增插件**：在 `hanako/plugins/` 创建目录 → 更新 `hanako/desktop/src/react/App.tsx`、`types.ts`、`tsconfig.json`。
3. **治理操作**：宪章守护者通过 sidecar `/guardian/*` 或 MCP `guardian_*` 工具执行。
4. **预设市场**：通过 sidecar `/preset/list|get|clone` 浏览/克隆 LAAPer 预设。

## 已知环境约束

- Windows 需要 `pywin32` 才能正常导入 `laap` 包。
- Hanako 桌面端构建需要 Node.js 20+。
- 运行时占用端口：2668、11521、8765。

## 谨记

- 不向用户确认完成度时，不主动说“全部完成”。
- 每次技术回答优先给出文件路径，其次是命令，最后是解释。
