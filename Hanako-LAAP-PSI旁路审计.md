# Hanako-LAAP PSI 旁路审计

更新时间：2026-08-02

## 审计原则

凡是代表主体感知、决定、行动、表达的路径，必须经过 PSI；纯基础设施、实验和内部计算路径不强行伪装成主体行为。

## 已覆盖的主体入口

```text
Python Runtime:
  laap.runtime.Agent
  laap.runtime.legacy
  AgentLifecycleAdapter.run/chat/chat_stream
  AgentLifecycleAdapter.call_tool/execute_tool

Hanako API:
  /agents/create 默认 Agent
  /agents/{id}/chat
  /agents/{id}/rsi
  /rsi/approve/{change_id}
  /triphase/memory/store

Hanako CLI:
  默认 Agent
  CodexAgent
  LifelikeAgent

Hanako Desktop:
  SessionCoordinator.prompt()
  SessionCoordinator.promptSession()
  严格模式：LAAP_PSI_GATE_REQUIRED=1
```

## 发现的直接 LLM 调用

### 已由主体入口覆盖

```text
laap/agent_core/agent.py
```

这里的 `self.llm.chat/generate/stream_chat` 属于 Runtime 后端执行层；API/CLI canonical Agent 通过 `AgentLifecycleAdapter` 进入，不应作为独立公共入口使用。

### 非普通主体入口

```text
laap/agi/hermes_integration.py
laap/agi/evolution_engine.py
laap/evolution/aevo/meta_editor.py
laap/domain_sdks/finquant/agent/conversation.py
```

当前定位为：

- 工具或 Hermes 内部适配；
- RSI/代码演化内部处理；
- 领域实验 Agent；
- 独立 SDK 试验路径。

它们不应直接被当作主聊天 Runtime 使用；如果未来升级为公开主体 Agent，必须接入 `laap.runtime` 和 PSI Gateway。

## 当前结论

主用户交互链路已经具备 PSI 边界；仓库仍保留若干实验/领域独立调用点，但没有把它们伪装成主数字生命主体路径。

## 后续动作

1. 禁止新的公共 Agent 直接导出 LLM 调用；
2. `AGIAgent.process_interaction(use_psi=False)` 已默认阻断；只有在 PowerShell 中显式执行 `$env:LAAP_ALLOW_PSI_BYPASS="1"` 才能用于分类后的基础设施工作，完成后应执行 `Remove-Item Env:LAAP_ALLOW_PSI_BYPASS` 清除；
3. 为领域 SDK 增加 Runtime 适配器后再纳入主体路径；
4. 逐步将完整 `laap.agi.PSIDriver` 接入 canonical Runtime；
5. 保持所有旁路调用有明确的实验/基础设施归类。
