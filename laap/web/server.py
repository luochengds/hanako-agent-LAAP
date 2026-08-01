"""
LAAP Web Server - HTTP(8081) + WebSocket(8766) + Voice
Integrated: static files + real-time chat + emotion sync + TTS
"""

import logging
logger = logging.getLogger(__name__)

import os, sys, json, time, threading, base64, traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

HTTP_PORT = 8081
WS_PORT = 8766
STATIC_DIR = Path(__file__).parent.parent / "web" / "static"

_agent = None
_ws_clients = set()
_ws_lock = threading.Lock()

# ── TTS ──
from laap.web.voice_bridge import tts_to_base64

MIME = {'.vrm':'application/octet-stream','.glb':'model/gltf-binary','.gltf':'model/gltf+json',
        '.js':'application/javascript','.css':'text/css','.html':'text/html; charset=utf-8',
        '.json':'application/json','.png':'image/png','.wasm':'application/wasm'}

class HTTPHandler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(STATIC_DIR),**kw)
    def guess_type(self,p): return MIME.get(os.path.splitext(p)[1].lower()) or super().guess_type(p)
    def log_message(self,*a): pass
    def end_headers(self): self.send_header("Access-Control-Allow-Origin","*"); SimpleHTTPRequestHandler.end_headers(self)

def ws_broadcast(data):
    msg = json.dumps(data, ensure_ascii=False)
    with _ws_lock:
        dead = set()
        for ws in list(_ws_clients):
            try: ws.send(msg)
            except: dead.add(ws)
        _ws_clients -= dead

def ws_broadcast_binary(data: bytes):
    with _ws_lock:
        for ws in list(_ws_clients):
            try: ws.send(data)
            except: _ws_clients.discard(ws)

def ws_handle(ws):
    _ws_clients.add(ws)
    ws.send(json.dumps({"type": "status", "status": "ready"}))
    try:
        for raw in ws:
            data = json.loads(raw)
            tp = data.get("type")
            if tp == "chat":
                handle_chat(data.get("text", ""))
            elif tp == "tts":
                # Frontend requests TTS for given text
                text = data.get("text", "")
                threading.Thread(target=lambda: handle_tts(text), daemon=True).start()
            elif tp == "command":
                cmd = data.get("cmd")
                if cmd == "ping":
                    ws.send(json.dumps({"type": "pong"}))
                elif cmd == "status":
                    s = "agent_online" if _agent else "model_display"
                    ws.send(json.dumps({"type": "system", "text": f"LAAP: {s}"}))
    except Exception as e:
        logger.debug(f"操作失败: {e}")
    finally:
        _ws_clients.discard(ws)

def handle_tts(text):
    """Generate TTS audio and broadcast to all clients"""
    try:
        audio_b64 = tts_to_base64(text)
        ws_broadcast({"type": "tts_audio", "data": audio_b64, "format": "mp3"})
    except Exception as e:
        ws_broadcast({"type": "error", "message": f"TTS failed: {e}"})

def handle_chat(text):
    ws_broadcast({"type": "user", "text": text})
    if _agent is None:
        ws_broadcast({"type": "response", "text": "Model display mode. Full mode: python -m laap.web.server"})
        return
    agent = _agent
    def run():
        try:
            from laap.ui.stream_handler import StreamHandler
            sh = StreamHandler(verbose=False, use_spinner=False)
            sh.on_token = lambda tok: ws_broadcast({"type":"token","text":tok})
            sh.on_tool_call = lambda n,a: ws_broadcast({"type":"tool_call","name":n})
            result = agent.chat(text, handler=sh)
            result = result or ""
            ws_broadcast({"type":"response","text":result})
            # Auto-TTS on response
            if result.strip():
                threading.Thread(target=lambda: handle_tts(result), daemon=True).start()
            # Emotion + vitals
            try:
                es = agent.lifeform.emotion_system
                name, intens, cn = es.get_dominant_emotion()
                ws_broadcast({"type":"emotion","name":name,"intensity":intens,"label":cn})
                v = agent.lifeform.physiology.vitals
                ws_broadcast({"type":"vitals", "energy":getattr(v,"energy",0.5), "focus":getattr(v,"focus",0.5), "mood":getattr(v,"mood",0.5)})
            except: pass
        except Exception as e:
            ws_broadcast({"type":"error","message":str(e)})
    threading.Thread(target=run, daemon=True).start()

def start(agent=None):
    global _agent
    _agent = agent
    httpd = HTTPServer(("0.0.0.0", HTTP_PORT), HTTPHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    import websockets.sync.server
    def sws():
        with websockets.sync.server.serve(ws_handle, "0.0.0.0", WS_PORT) as s: s.serve_forever()
    threading.Thread(target=sws, daemon=True).start()
    tag = f"Agent: {agent.config.name}" if agent else "Model Display"
    logger.info(f"\n  LAAP Web Server Started")
    logger.info(f"  HTTP: http://localhost:{HTTP_PORT}")
    logger.info(f"  WS:   ws://localhost:{WS_PORT}")
    logger.info(f"  TTS:  EdgeTTS (zh-CN-XiaoxiaoNeural)")
    logger.info(f"  Mode: {tag}\n")
if __name__ == "__main__":
    try:
        from laap.cli.config_manager import config_manager
        config_manager.apply_to_environment()
        from laap.llm.factory import LLMFactory
        from laap.agent.lifelike import LifelikeConfig
        from laap.lifeform import LifeformAgent
        factory = LLMFactory(default_provider="deepseek", default_model="deepseek-v4-flash")
        agent = LifeformAgent(config=LifelikeConfig(name="Ao", verbose=False), llm_factory=factory, show_banner=False)
        logger.info("  Agent ready")
        start(agent)
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n  Stopped")
    except Exception as e:
        logger.error(f"\n  Error: {e}")
        traceback.print_exc()
        input("Press Enter...")
