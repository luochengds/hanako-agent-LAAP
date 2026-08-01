"""Signal Platform — 加密消息收发 (signal-cli REST API)"""
from __future__ import annotations
import asyncio, json, logging, time, urllib.request
from typing import Any, Callable, Dict, List, Optional
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger("agent_core.platforms.signal")

class SignalAdapter(BasePlatformAdapter):
    """Signal适配器 — 通过signal-cli REST API收发加密消息"""

    DEFAULT_BASE = "http://127.0.0.1:8080"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self._api_base = config.get("api_base", self.DEFAULT_BASE)
        self._phone = config.get("phone", config.get("number", ""))
        self._account = config.get("account", self._phone)
        self._username = config.get("username", "")
        self._recipient = config.get("default_recipient", "")
        self._verify_ssl = config.get("verify_ssl", True)
        self._poll_interval = config.get("poll_interval", 2.0)
        self._task = None
        self._handler = None
        self._known_messages: set = set()
        self._stats["start_time"] = time.time()

    async def start(self):
        """启动Signal客户端轮询"""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Signal started (account={self._account}, api={self._api_base})")

    async def stop(self):
        """停止Signal客户端"""
        self._running = False
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        logger.info("Signal stopped")

    async def _poll_loop(self):
        """轮询signal-cli REST API获取新消息"""
        retry = 1
        while self._running:
            try:
                result = await self._api("GET", "/v1/receive/" + self._account, timeout=10)
                if isinstance(result, list):
                    for envelope in result:
                        await self._process_envelope(envelope)
                retry = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Signal poll: {e}")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)
            await asyncio.sleep(self._poll_interval)

    async def _process_envelope(self, envelope: Dict):
        """处理接收到的消息信封"""
        envelope_id = envelope.get("envelope", {}).get("timestamp", str(time.time()))
        if envelope_id in self._known_messages:
            return
        self._known_messages.add(envelope_id)
        if len(self._known_messages) > 10000:
            self._known_messages = set(list(self._known_messages)[-5000:])

        source = envelope.get("envelope", {}).get("source", "")
        source_name = envelope.get("envelope", {}).get("sourceName", source)
        data_msg = envelope.get("envelope", {}).get("dataMessage", {})
        text = data_msg.get("message", "") or ""
        attachments = data_msg.get("attachments", [])

        if not text and not attachments:
            return

        att_url = attachments[0] if attachments else ""
        event = MessageEvent(
            platform="signal",
            chat_id=source,
            user_id=source,
            text=text,
            user_name=source_name or source,
            message_id=str(data_msg.get("timestamp", "")),
            media_url=att_url,
            timestamp=time.time(),
        )
        if data_msg.get("groupInfo"):
            group = data_msg["groupInfo"]
            event.chat_id = f"group:{group.get('groupId', '')}"
            event.raw = {"group_name": group.get("name", "")}

        self._stats["messages_received"] += 1
        if self._handler:
            try:
                resp = self._handler(event)
                if resp and text:
                    await self.send_message(event.chat_id, str(resp)[:3000])
            except Exception as e:
                logger.error(f"Signal handler: {e}")

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SendResult:
        """发送加密消息"""
        try:
            recipient = chat_id or kwargs.get("recipient", self._recipient)
            if not recipient:
                return SendResult(success=False, error="no recipient")

            payload = {
                "message": text[:3000],
                "number": self._account,
                "recipients": [recipient],
            }
            if recipient.startswith("group:"):
                payload["recipients"] = [recipient.replace("group:", "")]
                payload["group"] = True

            result = await self._api("POST", "/v2/send", data=payload)
            self._stats["messages_sent"] += 1
            msg_id = ""
            if isinstance(result, dict):
                msg_id = str(result.get("timestamp", ""))
            return SendResult(success=True, message_id=msg_id)
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, **kwargs) -> SendResult:
        """发送带附件的消息"""
        try:
            recipient = chat_id or kwargs.get("recipient", self._recipient)
            if not recipient:
                return SendResult(success=False, error="no recipient")
            payload = {
                "number": self._account,
                "recipients": [recipient],
                "base64_attachments": [image_url] if image_url.startswith("data:") else [],
                "url_attachments": [image_url] if not image_url.startswith("data:") else [],
            }
            if recipient.startswith("group:"):
                payload["recipients"] = [recipient.replace("group:", "")]
                payload["group"] = True
            await self._api("POST", "/v2/send", data=payload)
            self._stats["messages_sent"] += 1
            return SendResult(success=True)
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str) -> bool:
        """发送正在输入指示"""
        try:
            recipient = chat_id or self._recipient
            if not recipient:
                return False
            payload = {
                "number": self._account,
                "recipients": [recipient],
                "typing": "typing",
            }
            await self._api("PUT", "/v1/typing/" + self._account, data=payload)
            return True
        except Exception:
            return False

    async def register_device(self, capture_code: str = "") -> Dict:
        """注册Signal设备"""
        payload = {"use_voice": False, "captcha": capture_code} if capture_code else {}
        try:
            result = await self._api("POST", "/v1/register/" + self._account, data=payload)
            return result if isinstance(result, dict) else {"status": "registered"}
        except Exception as e:
            return {"error": str(e)}

    async def verify_device(self, code: str) -> bool:
        """验证注册码"""
        try:
            await self._api("POST", "/v1/register/" + self._account + "/verify/" + code)
            return True
        except Exception:
            return False

    async def list_contacts(self) -> List[Dict]:
        """列出联系人"""
        try:
            result = await self._api("GET", "/v1/contacts/" + self._account)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    async def list_groups(self) -> List[Dict]:
        """列出群组"""
        try:
            result = await self._api("GET", "/v1/groups/" + self._account)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    async def _api(self, method: str, path: str, data: Any = None, timeout: int = 15) -> Any:
        """调用signal-cli REST API"""
        url = f"{self._api_base}{path}"
        if data is not None and method == "GET":
            method = "POST"
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if self._username:
            import base64
            auth = base64.b64encode(f"{self._username}:".encode()).decode()
            req.add_header("Authorization", f"Basic {auth}")

        loop = asyncio.get_event_loop()
        def _do_request():
            ctx = None
            if not self._verify_ssl:
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode()
                if not raw.strip():
                    return {}
                return json.loads(raw)
        return await loop.run_in_executor(None, _do_request)
