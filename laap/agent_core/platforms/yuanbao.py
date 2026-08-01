"""腾讯元宝平台 — 元宝群聊机器人（@提及响应）"""
from __future__ import annotations
import asyncio, json, logging, time, urllib.request, urllib.parse, hashlib, hmac, base64, threading
from typing import Any, Callable, Dict, List, Optional
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger("agent_core.platforms.yuanbao")

class YuanbaoAdapter(BasePlatformAdapter):
    """腾讯元宝适配器 — 群聊机器人消息收发及@提及响应"""

    API_BASE = "https://api.yuanbao.tencent.com/ai/v1"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", config.get("secret", ""))
        self.bot_id = config.get("bot_id", config.get("bot", ""))
        self.bot_name = config.get("bot_name", "LAAP机器人")
        self._webhook_port = config.get("webhook_port", 9500)
        self._webhook_path = config.get("webhook_path", "/webhook/yuanbao")
        self._webhook_secret = config.get("webhook_secret", "")
        self._at_only = config.get("at_only", True)
        self._auto_reply = config.get("auto_reply", True)
        self._group_ids = config.get("group_ids", [])
        self._server = None
        self._thread = None
        self._handler = None
        self._stats["start_time"] = time.time()

        if isinstance(self._group_ids, str):
            self._group_ids = [g.strip() for g in self._group_ids.split(",") if g.strip()]

    async def start(self):
        """启动元宝机器人"""
        self._running = True
        self._start_webhook()
        logger.info(f"Yuanbao started (bot={self.bot_id}, app={self.app_id})")

    def _start_webhook(self):
        """启动Webhook服务器接收消息"""
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler

            class YuanbaoHandler(BaseHTTPRequestHandler):
                adapter = None

                def do_POST(self):
                    """处理元宝回调消息"""
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length).decode("utf-8", errors="replace")
                    content_type = self.headers.get("Content-Type", "")
                    signature = self.headers.get("X-Yuanbao-Signature", "")
                    timestamp = self.headers.get("X-Yuanbao-Timestamp", "")
                    nonce = self.headers.get("X-Yuanbao-Nonce", "")

                    # 验证签名
                    if self.adapter and self.adapter._webhook_secret:
                        if not self.adapter._verify_webhook_sig(body, signature, timestamp, nonce):
                            self.send_response(403)
                            self.end_headers()
                            self.wfile.write(b'{"error":"invalid signature"}')
                            return

                    if self.adapter:
                        asyncio.run_coroutine_threadsafe(
                            self.adapter._process_webhook(body, content_type),
                            self.adapter._get_loop(),
                        )

                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"code":0,"message":"ok"}')

                def log_message(self, format, *args):
                    pass

            YuanbaoHandler.adapter = self
            self._server = HTTPServer(("0.0.0.0", self._webhook_port), YuanbaoHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info(f"Yuanbao webhook on :{self._webhook_port}{self._webhook_path}")
        except Exception as e:
            logger.error(f"Yuanbao webhook start failed: {e}")

    def _get_loop(self):
        """获取事件循环"""
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    def _verify_webhook_sig(self, body: str, signature: str, timestamp: str, nonce: str) -> bool:
        """验证Webhook签名"""
        if not signature or not self._webhook_secret:
            return True
        try:
            raw = f"{timestamp}{nonce}{body}"
            expected = base64.b64encode(
                hmac.new(
                    self._webhook_secret.encode("utf-8"),
                    raw.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode()
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False

    async def _process_webhook(self, body: str, content_type: str):
        """处理Webhook接收到的消息"""
        try:
            if "application/json" in content_type:
                data = json.loads(body)
            else:
                data = json.loads(body)

            event_type = data.get("event_type", data.get("type", ""))

            if event_type in ("message", "group_message", ""):
                await self._handle_message(data)
            elif event_type in ("event", "callback"):
                await self._handle_event(data)
        except Exception as e:
            logger.error(f"Process webhook: {e}")

    async def _handle_message(self, data: Dict):
        """处理接收到的消息"""
        msg_data = data.get("message", data.get("data", data))
        msg_type = msg_data.get("msg_type", msg_data.get("type", "text"))
        group_id = msg_data.get("group_id", msg_data.get("chat_id", msg_data.get("room_id", "")))
        sender_id = msg_data.get("sender_id", msg_data.get("user_id", msg_data.get("from", "")))
        sender_name = msg_data.get("sender_name", msg_data.get("nickname", msg_data.get("from_name", "")))
        content = msg_data.get("content", msg_data.get("text", msg_data.get("body", "")))
        msg_id = msg_data.get("msg_id", msg_data.get("message_id", str(time.time())))
        is_at = msg_data.get("is_at", data.get("is_mention", data.get("is_at", False)))
        at_list = msg_data.get("at_list", data.get("mention_list", []))

        if isinstance(content, dict):
            content = content.get("text", content.get("content", json.dumps(content, ensure_ascii=False)))

        if not content:
            return

        # 如果设置了at_only, 只处理@机器人的消息
        if self._at_only and not is_at:
            if self.bot_id and self.bot_id not in at_list:
                if self.bot_name and self.bot_name not in content:
                    return

        # 移除@提及文本
        clean_text = content
        if is_at:
            for mention in at_list:
                clean_text = clean_text.replace(f"@{mention}", "").strip()
            if self.bot_name:
                clean_text = clean_text.replace(f"@{self.bot_name}", "").strip()

        event = MessageEvent(
            platform="yuanbao",
            chat_id=group_id,
            user_id=sender_id,
            text=clean_text or content,
            msg_type=MessageType.TEXT,
            user_name=sender_name or sender_id,
            message_id=msg_id,
            timestamp=time.time(),
            raw=data,
        )

        self._stats["messages_received"] += 1

        if self._handler:
            try:
                resp = self._handler(event)
                if self._auto_reply and resp and clean_text:
                    await self.send_message(group_id, str(resp)[:3000])
            except Exception as e:
                logger.error(f"Yuanbao handler: {e}")
        else:
            logger.info(f"Yuanbao message from {sender_name}: {clean_text[:50]}")

    async def _handle_event(self, data: Dict):
        """处理事件回调"""
        event_type = data.get("event_type", data.get("type", ""))
        logger.debug(f"Yuanbao event: {event_type}")

    async def stop(self):
        """停止元宝机器人"""
        self._running = False
        if self._server:
            self._server.shutdown()
        logger.info("Yuanbao stopped")

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SendResult:
        """发送群聊消息"""
        try:
            group_id = chat_id or kwargs.get("group_id", "")
            if not group_id:
                return SendResult(success=False, error="no group_id")

            at_users = kwargs.get("at_users", [])
            at_all = kwargs.get("at_all", False)

            content = text[:3000]

            payload = {
                "app_id": self.app_id,
                "group_id": group_id,
                "msg_type": "text",
                "content": content,
                "bot_id": self.bot_id,
            }
            if at_users:
                payload["at_users"] = at_users
            if at_all:
                payload["at_all"] = True

            result = await self._api("/message/send", payload)
            self._stats["messages_sent"] += 1
            return SendResult(
                success=True,
                message_id=result.get("msg_id", result.get("message_id", "")),
            )
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def send_markdown(self, chat_id: str, text: str, **kwargs) -> SendResult:
        """发送Markdown格式消息"""
        try:
            group_id = chat_id or kwargs.get("group_id", "")
            if not group_id:
                return SendResult(success=False, error="no group_id")
            payload = {
                "app_id": self.app_id,
                "group_id": group_id,
                "msg_type": "markdown",
                "content": text[:5000],
                "bot_id": self.bot_id,
            }
            result = await self._api("/message/send", payload)
            return SendResult(success=True, message_id=result.get("msg_id", ""))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_card(self, chat_id: str, title: str, content: str, **kwargs) -> SendResult:
        """发送卡片消息"""
        try:
            group_id = chat_id or kwargs.get("group_id", "")
            if not group_id:
                return SendResult(success=False, error="no group_id")
            payload = {
                "app_id": self.app_id,
                "group_id": group_id,
                "msg_type": "card",
                "content": json.dumps({"title": title, "content": content[:2000]}, ensure_ascii=False),
                "bot_id": self.bot_id,
            }
            result = await self._api("/message/send", payload)
            return SendResult(success=True, message_id=result.get("msg_id", ""))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def reply_message(self, chat_id: str, text: str, reply_to_id: str, **kwargs) -> SendResult:
        """回复特定消息"""
        try:
            payload = {
                "app_id": self.app_id,
                "group_id": chat_id,
                "msg_type": "text",
                "content": text[:3000],
                "reply_to": reply_to_id,
                "bot_id": self.bot_id,
            }
            result = await self._api("/message/reply", payload)
            return SendResult(success=True, message_id=result.get("msg_id", ""))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def get_group_info(self, group_id: str) -> Optional[Dict]:
        """获取群信息"""
        try:
            result = await self._api("/group/info", {"app_id": self.app_id, "group_id": group_id})
            return result
        except Exception:
            return None

    async def get_group_members(self, group_id: str) -> List[Dict]:
        """获取群成员列表"""
        try:
            result = await self._api("/group/members", {
                "app_id": self.app_id,
                "group_id": group_id,
            })
            return result.get("members", result.get("data", []))
        except Exception:
            return []

    async def send_typing(self, chat_id: str) -> bool:
        """发送正在输入指示"""
        try:
            await self._api("/message/typing", {
                "app_id": self.app_id,
                "group_id": chat_id,
                "bot_id": self.bot_id,
            })
            return True
        except Exception:
            return False

    async def set_webhook(self, url: str) -> bool:
        """设置消息回调地址"""
        try:
            await self._api("/webhook/set", {
                "app_id": self.app_id,
                "webhook_url": url,
                "webhook_secret": self._webhook_secret,
            })
            logger.info(f"Yuanbao webhook set: {url}")
            return True
        except Exception as e:
            logger.error(f"Set webhook failed: {e}")
            return False

    async def _api(self, path: str, data: Dict = None) -> Dict:
        """调用元宝API"""
        url = f"{self.API_BASE}{path}"
        if data is None:
            data = {}
        if self.app_id and "app_id" not in data:
            data["app_id"] = self.app_id

        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")

        # 生成签名
        if self.app_secret:
            timestamp = str(int(time.time()))
            nonce = hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
            raw = f"{timestamp}{nonce}{body.decode('utf-8')}"
            signature = base64.b64encode(
                hmac.new(
                    self.app_secret.encode("utf-8"),
                    raw.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode()
            req.add_header("X-Yuanbao-Timestamp", timestamp)
            req.add_header("X-Yuanbao-Nonce", nonce)
            req.add_header("X-Yuanbao-Signature", signature)

        loop = asyncio.get_event_loop()
        def _do():
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        return await loop.run_in_executor(None, _do)
