"""[DEPRECATED] aris-cognitive-bus.py — 已被 laap-cognitive-bus-bridge.ts 替代

此文件原为 mock CognitiveBus WebSocket 服务器。
新版直接连接 LAAP 后端 CognitiveBus（ws://127.0.0.1:8765），
由 hanako 插件进程内调用，无需独立 Python 服务。

启动方式：
    在 d:\\LAAP\\hanako 下执行：
    aris-bridge\\start-aris-instance.cmd

或手动启动：
    1. python aris-bridge\\aris-engine\\sidecar.py
    2. npm run server
    3. npm run start:dev
"""
import sys

print(__doc__, file=sys.stderr)
sys.exit(0)
