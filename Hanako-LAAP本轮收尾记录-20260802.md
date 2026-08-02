# Hanako-LAAP 本轮收尾记录

日期：2026-08-02

## 结论

本轮目标已完成，源码主路径可运行；PSI、AGIAgent、DeepSeek、Sidecar 和 Web Chat 已完成联动验证。

## 已完成

- Web Chat → `hub.send()` → Session submit → PSI gate 链路确认。
- Sidecar 真实请求验证通过：
  - `POST /before_turn`：200
  - `POST /after_turn`：200
- Sidecar 意识总线收到真实用户输入和模型响应。
- DeepSeek 真实 Provider 调用通过，未使用 fallback。
- AGIAgent 已设为默认 Cognitive Runtime。
- `BridgeCognitiveRuntime` 保留为显式回退：
  - `LAAP_COGNITIVE_RUNTIME=bridge`
- Web 端工作台支持输入 Windows 文件夹路径。
- DSML/ANTML/XML/tool-call 协议残片不再进入用户可见聊天文本。
- 客户端构建、TypeScript 检查和相关专项测试通过：
  - 93 个协议/流式清洗测试通过。

## 当前架构决定

```text
AGIAgent（默认主体认知）
    → PSIDriver
    → PSI gate
    → LLM 表达通道

BridgeCognitiveRuntime：兼容与显式回退，不自动静默切换。
```

AGIAgent 失败时默认阻断，不自动降级，以避免主体认知状态无感变化。

运行时策略：

```text
默认 → AGIAgent
AGIAgent 初始化/运行失败 → 报错并阻断
LAAP_COGNITIVE_RUNTIME=bridge → 使用 Bridge
```

未来如需容灾，只允许通过显式开关启用：

```powershell
$env:LAAP_RUNTIME_FALLBACK="bridge"
```

该开关未实现/未开启前，系统不会静默切换；启用后也必须记录告警和回退原因。

## 非阻断事项

- HermesIntegration 当前不可用，原因是 `HERMES_ROOT` 指向的目录缺少 `run_agent.py`。
- 当前 DeepSeek 直连路径不依赖 Hermes，因此不影响聊天和 PSI 主链路。
- Python 全量 pytest 未执行：当前虚拟环境没有安装 pytest；未为此安装额外依赖。
- 全量发行构建、Installer、seed 和许可证处理不属于本轮目标。

## 最新关键提交

```text
e8fa1eb feat: make agi the default cognitive runtime
ff51204 fix: hide provider tool protocol from chat prose
3a32ad3 fix: allow web workspace path selection
```

状态：本轮收尾，后续仅进行观察性回归，不再扩大架构改动范围。
