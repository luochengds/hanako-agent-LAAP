"""SMS Platform — 短信收发 (Twilio / 阿里云 双Provider)"""
from __future__ import annotations

import logging

import asyncio, json, logging, time, urllib.request, urllib.parse, hashlib, hmac, base64
from typing import Any, Callable, Dict, List, Optional
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger("agent_core.platforms.sms")

class SmsAdapter(BasePlatformAdapter):
    """SMS适配器 — 支持Twilio和阿里云双Provider短信收发"""

    PROVIDER_TWILIO = "twilio"
    PROVIDER_ALIYUN = "aliyun"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.provider = config.get("provider", self.PROVIDER_TWILIO)
        self._webhook_port = config.get("webhook_port", 9001)
        self._inbound_phone = config.get("inbound_phone", config.get("phone", ""))
        self._handler = None
        self._server = None
        self._thread = None
        self._stats["start_time"] = time.time()

        # Twilio config
        self._twilio_account_sid = config.get("account_sid", config.get("twilio_account_sid", ""))
        self._twilio_auth_token = config.get("auth_token", config.get("twilio_auth_token", ""))
        self._twilio_from = config.get("from_number", config.get("twilio_from", ""))

        # Aliyun config
        self._aliyun_access_key = config.get("access_key", config.get("aliyun_access_key", ""))
        self._aliyun_access_secret = config.get("access_secret", config.get("aliyun_access_secret", ""))
        self._aliyun_sign_name = config.get("sign_name", config.get("aliyun_sign_name", "LAAP"))
        self._aliyun_template_code = config.get("template_code", config.get("aliyun_template_code", ""))

    async def start(self):
        """启动SMS服务"""
        self._running = True
        if self.provider == self.PROVIDER_TWILIO:
            await self._start_twilio()
        else:
            await self._start_aliyun()
        logger.info(f"SMS started (provider={self.provider})")

    async def _start_twilio(self):
        """初始化Twilio提供商"""
        self._token = base64.b64encode(
            f"{self._twilio_account_sid}:{self._twilio_auth_token}".encode()
        ).decode()
        self._token_expire = time.time() + 86400

    async def _start_aliyun(self):
        """初始化阿里云SMS"""
        pass

    async def stop(self):
        """停止SMS服务"""
        self._running = False
        if self._server:
            self._server.shutdown()
        logger.info("SMS stopped")

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SendResult:
        """发送短信"""
        phone = chat_id or kwargs.get("phone", "")
        if not phone:
            return SendResult(success=False, error="no phone number")

        if self.provider == self.PROVIDER_TWILIO:
            return await self._send_twilio(phone, text, **kwargs)
        else:
            return await self._send_aliyun(phone, text, **kwargs)

    async def _send_twilio(self, to: str, text: str, **kwargs) -> SendResult:
        """通过Twilio API发送短信"""
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio_account_sid}/Messages.json"
            data = urllib.parse.urlencode({
                "To": to,
                "From": self._twilio_from,
                "Body": text[:1600],
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Authorization", f"Basic {self._token}")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

            loop = asyncio.get_event_loop()
            def _do():
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            result = await loop.run_in_executor(None, _do)
            self._stats["messages_sent"] += 1
            return SendResult(
                success=True,
                message_id=result.get("sid", ""),
            )
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def _send_aliyun(self, to: str, text: str, **kwargs) -> SendResult:
        """通过阿里云短信API发送"""
        try:
            params = {
                "PhoneNumbers": to,
                "SignName": self._aliyun_sign_name,
                "TemplateCode": self._aliyun_template_code,
                "TemplateParam": json.dumps({"code": text[:200]}, ensure_ascii=False),
                "AccessKeyId": self._aliyun_access_key,
                "Format": "JSON",
                "RegionId": "cn-hangzhou",
                "SignatureMethod": "HMAC-SHA1",
                "SignatureNonce": str(int(time.time() * 1000)),
                "SignatureVersion": "1.0",
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "Version": "2017-05-25",
                "Action": "SendSms",
            }
            sorted_keys = sorted(params.keys())
            canonical = "&".join(
                f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(params[k]), safe='')}"
                for k in sorted_keys
            )
            string_to_sign = f"POST&{urllib.parse.quote('/', safe='')}&{urllib.parse.quote(canonical, safe='')}"
            signature = base64.b64encode(
                hmac.new(
                    (self._aliyun_access_secret + "&").encode("utf-8"),
                    string_to_sign.encode("utf-8"),
                    hashlib.sha1,
                ).digest()
            ).decode()
            params["Signature"] = signature

            url = "https://dysmsapi.aliyuncs.com/?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, method="POST")

            loop = asyncio.get_event_loop()
            def _do():
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            result = await loop.run_in_executor(None, _do)
            if result.get("Code") == "OK":
                self._stats["messages_sent"] += 1
                return SendResult(success=True, message_id=result.get("BizId", ""))
            return SendResult(success=False, error=result.get("Message", "unknown"))
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def send_bulk(self, phones: List[str], text: str) -> List[SendResult]:
        """批量发送短信"""
        results = []
        for phone in phones:
            result = await self.send_message(phone, text)
            results.append(result)
            await asyncio.sleep(0.1)
        return results

    async def receive_sms(self, phone: str = "") -> List[Dict]:
        """通过Twilio拉取已收到的短信"""
        if self.provider != self.PROVIDER_TWILIO:
            return []
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio_account_sid}/Messages.json"
            params = {}
            if phone:
                params["To"] = phone
            query = urllib.parse.urlencode(params)
            if query:
                url += "?" + query
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Basic {self._token}")

            loop = asyncio.get_event_loop()
            def _do():
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            result = await loop.run_in_executor(None, _do)
            messages = result.get("messages", [])
            for msg in messages:
                if self._handler:
                    direction = msg.get("direction", "")
                    if direction == "inbound":
                        event = MessageEvent(
                            platform="sms",
                            chat_id=msg.get("from", ""),
                            user_id=msg.get("from", ""),
                            text=msg.get("body", ""),
                            user_name=msg.get("from", ""),
                            message_id=msg.get("sid", ""),
                            timestamp=time.mktime(
                                time.strptime(msg.get("date_sent", ""), "%a, %d %b %Y %H:%M:%S %z")[:9]
                            ) if msg.get("date_sent") else time.time(),
                        )
                        try:
                            self._handler(event)
                        except Exception as e:
                            logger.debug(f"操作失败: {e}")
            return messages
        except Exception as e:
            logger.error(f"SMS receive: {e}")
            return []

    async def send_typing(self, chat_id: str) -> bool:
        return True

    def validate_twilio_request(self, url: str, params: Dict, signature: str) -> bool:
        """验证Twilio Webhook请求签名"""
        if not self._twilio_auth_token:
            return False
        expected = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        digest = hmac.new(
            self._twilio_auth_token.encode(),
            expected.encode(),
            hashlib.sha256,
        ).hexdigest()
        import base64
        computed = base64.b64encode(
            hmac.new(
                self._twilio_auth_token.encode(),
                expected.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        return computed == signature
