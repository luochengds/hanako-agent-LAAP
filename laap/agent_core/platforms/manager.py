"""PlatformManager — 管理所有平台（深度集成版）"""
from __future__ import annotations

import logging

import asyncio, json, logging, os
from typing import Any, Callable, Dict, List, Optional
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent
from laap.agent_core.platforms.telegram import TelegramAdapter
from laap.agent_core.platforms.discord import DiscordAdapter
from laap.agent_core.platforms.slack import SlackAdapter
from laap.agent_core.platforms.feishu import FeishuAdapter
from laap.agent_core.platforms.wechat import WeChatAdapter
from laap.agent_core.platforms.wecom import WeComAdapter
from laap.agent_core.platforms.dingtalk import DingTalkAdapter
from laap.agent_core.platforms.webhook import WebhookAdapter
from laap.agent_core.platforms.whatsapp import WhatsAppAdapter
from laap.agent_core.platforms.email import EmailAdapter
from laap.agent_core.platforms.signal import SignalAdapter
from laap.agent_core.platforms.sms import SmsAdapter
from laap.agent_core.platforms.matrix import MatrixAdapter
from laap.agent_core.platforms.yuanbao import YuanbaoAdapter

logger = logging.getLogger("agent_core.platforms.manager")

ALL_PLATFORMS = {
    "telegram": TelegramAdapter, "discord": DiscordAdapter, "slack": SlackAdapter,
    "feishu": FeishuAdapter, "wechat": WeChatAdapter, "wecom": WeComAdapter,
    "dingtalk": DingTalkAdapter, "webhook": WebhookAdapter,
    "whatsapp": WhatsAppAdapter, "email": EmailAdapter,
    "signal": SignalAdapter, "sms": SmsAdapter,
    "matrix": MatrixAdapter, "yuanbao": YuanbaoAdapter,
}

PLATFORM_DETAILS = {
    "telegram": {"name":"Telegram","region":"global","auth":"token"},
    "discord": {"name":"Discord","region":"global","auth":"token"},
    "slack": {"name":"Slack","region":"global","auth":"token"},
    "feishu": {"name":"飞书","region":"china","auth":"app_id+secret"},
    "wechat": {"name":"微信","region":"china","auth":"app_id+secret"},
    "wecom": {"name":"企业微信","region":"china","auth":"corp_id+secret"},
    "dingtalk": {"name":"钉钉","region":"china","auth":"app_key+secret"},
    "webhook": {"name":"Webhook","region":"global","auth":"optional"},
    "whatsapp": {"name":"WhatsApp","region":"global","auth":"token"},
    "email": {"name":"Email","region":"global","auth":"password"},
    "signal": {"name":"Signal","region":"global","auth":"phone+api_base"},
    "sms": {"name":"SMS","region":"global","auth":"provider+account"},
    "matrix": {"name":"Matrix","region":"global","auth":"homeserver+token"},
    "yuanbao": {"name":"腾讯元宝","region":"china","auth":"app_id+secret"},
}


class PlatformManager:
    def __init__(self, handler: Callable = None):
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._handler = handler
        self._config_path = os.path.expanduser("~/.laap/gateway.json")

    def register(self, adapter: BasePlatformAdapter):
        name = adapter.name
        self.adapters[name] = adapter
        adapter._handler = self._on_message

    def unregister(self, name: str):
        if name in self.adapters:
            del self.adapters[name]

    def get_adapter(self, name: str):
        return self.adapters.get(name)

    def _on_message(self, event: MessageEvent) -> str:
        if self._handler:
            return self._handler(event)
        return f"[{event.platform}] Echo: {event.text[:50]}"

    def configure(self, config: Dict):
        for name, cls in ALL_PLATFORMS.items():
            cfg = config.get(name, {})
            if cfg.get("enabled", False):
                required = {"token","app_id","corp_id","app_key","webhook","phone","access_key"}
                has_auth = any(k in cfg for k in required)
                if has_auth:
                    self.register(name, cls(cfg))
                    logger.info(f"Configured: {name}")

    def load_config(self):
        cfg = {}
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r') as f:
                    cfg = json.load(f)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        self.configure(cfg)

    def list_platforms(self) -> List[str]:
        return list(self.adapters.keys())

    def get(self, name: str) -> Optional[BasePlatformAdapter]:
        return self.adapters.get(name)

    async def start_all(self):
        for name, adapter in self.adapters.items():
            try:
                await adapter.start()
            except Exception as e:
                logger.error(f"Start {name} failed: {e}")

    async def stop_all(self):
        for name, adapter in self.adapters.items():
            try:
                await adapter.stop()
            except Exception as e:
                logger.error(f"Stop {name} failed: {e}")

    def get_stats(self) -> dict:
        total = {"platforms": len(self.adapters), "list": self.list_platforms()}
        for name, adapter in self.adapters.items():
            total[name] = adapter.get_stats()
        return total
