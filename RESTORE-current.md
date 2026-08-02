# 当前版本恢复与回退说明

版本基线：`5e95f14`

本文件描述当前源码运行版本，不修改架构迁移前的历史快照：

```text
E:\worke\hanako-agent-LAAP-architecture-snapshot-20260802-1530\RESTORE.md
```

## 恢复源码

```powershell
cd E:\worke\hanako-agent-LAAP
git status
git log -1 --oneline
```

当前版本应包含：

- `PSIDriver` canonical 主体入口；
- AGIAgent CognitiveBus/WorldModel/UnifiedMemory 持久化；
- `load_status` 降级报告；
- `LAAP_PERSISTENCE_STRICT=1` 严格门；
- 异步 Consciousness Harness 桥接。

如需回退到当前提交前：

```powershell
git revert 5e95f14
git revert d78d0ef
```

请优先使用 `git revert`，不要改写共享历史。

## 运行 canonical AGI Runtime

```powershell
$env:LAAP_COGNITIVE_RUNTIME="agi"
$env:LAAP_PSI_RECEIPT_REQUIRED="1"
```

需要严格阻断降级认知状态时：

```powershell
$env:LAAP_PERSISTENCE_STRICT="1"
```

## 维护 bypass

仅限明确分类的基础设施维护：

```powershell
$env:LAAP_ALLOW_PSI_BYPASS="1"
# 执行维护操作
Remove-Item Env:LAAP_ALLOW_PSI_BYPASS
```

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\compare_cognitive_runtimes.py `
  --output "$env:TEMP\laap-restore-compare.json"

python -m pytest -q `
  laap/config/test_paths.py `
  laap/colony/test_guardian.py `
  laap/evolution/test_rsi_sandbox.py
```

预期：AGIAgent 6/6、canonical=True、single_cycle_per_turn=True、Shadow 6/6、核心回归 108 passed。

## 历史快照

架构迁移前快照保持只读，不要将当前版本的文件复制回历史快照目录：

```text
E:\worke\hanako-agent-LAAP-architecture-snapshot-20260802-1530\RESTORE.md
```
