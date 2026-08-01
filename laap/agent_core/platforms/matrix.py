"""Matrix Platform — 去中心化消息 (Matrix协议客户端)"""
from __future__ import annotations
import asyncio, json, logging, time, urllib.request, urllib.parse, hashlib, random, string
from typing import Any, Callable, Dict, List, Optional, Tuple
from laap.agent_core.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger("agent_core.platforms.matrix")

class MatrixAdapter(BasePlatformAdapter):
    """Matrix适配器 — 去中心化消息收发(通过Matrix CS API)"""

    HS_DEFAULT = "https://matrix-client.matrix.org"

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.homeserver = config.get("homeserver", config.get("hs", self.HS_DEFAULT))
        self._user_id = config.get("user_id", config.get("username", ""))
        self._password = config.get("password", "")
        self._access_token = config.get("access_token", "")
        self._device_id = config.get("device_id", f"LAAP-{int(time.time())}")
        self._sync_filter = config.get("sync_filter", "{}")
        self._poll_interval = config.get("poll_interval", 3.0)
        self._next_batch = ""
        self._task = None
        self._handler = None
        self._known_events: set = set()
        self._joined_rooms: Dict[str, str] = {}
        self._stats["start_time"] = time.time()

    async def start(self):
        """启动Matrix客户端"""
        self._running = True
        if not self._access_token:
            await self._login()
        await self._sync_joined_rooms()
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"Matrix started (user={self._user_id}, hs={self.homeserver})")

    async def stop(self):
        """停止Matrix客户端"""
        self._running = False
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        logger.info("Matrix stopped")

    async def _login(self) -> bool:
        """使用密码登录Matrix服务器"""
        try:
            result = await self._api("POST", "/_matrix/client/v3/login", {
                "type": "m.login.password",
                "user": self._user_id,
                "password": self._password,
                "device_id": self._device_id,
                "initial_device_display_name": "LAAP Agent",
            })
            self._access_token = result.get("access_token", "")
            self._user_id = result.get("user_id", self._user_id)
            self._device_id = result.get("device_id", self._device_id)
            self._token_expire = time.time() + 86400 * 30
            if self._access_token:
                logger.info(f"Matrix logged in as {self._user_id}")
                return True
            logger.error("Matrix login failed: no access_token")
            return False
        except Exception as e:
            logger.error(f"Matrix login failed: {e}")
            return False

    async def _sync_joined_rooms(self):
        """获取已加入的房间列表"""
        try:
            result = await self._api("GET", "/_matrix/client/v3/joined_rooms")
            rooms = result.get("joined_rooms", [])
            for room_id in rooms:
                self._joined_rooms[room_id] = ""
            logger.info(f"Matrix in {len(rooms)} rooms")
        except Exception as e:
            logger.error(f"Sync rooms: {e}")

    async def _sync_loop(self):
        """轮询Matrix同步API获取新消息"""
        retry = 1
        while self._running:
            try:
                params = {"timeout": 30000}
                if self._next_batch:
                    params["since"] = self._next_batch
                if self._sync_filter and self._sync_filter != "{}":
                    params["filter"] = self._sync_filter

                result = await self._api("GET", "/_matrix/client/v3/sync", params=params, timeout=45)
                self._next_batch = result.get("next_batch", self._next_batch)
                await self._process_sync(result)
                retry = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Matrix sync: {e}")
                await asyncio.sleep(retry)
                retry = min(retry * 2, 60)
            await asyncio.sleep(self._poll_interval)

    async def _process_sync(self, sync_data: Dict):
        """处理同步数据中的房间事件"""
        rooms = sync_data.get("rooms", {})
        join = rooms.get("join", {})
        for room_id, room_data in join.items():
            timeline = room_data.get("timeline", {})
            events = timeline.get("events", [])
            for event in events:
                await self._process_event(room_id, event)

    async def _process_event(self, room_id: str, event: Dict):
        """处理单个Matrix事件"""
        event_id = event.get("event_id", "")
        if not event_id or event_id in self._known_events:
            return
        self._known_events.add(event_id)
        if len(self._known_events) > 20000:
            self._known_events = set(list(self._known_events)[-10000:])

        etype = event.get("type", "")
        content = event.get("content", {})
        sender = event.get("sender", "")
        origin_ts = event.get("origin_server_ts", int(time.time() * 1000)) / 1000

        if self._user_id and sender == self._user_id:
            return

        text = ""
        msgtype = MessageType.TEXT
        media_url = ""

        if etype == "m.room.message":
            body = content.get("body", "")
            msgtype_str = content.get("msgtype", "m.text")
            if msgtype_str == "m.text" or msgtype_str == "m.notice":
                text = body
            elif msgtype_str == "m.image":
                text = f"[图片] {body}"
                media_url = content.get("url", "")
                msgtype = MessageType.IMAGE
            elif msgtype_str == "m.file":
                text = f"[文件] {body}"
                msgtype = MessageType.FILE
            elif msgtype_str == "m.audio":
                text = f"[音频] {body}"
                msgtype = MessageType.AUDIO
            elif msgtype_str == "m.emote":
                text = f"* {sender}: {body}"
                msgtype = MessageType.TEXT
            else:
                text = body

            if content.get("format") == "org.matrix.custom.html":
                msgtype = MessageType.MARKDOWN

            display_name = content.get("displayname", "") or sender

            event_obj = MessageEvent(
                platform="matrix",
                chat_id=room_id,
                user_id=sender,
                text=text,
                msg_type=msgtype,
                user_name=display_name,
                message_id=event_id,
                media_url=media_url,
                timestamp=origin_ts,
            )
            self._stats["messages_received"] += 1
            if self._handler:
                try:
                    resp = self._handler(event_obj)
                    if resp and text:
                        await self.send_message(room_id, str(resp)[:4000])
                except Exception as e:
                    logger.error(f"Matrix handler: {e}")

    async def send_message(self, chat_id: str, text: str, **kwargs) -> SendResult:
        """发送消息到房间"""
        try:
            room_id = chat_id
            if not room_id.startswith("!"):
                room_id = await self._resolve_room_alias(room_id)
                if not room_id:
                    return SendResult(success=False, error="room not found")

            txn_id = kwargs.get("txn_id", f"txn-{int(time.time()*1000)}-{random.randint(1000,9999)}")
            msgtype = kwargs.get("msgtype", "m.text")

            content = {
                "msgtype": msgtype,
                "body": text[:4000],
            }
            if kwargs.get("formatted_body"):
                content["format"] = "org.matrix.custom.html"
                content["formatted_body"] = kwargs["formatted_body"]
            elif msgtype == "m.text":
                content["format"] = "org.matrix.custom.html"
                content["formatted_body"] = text[:4000].replace("\n", "<br>")

            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/send/m.room.message/{urllib.parse.quote(txn_id, safe='')}"
            result = await self._api("PUT", path, content)
            self._stats["messages_sent"] += 1
            return SendResult(
                success=True,
                message_id=result.get("event_id", ""),
            )
        except Exception as e:
            self._stats["errors"] += 1
            return SendResult(success=False, error=str(e))

    async def send_text(self, chat_id: str, text: str) -> SendResult:
        """发送文本消息"""
        return await self.send_message(chat_id, text, msgtype="m.text")

    async def send_notice(self, chat_id: str, text: str) -> SendResult:
        """发送通知消息(静默提示)"""
        return await self.send_message(chat_id, text, msgtype="m.notice")

    async def send_image(self, chat_id: str, image_url: str, **kwargs) -> SendResult:
        """发送图片"""
        try:
            room_id = chat_id
            txn_id = f"txn-{int(time.time()*1000)}"
            content = {
                "msgtype": "m.image",
                "body": kwargs.get("filename", "image"),
                "url": image_url,
            }
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/send/m.room.message/{urllib.parse.quote(txn_id, safe='')}"
            await self._api("PUT", path, content)
            return SendResult(success=True)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_emote(self, chat_id: str, text: str) -> SendResult:
        """发送emote消息(行为)"""
        return await self.send_message(chat_id, text, msgtype="m.emote")

    async def send_typing(self, chat_id: str) -> bool:
        """发送正在输入指示"""
        try:
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(chat_id, safe='')}/typing/{urllib.parse.quote(self._user_id, safe='')}"
            await self._api("PUT", path, {"typing": True, "timeout": 15000})
            return True
        except Exception:
            return False

    async def join_room(self, room_id: str) -> bool:
        """加入房间"""
        try:
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/join"
            result = await self._api("POST", path, {})
            joined = result.get("room_id", room_id)
            self._joined_rooms[joined] = ""
            logger.info(f"Joined room: {joined}")
            return True
        except Exception as e:
            logger.error(f"Join room failed: {e}")
            return False

    async def leave_room(self, room_id: str) -> bool:
        """离开房间"""
        try:
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/leave"
            await self._api("POST", path, {})
            self._joined_rooms.pop(room_id, None)
            return True
        except Exception as e:
            logger.error(f"Leave room failed: {e}")
            return False

    async def create_room(self, name: str, topic: str = "", invite: List[str] = None) -> Optional[str]:
        """创建房间"""
        try:
            content = {"name": name, "topic": topic, "preset": "public_chat"}
            if invite:
                content["invite"] = invite
            result = await self._api("POST", "/_matrix/client/v3/createRoom", content)
            room_id = result.get("room_id", "")
            if room_id:
                self._joined_rooms[room_id] = name
            return room_id
        except Exception as e:
            logger.error(f"Create room failed: {e}")
            return None

    async def get_members(self, room_id: str) -> List[Dict]:
        """获取房间成员"""
        try:
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/members"
            result = await self._api("GET", path)
            return result.get("chunk", [])
        except Exception:
            return []

    async def _resolve_room_alias(self, alias: str) -> Optional[str]:
        """解析房间别名到ID"""
        if alias.startswith("!"):
            return alias
        try:
            clean = alias[1:] if alias.startswith("#") else alias
            path = f"/_matrix/client/v3/directory/room/{urllib.parse.quote(clean, safe='')}"
            result = await self._api("GET", path)
            return result.get("room_id", alias)
        except Exception:
            return alias

    async def upload_file(self, content_type: str, data: bytes) -> Optional[str]:
        """上传文件到Matrix内容仓库"""
        try:
            path = "/_matrix/media/v3/upload"
            req = urllib.request.Request(
                f"{self.homeserver}{path}",
                data=data,
                method="POST",
            )
            req.add_header("Authorization", f"Bearer {self._access_token}")
            req.add_header("Content-Type", content_type)
            loop = asyncio.get_event_loop()
            def _do():
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            result = await loop.run_in_executor(None, _do)
            return result.get("content_uri", "")
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return None

    async def _api(self, method: str, path: str, data: Any = None, params: Dict = None, timeout: int = 30) -> Any:
        """调用Matrix CS API"""
        url = f"{self.homeserver}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if self._access_token:
            req.add_header("Authorization", f"Bearer {self._access_token}")

        loop = asyncio.get_event_loop()
        def _do():
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                if not raw.strip():
                    return {}
                return json.loads(raw)
        return await loop.run_in_executor(None, _do)
