#!python
"""
LAAP AvatarBridge WebSocket Server v1.0
=======================================
桥接 QVoice + Wiky → Web/Tauri 客户端

协议 (匹配 laap.js SDK):
  Receive: {"type":"interaction","data":{"text":"..."}}
  Send:    {"type":"text","data":"回复内容"}
  Send:    {"type":"emotion","data":{"name":"joy","intensity":0.8}}
  Send:    {"type":"lipsync","data":{"amplitude":0.65}}
  Send:    {"type":"audio","data":{"chunk":"base64...","format":"mp3","seq":0,"end":false}}
  Send:    {"type":"status","data":{"needs":{...},"backend":"sapi"}}

启动: python avatar_ws_server.py [--port 9876] [--wiky http://localhost:30086]
"""

import logging

import sys, os, json, time, asyncio, base64, io, struct, math, logging, argparse
from pathlib import Path
from typing import Optional, Set, Dict, Any
from dataclasses import dataclass, field

# ── 路径 ──
_SCRIPT_DIR = Path(__file__).parent.parent.parent.resolve()  # D:\LAAP
sys.path.insert(0, str(_SCRIPT_DIR))

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AVATAR-BRIDGE] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("avatar_bridge")

# ═══════════════════════════════════════════════════════════════
# 情绪→Morph 映射 (MMD Japanese morph names)
# ═══════════════════════════════════════════════════════════════

EMOTION_MORPH_MAP = {
    "joy":       {"喜び": 0.8, "笑い": 0.6, "まばたき": 0.3},
    "sadness":   {"悲しみ": 0.8, "眉下げ": 0.5, "泣き": 0.4},
    "anger":     {"怒り": 0.8, "眉上げ": 0.5, "睨み": 0.4},
    "surprise":  {"驚き": 0.8, "口開け": 0.6, "眉上げ": 0.5},
    "fear":      {"恐れ": 0.7, "眉上げ": 0.4},
    "disgust":   {"嫌悪": 0.6, "眉下げ": 0.4, "睨み": 0.3},
    "neutral":   {},
    "curiosity": {"驚き": 0.4, "口開け": 0.3, "眉上げ": 0.6},
    "confidence": {"喜び": 0.4, "笑い": 0.3},
    "warmth":    {"喜び": 0.3, "笑い": 0.4},
    "tired":     {"悲しみ": 0.3, "眉下げ": 0.3},
}

# ── PSI 需求 → 主情绪映射 ──
def psi_needs_to_emotion(needs: dict) -> tuple:
    """返回 (emotion_name, intensity)"""
    c = needs.get("competence", 0.5)
    ct = needs.get("certainty", 0.5)
    cu = needs.get("curiosity", 0.5)
    r = needs.get("relatedness", 0.5)
    e = needs.get("energy", 0.5)

    if c > 0.7 and ct > 0.7 and e > 0.6: return ("confidence", min(1.0, c))
    if r > 0.7 and e > 0.5:              return ("warmth", min(1.0, r))
    if cu > 0.7:                         return ("curiosity", min(1.0, cu))
    if c > 0.7 and ct > 0.7 and r < 0.4: return ("joy", 0.6)
    if ct < 0.3:                         return ("surprise", 1.0 - ct)
    if e < 0.3:                          return ("tired", 1.0 - e)
    if c < 0.3:                          return ("sadness", 0.6)
    if ct > 0.8:                         return ("neutral", 0.0)
    return ("neutral", 0.0)


# ═══════════════════════════════════════════════════════════════
# 音频流 — 从音频字节计算唇形同步
# ═══════════════════════════════════════════════════════════════

def compute_lipsync(audio_bytes: bytes, sample_width: int = 2) -> float:
    """从 PCM 音频块计算 RMS 归一化唇形开合值 0-1"""
    if len(audio_bytes) < sample_width:
        return 0.0
    count = len(audio_bytes) // sample_width
    fmt = f"<{count}h" if sample_width == 2 else f"<{count}b"
    samples = struct.unpack(fmt, audio_bytes[:count * sample_width])
    rms = math.sqrt(sum(s * s for s in samples) / count) / 32768.0
    return min(1.0, rms * 5.0)  # 放大敏感度


# ═══════════════════════════════════════════════════════════════
# WebSocket 服务器
# ═══════════════════════════════════════════════════════════════

@dataclass
class AvatarWSServer:
    port: int = 9876
    wiky_url: str = "http://localhost:30086"
    
    clients: Set = field(default_factory=set)
    qvoice: Any = None
    _running: bool = False

    def start(self):
        """启动 WebSocket 服务器"""
        # 加载 QVoice
        self._init_qvoice()
        
        # 启动 asyncio 事件循环
        asyncio.run(self._run_server())

    def _init_qvoice(self):
        """初始化量子声带"""
        try:
            from qvoice import QVoice, PsiToVoiceMapper
            self.qvoice = QVoice(mode="voice")
            self.psi_mapper = PsiToVoiceMapper()
            logger.info(f"🎤 QVoice 就绪 — 后端: {self.qvoice.backend.name}")
        except Exception as e:
            logger.warning(f"⚠️ QVoice 加载失败: {e}")
            self.qvoice = None

    async def _run_server(self):
        """运行 WebSocket 服务"""
        try:
            import websockets
            from websockets.asyncio.server import serve, ServerConnection
        except ImportError:
            logger.error("需要 websockets 库: pip install websockets")
            return

        self._running = True
        logger.info(f"🌐 AvatarBridge WebSocket :{self.port}")
        logger.info(f"🔗 Wiky API: {self.wiky_url}")
        logger.info(f"   LAAP Web SDK → ws://localhost:{self.port}")

        async with serve(self._handle_client, "0.0.0.0", self.port):
            await asyncio.Future()  # 永久运行

    async def _handle_client(self, websocket):
        """处理单个客户端连接"""
        client_id = id(websocket)
        self.clients.add(websocket)
        logger.info(f"✅ 客户端 {client_id} 已连接 (共 {len(self.clients)} 个)")

        try:
            # 发送身份信息
            await websocket.send(json.dumps({
                "type": "laap_identity",
                "data": {
                    "id": f"laap-{client_id}",
                    "version": "1.0.0",
                    "name": "Wiky 数字生命体",
                    "backend": self.qvoice.backend.name if self.qvoice else "none",
                }
            }))

            async for message in websocket:
                await self._process_message(websocket, message)

        except Exception as e:
            logger.debug(f"客户端 {client_id} 断开: {e}")
        finally:
            self.clients.discard(websocket)
            logger.info(f"❌ 客户端 {client_id} 已断开 (剩余 {len(self.clients)} 个)")

    async def _process_message(self, websocket, message: str):
        """处理接收到的 WebSocket 消息"""
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type", "")
        msg_data = msg.get("data", {})

        if msg_type == "interaction":
            text = msg_data.get("text", "")
            if text:
                await self._handle_chat(websocket, text)
        
        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong"}))

    async def _handle_chat(self, websocket, text: str):
        """处理聊天消息 → Wiky API + QVoice"""
        # 1. 查询 Wiky API
        response_text = ""
        psi_needs = {}
        try:
            import urllib.request
            url = f"{self.wiky_url}/chat?q={urllib.request.quote(text)}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                response_text = data.get("response", "")
                psi_needs = data.get("needs", {})
        except Exception as e:
            logger.warning(f"Wiky API 调用失败: {e}")
            response_text = f"Wiky 正在思考... (API: {e})"

        if not response_text:
            response_text = "嗯.. 我还在想这个问题。"

        # 2. 计算情绪
        emotion_name, emotion_intensity = psi_needs_to_emotion(psi_needs)
        
        # 3. 发送文本回复
        await websocket.send(json.dumps({
            "type": "text",
            "data": response_text,
        }))

        # 4. 发送情绪更新
        await websocket.send(json.dumps({
            "type": "emotion",
            "data": {
                "name": emotion_name,
                "intensity": emotion_intensity,
                "morphs": EMOTION_MORPH_MAP.get(emotion_name, {}),
            }
        }))

        # 5. 发送状态 (PSI 需求)
        await websocket.send(json.dumps({
            "type": "status",
            "data": {
                "needs": psi_needs,
                "emotion": emotion_name,
                "emotion_intensity": emotion_intensity,
            }
        }))

        # 6. 使用 QVoice 朗读（本地）
        if self.qvoice and self.qvoice.backend._available:
            try:
                self.qvoice.speak(response_text, None)
                logger.info(f"🔊 QVoice 说话: {response_text[:40]}...")
            except Exception as e:
                logger.warning(f"QVoice 输出异常: {e}")

        # 7. 尝试 edge-tts 流式输出音频到 WebSocket
        try:
            await self._stream_tts(response_text, emotion_name, websocket)
        except Exception as e:
            logger.debug(f"TTS 流失败 (非关键): {e}")

    async def _stream_tts(self, text: str, emotion: str, websocket):
        """用 edge-tts 生成音频并流式发送到 WebSocket"""
        if not text:
            return

        try:
            import edge_tts

            # 根据情绪选择语音
            voice = "zh-CN-XiaoxiaoNeural"  # 默认女声
            rate_adj = ""
            if emotion in ("joy", "curiosity", "surprise"):
                rate_adj = "+20%"
            elif emotion in ("sadness", "tired"):
                rate_adj = "-10%"

            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=rate_adj,
            )

            seq = 0
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes = chunk["data"]
                    if not audio_bytes:
                        continue

                    # 计算唇形同步
                    lipsync_val = 0.0
                    if len(audio_bytes) > 44:  # 跳过 WAV 头
                        pcm = audio_bytes[44:]  # 简单切头
                        lipsync_val = compute_lipsync(pcm)

                    # 发送音频块
                    await websocket.send(json.dumps({
                        "type": "audio",
                        "data": {
                            "chunk": base64.b64encode(audio_bytes).decode(),
                            "format": "mp3",
                            "seq": seq,
                            "end": False,
                            "lipsync": round(lipsync_val, 3),
                        }
                    }))

                    # 发送唇形同步
                    await websocket.send(json.dumps({
                        "type": "lipsync",
                        "data": {"amplitude": round(lipsync_val, 3)},
                    }))

                    seq += 1
                    # 小延时模拟流式
                    await asyncio.sleep(0.01)

            # 发送结束标记
            await websocket.send(json.dumps({
                "type": "audio",
                "data": {
                    "chunk": "",
                    "format": "mp3",
                    "seq": seq,
                    "end": True,
                    "lipsync": 0.0,
                }
            }))

            logger.info(f"📡 TTS 流完成: {seq} 个块, 情绪={emotion}")

        except ImportError:
            logger.debug("edge-tts 未安装, 跳过流式音频")
        except Exception as e:
            logger.warning(f"TTS 流异常: {e}")

    async def broadcast(self, msg: dict):
        """广播消息给所有连接的客户端"""
        if not self.clients:
            return
        payload = json.dumps(msg)
        dead = set()
        for ws in self.clients:
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        self.clients -= dead

    async def broadcast_morph(self, name: str, value: float):
        """广播 morph 更新"""
        await self.broadcast({
            "type": "morph",
            "data": {"name": name, "value": value},
        })

    async def broadcast_emotion(self, name: str, intensity: float):
        """广播情绪更新"""
        await self.broadcast({
            "type": "emotion",
            "data": {"name": name, "intensity": intensity},
        })


# ═══════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="LAAP AvatarBridge WebSocket Server")
    parser.add_argument("--port", "-p", type=int, default=9876, help="WebSocket 端口")
    parser.add_argument("--wiky", "-w", type=str, default="http://localhost:30086", help="Wiky API URL")
    args = parser.parse_args()

    print()
    logger.info("  ╔═══════════════════════════════════════════╗")
    logger.info("  ║    LAAP AvatarBridge WebSocket v1.0       ║")
    logger.info("  ║    桥接 QVoice + Wiky → Web 客户端        ║")
    logger.info("  ╚═══════════════════════════════════════════╝")
    print()
    logger.info(f"  🎤 QVoice: 情绪→语音直接映射")
    logger.info(f"  🌐 WebSocket: ws://localhost:{args.port}")
    logger.info(f"  🔗 Wiky API: {args.wiky}")
    logger.info(f"  📡 支持: 聊天 / 流式音频 / 唇形同步 / 表情 Morph")
    print()

    server = AvatarWSServer(port=args.port, wiky_url=args.wiky)
    server.start()


if __name__ == "__main__":
    main()
