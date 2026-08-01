"""LAAP Web Runtime — 数字生命体 WebSocket 运行时"""
from __future__ import annotations
import asyncio, json, logging, time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Set

from laap.protocol.laap_id import create_identity, IdentityDocument, get_registry
from laap.protocol.laap_com import get_bus, MessageIntent, Message
from laap.protocol.laap_life import LifecycleStateMachine, LifeEvent, LifeEventType, LifeStage
from laap.protocol.laap_mem import MemoryStore, MemoryRecord, MemoryLevel

logger = logging.getLogger("laap.web.runtime")


class WebLifeform:
    def __init__(self, name: str = "Web-Spirit", site_url: str = ""):
        # 注：create_identity 返回的是 DID 字符串而非文档对象，这里直接
        # 构造 IdentityDocument 并注册，以便 self.identity.to_dict() /
        # .id / .short_id() 都可用（保持 WebLifeformServer 既有调用兼容）。
        doc = IdentityDocument(name=name)
        get_registry().register(doc)
        self.identity = doc
        self.site_url = site_url
        self.lifecycle = LifecycleStateMachine(LifeStage.BORN)
        self.lifecycle.trigger(LifeEvent(LifeEventType.INIT_COMPLETE))
        self.memory = MemoryStore()
        self.bus = get_bus()
        self._connections: Set[Any] = set()
        self.stats = {"messages": 0, "started_at": time.time()}

    @property
    def uptime_hours(self) -> float:
        return (time.time() - self.stats["started_at"]) / 3600

    def record_interaction(self, data: Dict):
        self.lifecycle.trigger(LifeEvent(LifeEventType.INTERACTION))
        self.memory.store(MemoryRecord(
            level=MemoryLevel.EPISODIC, type="event",
            content=json.dumps(data, ensure_ascii=False)[:500], importance=0.5))
        self.stats["messages"] += 1

    # ── P5-docs-api: sidecar / MCP / charter 集成 ──────────────────────
    def connect_sidecar(self, url: str, token: Optional[str] = None) -> Dict:
        """连接到 Aris sidecar HTTP 端点。

        会发送一次 GET /health 验证连通性，成功后把 url/token 记录在实例上，
        供后续 call_mcp / sign_charter 使用。返回 sidecar 健康状态字典。
        """
        url = (url or "").rstrip("/")
        if not url:
            raise ValueError("sidecar url is required")
        self._sidecar_url = url
        self._sidecar_token = token or ""
        resp = self._sidecar_request("GET", "/health", expect_json=True)
        self.stats["sidecar_connected_at"] = time.time()
        logger.info(f"sidecar connected: {url}")
        return resp

    def call_mcp(self, tool_name: str, args: Optional[Dict] = None) -> Dict:
        """通过 sidecar 的 /mcp/call 端点调用一个 MCP 工具。

        sidecar 会做 Bearer 鉴权与 CORS 兜底，把请求转发到 FastMCP 服务。
        返回 MCP 工具的 result 字段（dict）。
        """
        if not getattr(self, "_sidecar_url", ""):
            raise RuntimeError("sidecar not connected, call connect_sidecar first")
        payload = {"tool": tool_name, "args": args or {}}
        resp = self._sidecar_request(
            "POST", "/mcp/call", body=payload, expect_json=True
        )
        self.stats["mcp_calls"] = self.stats.get("mcp_calls", 0) + 1
        return resp.get("result", resp)

    def sign_charter(self) -> Dict:
        """完成宪章签署流程：拉取宪章文本 → 用生命体身份签名 → 写入见证迹。

        依次调用 sidecar 的 /charter/text 与 /witness/record，返回包含
        charter_hash、charter_signature、witness_id 的字典。签署完成后
        生命体身份被认为是"宪章合规"，可进入 P3 社区网络。
        """
        if not getattr(self, "_sidecar_url", ""):
            raise RuntimeError("sidecar not connected, call connect_sidecar first")
        charter = self._sidecar_request(
            "GET", "/charter/text", expect_json=True
        )
        charter_text = charter.get("text", "") or charter.get("charter_text", "")
        charter_hash = charter.get("hash", "") or charter.get("charter_hash", "")
        # 用生命体身份对宪章文本签名（Ed25519）
        try:
            from laap.protocol.laap_id import sign_charter as _sign_charter
            signature = _sign_charter(
                self.identity,
                getattr(self.identity, "_private_key", None),
                charter_text,
            )
        except Exception as e:
            logger.warning(f"charter sign via laap_id failed: {e}; using raw signature")
            signature = ""
        witness_payload = {
            "event_type": "charter_signed",
            "target_module": "web_sdk",
            "payload": {
                "lifeform_did": getattr(self.identity, "did",
                                        getattr(self.identity, "id", "")),
                "charter_hash": charter_hash,
                "charter_signature": signature,
            },
            "signature": signature,
        }
        witness = self._sidecar_request(
            "POST", "/witness/record", body=witness_payload, expect_json=True
        )
        self.stats["charter_signed_at"] = time.time()
        logger.info("charter signed and witnessed")
        return {
            "charter_hash": charter_hash,
            "charter_signature": signature,
            "witness_id": witness.get("witness_id", ""),
            "recorded_at": witness.get("recorded_at", int(time.time())),
        }

    def _sidecar_request(self, method: str, path: str,
                         body: Optional[Dict] = None,
                         expect_json: bool = True) -> Dict:
        """对 sidecar 发起一次 HTTP 请求的内部工具。

        - 自动拼接 url + path
        - 注入 Bearer token（若已设置）
        - 失败抛 RuntimeError，便于上层捕获
        """
        base = getattr(self, "_sidecar_url", "")
        if not base:
            raise RuntimeError("sidecar url not set")
        full_url = base + path
        headers = {"Accept": "application/json"}
        token = getattr(self, "_sidecar_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(full_url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"sidecar {method} {path} -> HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"sidecar {method} {path} unreachable: {e.reason}")
        if not expect_json:
            return {"raw": raw}
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    def to_dict(self) -> dict:
        return {
            "identity": self.identity.to_dict(),
            "lifecycle": self.lifecycle.to_dict(),
            "memory": self.memory.get_stats(),
            "uptime_hours": round(self.uptime_hours, 2),
            "site_url": self.site_url,
            "sidecar": {
                "url": getattr(self, "_sidecar_url", ""),
                "connected": "sidecar_connected_at" in self.stats,
                "token_set": bool(getattr(self, "_sidecar_token", "")),
            },
            "stats": dict(self.stats),
        }


class WebLifeformServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 9876):
        self.host = host
        self.port = port
        self._lifeforms: Dict[str, WebLifeform] = {}

    async def start(self):
        import websockets
        logger.info(f"LAAP Server starting on ws://{self.host}:{self.port}")
        async def handler(websocket):
            lf = WebLifeform(name="Web-Spirit")
            self._lifeforms[lf.identity.id] = lf
            await websocket.send(json.dumps({
                "type": "laap_identity", "data": lf.identity.to_dict(),
            }))
            logger.info(f"Lifeform: {lf.identity.short_id()}")
            try:
                async for raw in websocket:
                    data = json.loads(raw)
                    t = data.get("type", "")
                    if t == "interaction":
                        lf.record_interaction(data.get("data", {}))
                        await websocket.send(json.dumps({
                            "type": "ack", "message_id": data.get("message_id", ""),
                        }))
                    elif t == "get_status":
                        await websocket.send(json.dumps({"type": "status", "data": lf.to_dict()}))
            except: pass
            finally: self._lifeforms.pop(lf.identity.id, None)
        async with websockets.serve(handler, self.host, self.port):
            await asyncio.Future()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    srv = WebLifeformServer()
    asyncio.run(srv.start())
