"""[DEPRECATED] aris-hanako-server.py — 已被 Hanako 原生 server 替代

此文件原为 mock Hanako 后端 API（监听 2668）与 WS 转发（2669）。
新版直接使用 Hanako 内置 server，并由 laap-cognitive-bus-bridge.ts
负责与 LAAP CognitiveBus 的桥接，无需独立 Python 服务。

启动方式：
    在 d:\\LAAP\\hanako 下执行：
    npm run server

或在开发模式下：
    npm run start:dev
"""
import sys

print(__doc__, file=sys.stderr)
sys.exit(0)
