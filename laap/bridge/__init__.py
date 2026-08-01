"""
LAAP Avatar Bridge — WebSocket 网关
将 QVoice + Wiky 连接到 Web / Tauri 客户端

架构:
  Web Client (laap.js SDK)
    ↕ WebSocket :9876
  AvatarBridge WS Server
    ├→ Wiky HTTP API (:30086) — 聊天 + PSI 需求
    ├→ QVoice — 情绪语音 + 唇形同步
    └→ 广播到客户端:
         ├ text      — 聊天回复
         ├ emotion   — 情绪名 + 强度 (morph)
         ├ lipsync   — 嘴形开合 0-1
         └ audio     — 流式音频块
"""

__version__ = "1.0.0"
