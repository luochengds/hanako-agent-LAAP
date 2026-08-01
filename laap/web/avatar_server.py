"""
LAAP Avatar Server - Web 3D虚拟角色服务器
HTTP(8081) + WebSocket(8766)
支持: VRM/GLB模型加载、WebSocket聊天、情感同步、表情驱动
"""

import logging
logger = logging.getLogger(__name__)

import json, os, time, threading, socketserver, queue, sys
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

HTTP_PORT = 8081
WS_PORT = 8766
STATIC_DIR = Path(__file__).parent / "static"

_agent = None
_ws_clients = set()
_ws_lock = threading.Lock()

# MIME types
MIME_MAP = {
    ".vrm": "application/octet-stream",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".pmx": "application/octet-stream",
    ".pmd": "application/octet-stream",
    ".vmd": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
}

class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()
    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        return MIME_MAP.get(ext) or super().guess_type(path)
    def log_message(self, *a): pass
    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

def _run_http():
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("0.0.0.0", HTTP_PORT), _Handler) as s:
            s.serve_forever()
    except Exception as e:
        logger.error(f"  HTTP error: {e}")
def _ws_broadcast(data):
    msg = json.dumps(data, ensure_ascii=False)
    with _ws_lock:
        for ws in list(_ws_clients):
            try: ws.send(msg)
            except: _ws_clients.discard(ws)

def _ws_handle(ws):
    _ws_clients.add(ws)
    ws.send(json.dumps({"type": "status", "status": "ready"}))
    try:
        for raw in ws:
            data = json.loads(raw)
            if data.get("type") == "chat":
                _handle_chat(data.get("text", ""))
            elif data.get("type") == "command":
                cmd = data.get("cmd")
                if cmd == "screenshot":
                    try:
                        from laap.tools.gui import gui_screenshot
                        r = json.loads(gui_screenshot())
                        ws.send(json.dumps({"type":"screenshot","data_base64":r.get("data_base64","")}))
                    except Exception as e:
                        ws.send(json.dumps({"type":"error","message":str(e)}))
    except Exception as e:
        logger.debug(f"操作失败: {e}")
    finally:
        _ws_clients.discard(ws)

def _handle_chat(text):
    global _agent
    _ws_broadcast({"type": "user", "text": text})
    if _agent is None:
        _ws_broadcast({"type": "response", "text": "LAAP Agent not started. Model display mode only."})
        return
    def _run():
        try:
            from laap.ui.stream_handler import StreamHandler
            sh = StreamHandler(verbose=False, use_spinner=False)
            def on_tok(tok):
                _ws_broadcast({"type": "token", "text": tok})
            def on_tc(name, args):
                _ws_broadcast({"type": "tool_call", "name": name})
            sh.on_token = on_tok
            sh.on_tool_call = on_tc
            result = _agent.chat(text, handler=sh)
            _ws_broadcast({"type": "response", "text": result or ""})
            try:
                es = _agent.lifeform.emotion_system
                name, intens, cn = es.get_dominant_emotion()
                _ws_broadcast({"type": "emotion", "name": name, "intensity": intens, "label": cn})
                v = _agent.lifeform.physiology.vitals
                _ws_broadcast({"type": "vitals",
                    "energy": getattr(v,"energy",0.5),
                    "focus": getattr(v,"focus",0.5),
                    "mood": getattr(v,"mood",0.5)})
            except: pass
        except Exception as e:
            _ws_broadcast({"type": "error", "message": str(e)})
    threading.Thread(target=_run, daemon=True).start()

def _run_ws():
    import websockets.sync.server
    with websockets.sync.server.serve(_ws_handle, "0.0.0.0", WS_PORT) as s:
        s.serve_forever()

def start_web_server(agent=None):
    global _agent
    _agent = agent
    t_http = threading.Thread(target=_run_http, daemon=True)
    t_ws = threading.Thread(target=_run_ws, daemon=True)
    t_http.start()
    t_ws.start()
    logger.info(f"  Web Avatar: http://localhost:{HTTP_PORT}")
    logger.info(f"  WebSocket: ws://localhost:{WS_PORT}")
    if agent:
        logger.info(f"  Agent: {agent.config.name}")
    else:
        logger.info(f"  Model display mode only")
if __name__ == "__main__":
    import traceback
    try:
        from laap.cli.config_manager import config_manager
        config_manager.apply_to_environment()
        from laap.llm.factory import LLMFactory
        from laap.agent.lifelike import LifelikeConfig
        from laap.lifeform import LifeformAgent
        factory = LLMFactory(default_provider="deepseek", default_model="deepseek-v4-flash")
        agent = LifeformAgent(config=LifelikeConfig(name="Ao", verbose=False), llm_factory=factory, show_banner=False)
        logger.info("  Agent ready")
        start_web_server(agent)
        logger.info(f"  Server at http://localhost:{HTTP_PORT}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n  Stopped")
    except Exception as e:
        logger.error(f"  Error: {e}")
        traceback.print_exc()
        input("Press Enter to exit...")
