"""
飞书 Card Kit 流式输出模块
=============================
基于 OpenClaw 的设计，使用飞书 Card Kit API 实现实时流式文字输出。

用法：
  1. 作为 Hermes FeishuAdapter 的增强（支持 draft streaming）
  2. 独立测试：python feishu_card_kit.py --test  "你好世界"

API 流程：
  POST /cardkit/v1/cards              → 创建卡片（streaming_mode=true）
  POST /im/v1/messages                → 发送卡片消息（interactive）
  PUT  /cardkit/v1/cards/{id}/elements/content/content  → 实时更新内容
  PATCH /cardkit/v1/cards/{id}/settings → 关闭 streaming 模式
"""

import asyncio
import json
import logging
import time
from typing import Optional

logger = logging.getLogger("feishu_card_kit")

# Token 缓存
_token_cache: dict[str, dict] = {}


def _resolve_api_base(domain: str = "feishu") -> str:
    if domain == "lark":
        return "https://open.larksuite.com/open-apis"
    if domain and domain.startswith("http"):
        return f"{domain.rstrip('/')}/open-apis"
    return "https://open.feishu.cn/open-apis"


async def _get_token(app_id: str, app_secret: str, domain: str = "feishu") -> str:
    """获取 tenant_access_token，带缓存"""
    import aiohttp
    cache_key = f"{domain}|{app_id}"
    cached = _token_cache.get(cache_key)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    api_base = _resolve_api_base(domain)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        ) as resp:
            data = await resp.json()
            if data.get("code") != 0 or "tenant_access_token" not in data:
                raise RuntimeError(f"Token error: {data.get('msg', 'unknown')}")
            token = data["tenant_access_token"]
            expire = data.get("expire", 7200)
            _token_cache[cache_key] = {
                "token": token,
                "expires_at": time.time() + expire,
            }
            return token


def _truncate_summary(text: str, max_len: int = 50) -> str:
    clean = text.replace("\n", " ").strip()
    return clean if len(clean) <= max_len else clean[:max_len - 3] + "..."


def _build_streaming_card(first_text: str = "⏳ Thinking...") -> dict:
    """构建流式卡片的 JSON 模板"""
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "summary": {"content": "[Generating...]"},
            "streaming_config": {
                "print_frequency_ms": {"default": 50},
                "print_step": {"default": 2},
            },
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": first_text,
                    "element_id": "content",
                }
            ],
        },
    }


class FeishuCardKitStream:
    """
    飞书 Card Kit 流式会话
    管理一个流式卡片的生命周期：创建 → 实时更新 → 关闭
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        domain: str = "feishu",
        client=None,  # lark-oapi Client 实例（可选）
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._client = client  # lark-oapi SDK client（优先使用）
        self._api_base = _resolve_api_base(domain)

        # 流式状态
        self.card_id: Optional[str] = None
        self.message_id: Optional[str] = None
        self._sequence: int = 0
        self._current_text: str = ""
        self._closed: bool = False
        self._update_queue: asyncio.Lock = asyncio.Lock()
        self._last_update_time: float = 0
        self._throttle_ms: float = 100  # 最大 10 次/秒
        self._pending_text: Optional[str] = None

    async def _get_token(self) -> str:
        return await _get_token(self._app_id, self._app_secret, self._domain)

    async def _http_request(self, method: str, path: str, json_data: dict = None) -> dict:
        """发 HTTP 请求到飞书 API（使用 aiohttp）"""
        import aiohttp
        token = await self._get_token()
        url = f"{self._api_base}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=json_data) as resp:
                data = await resp.json()
                if data.get("code", 0) != 0:
                    logger.warning(f"Card Kit API {method} {path}: {data.get('msg', '')}")
                return data

    async def start(self, receive_id: str, receive_id_type: str = "chat_id") -> None:
        """
        启动流式卡片：
        1. 创建卡片实体
        2. 发送卡片消息到聊天
        """
        if self.card_id:
            return

        card_json = _build_streaming_card()

        # 1) 创建卡片实体
        create_res = await self._http_request(
            "POST", "/cardkit/v1/cards",
            {"type": "card_json", "data": json.dumps(card_json)},
        )
        if create_res.get("code") != 0 or "card_id" not in create_res.get("data", {}):
            raise RuntimeError(f"创建卡片失败: {create_res.get('msg', 'unknown')}")

        self.card_id = create_res["data"]["card_id"]

        # 2) 发送卡片消息
        if self._client:
            # 使用 lark-oapi SDK
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("interactive")
                    .content(json.dumps({
                        "type": "card",
                        "data": {"card_id": self.card_id},
                    }))
                    .build()
                ).build()
            response = await asyncio.to_thread(self._client.im.v1.message.create, request)
            if response.code != 0:
                raise RuntimeError(f"发送卡片消息失败: {response.msg}")
            self.message_id = response.data.message_id
        else:
            # 使用 HTTP API
            send_res = await self._http_request(
                "POST", f"/im/v1/messages?receive_id_type={receive_id_type}",
                {
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps({
                        "type": "card",
                        "data": {"card_id": self.card_id},
                    }),
                },
            )
            if send_res.get("code") != 0:
                raise RuntimeError(f"发送卡片消息失败: {send_res.get('msg', 'unknown')}")
            self.message_id = send_res.get("data", {}).get("message_id", "")

        self._sequence = 1
        logger.info(f"CardKit 流式启动: card_id={self.card_id}, msg_id={self.message_id}")

    async def update(self, text: str) -> None:
        """
        更新卡片内容（带节流）
        在飞书客户端上实时显示文字变化
        """
        if not self.card_id or self._closed:
            return

        now = time.time()
        if (now - self._last_update_time) * 1000 < self._throttle_ms:
            self._pending_text = text
            return

        self._pending_text = None
        self._last_update_time = now
        self._current_text = text

        async with self._update_queue:
            if self._closed:
                return
            self._sequence += 1
            await self._http_request(
                "PUT",
                f"/cardkit/v1/cards/{self.card_id}/elements/content/content",
                {
                    "content": text,
                    "sequence": self._sequence,
                    "uuid": f"s_{self.card_id}_{self._sequence}",
                },
            )

    async def close(self, final_text: Optional[str] = None) -> None:
        """关闭流式卡片：处理最终文本 → 关闭 streaming 模式"""
        if not self.card_id or self._closed:
            return
        self._closed = True

        async with self._update_queue:
            text = final_text or self._pending_text or self._current_text

            # 如果有待发送的文本且与当前内容不同，先发送最终更新
            if text and text != self._current_text:
                self._sequence += 1
                await self._http_request(
                    "PUT",
                    f"/cardkit/v1/cards/{self.card_id}/elements/content/content",
                    {
                        "content": text,
                        "sequence": self._sequence,
                        "uuid": f"s_{self.card_id}_{self._sequence}",
                    },
                )

            # 关闭 streaming 模式
            self._sequence += 1
            await self._http_request(
                "PATCH",
                f"/cardkit/v1/cards/{self.card_id}/settings",
                {
                    "settings": json.dumps({
                        "config": {
                            "streaming_mode": False,
                            "summary": {"content": _truncate_summary(text)},
                        },
                    }),
                    "sequence": self._sequence,
                    "uuid": f"c_{self.card_id}_{self._sequence}",
                },
            )

        logger.info(f"CardKit 流式关闭: card_id={self.card_id}")

    @property
    def is_active(self) -> bool:
        return self.card_id is not None and not self._closed


# ── 独立测试 ────────────────────────────────────────────────────────

async def _test_streaming():
    """测试 Card Kit 流式输出"""
    import os

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_TEST_CHAT_ID", "")

    if not all([app_id, app_secret, chat_id]):
        logger.info("❌ 请设置环境变量: FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_TEST_CHAT_ID")
        return

    stream = FeishuCardKitStream(app_id, app_secret)

    logger.info(f"🚀 启动 Card Kit 流式 → 聊天 {chat_id}")
    await stream.start(chat_id)

    # 模拟流式输出
    test_texts = [
        "你好宝贝！",
        "你好宝贝！我是阿瑞斯，",
        "你好宝贝！我是阿瑞斯，这是通过飞书 Card Kit 流式输出的！",
        "你好宝贝！我是阿瑞斯，这是通过飞书 Card Kit 流式输出的！\n\n我可以在飞书里实时显示文字，就像打字一样。",
        "你好宝贝！我是阿瑞斯，这是通过飞书 Card Kit 流式输出的！\n\n我可以在飞书里实时显示文字，就像打字一样。\n\n**代码支持**：```python\nprint('hello')\n```\n| 功能 | 状态 |\n|------|------|\n| 流式 | ✅ |\n| 卡片 | ✅ |",
    ]

    for i, t in enumerate(test_texts):
        await stream.update(t)
        await asyncio.sleep(0.5)

    await stream.close(test_texts[-1])
    logger.info("✅ Card Kit 流式测试完成！")
if __name__ == "__main__":
    import sys
    if "--test" in sys.argv or "--demo" in sys.argv:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(_test_streaming())
    else:
        logger.info("Feishu Card Kit Streaming Module")
        logger.info("用法: python feishu_card_kit.py --test")