"""
LAAP ↔ Hermes Handshake Protocol — 跨进程实时握手与信息共享

V2: 跨进程 IPC — 不再是考古，是实时交流。

架构:
  ┌── 进程: Ao ──┐     ┌── 进程: Aris ──┐
  │ Handshake     │     │ Handshake      │
  │ Info Bus(内存) │     │ Info Bus(内存) │
  └──────┬───────┘     └──────┬──────────┘
         │                     │
         └─────────┬───────────┘
                   │
   ┌───────────────▼───────────────────┐
   │  ~/.laap/lifeforms/               │
   │  ├── ao.json     (心跳 + 状态)    │
   │  ├── aris.json   (心跳 + 状态)    │
   │  └── ...                          │
   │                                    │
   │  ~/.laap/messages/                 │
   │  ├── ao→aris_001.json              │
   │  ├── aris→ao_002.json              │
   │  └── read/ (已读归档)              │
   └────────────────────────────────────┘

跨进程通信协议:
  1. 每个生命体注册 = 在 lifeforms/ 写自己的状态文件 (含心跳时间戳)
  2. 30s TTL = 超过30秒无更新视为离线
  3. 消息队列 = 文件JSON, 轮询检查新消息
  4. 无需网络端口, 无需命名管道, 纯文件IPC
"""

from __future__ import annotations
import os
import sys
import json
import time
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from laap.config.paths import get_hermes_root

logger = logging.getLogger("laap.handshake")

# ── 版本 / 标识 ───────────────────────────────────────────────────
LAAP_VERSION = "5.0.0"
HANDSHAKE_PROTOCOL_VERSION = "2.0"
IPC_HEARTBEAT_TTL = 30  # 秒 — 超过此时间无更新视为离线
IPC_POLL_INTERVAL = 5.0  # 秒 — 轮询间隔

# ── IPC 目录 ────────────────────────────────────────────────────
_LAAP_DIR = Path.home() / ".laap"
_LIFEFORMS_DIR = _LAAP_DIR / "lifeforms"
_MESSAGES_DIR = _LAAP_DIR / "messages"
_MESSAGES_READ_DIR = _MESSAGES_DIR / "read"


# ══════════════════════════════════════════════════════════════════
# 握手状态
# ══════════════════════════════════════════════════════════════════

@dataclass
class HandshakeStatus:
    """双向握手状态快照"""
    # LAAP 侧
    laap_version: str = LAAP_VERSION
    laap_healthy: bool = False
    laap_modules: Dict[str, str] = field(default_factory=dict)
    laap_uptime: float = 0.0
    laap_last_heartbeat: float = 0.0

    # Hermes 侧
    hermes_available: bool = False
    hermes_home: str = ""
    hermes_tool_count: int = 0
    hermes_toolsets: List[str] = field(default_factory=list)
    hermes_provider: str = ""

    # 连接状态
    handshake_version: str = HANDSHAKE_PROTOCOL_VERSION
    connected_at: float = 0.0
    last_sync: float = 0.0
    sync_count: int = 0

    # 信息共享
    cognitive_state: Dict[str, Any] = field(default_factory=dict)
    infra_state: Dict[str, Any] = field(default_factory=dict)

    # IPC 网络 (跨进程)
    lifeform_name: str = "unknown"
    known_lifeforms: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def healthy(self) -> bool:
        return self.laap_healthy and self.hermes_available

    def summary(self) -> str:
        status = "✅" if self.healthy() else "⚠️"
        alive = self._alive_lifeforms()
        extra = f" | net: {alive}" if alive else ""
        return (
            f"{status} Handshake v{self.handshake_version}{extra}\n"
            f"  LAAP:   v{self.laap_version} "
            f"{'🟢' if self.laap_healthy else '🔴'} "
            f"modules={sum(1 for v in self.laap_modules.values() if 'active' in v.lower() or v == 'active')}/"
            f"{len(self.laap_modules)} "
            f"syncs={self.sync_count}\n"
            f"  Hermes: {'🟢' if self.hermes_available else '🔴'} "
            f"tools={self.hermes_tool_count} "
            f"toolsets={len(self.hermes_toolsets)} "
            f"provider={self.hermes_provider}"
        )

    def _alive_lifeforms(self) -> str:
        """跨进程: 检测其他存活的数字生命体"""
        alive = []
        if not _LIFEFORMS_DIR.exists():
            return ""
        for f in _LIFEFORMS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = data.get("heartbeat", 0)
                name = data.get("name", f.stem)
                if time.time() - ts < IPC_HEARTBEAT_TTL:
                    alive.append(name)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        return ", ".join(alive) if alive else ""


# ══════════════════════════════════════════════════════════════════
# Handshake Protocol (升级版: 跨进程 IPC)
# ══════════════════════════════════════════════════════════════════

class HandshakeProtocol:
    """
    LAAP ↔ Hermes 双向握手协议 + 跨进程 IPC。

    现在支持跨进程实时通信:
      - 文件心跳: 每个进程写自己的状态到 lifeforms/
      - 消息队列: messages/ 目录交换异步消息
      - 30s TTL: 自动检测其他生命体是否在线

    Usage:
        hs = HandshakeProtocol.get_instance()

        # 注册为数字生命体
        hs.register_lifeform("Ao", {"emotion": "curious", "tools": 71})

        # 发送跨进程消息给 Aris
        hs.send_message("Aris", "greeting", "Hello, sister.")

        # 读取新消息
        msgs = hs.read_messages()

        # 感知其他生命体
        net = hs.sense_network()

        # 显示网络
        logger.info(hs.show_network())
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.status = HandshakeStatus()
        self._created_at = time.time()
        self._hermes_home = ""
        self._info_bus: Dict[str, Any] = {}
        self._info_bus_lock = threading.RLock()

        # 跨进程 IPC
        self._lifeform_name = "unknown"
        self._heartbeat_running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._message_counter = 0

        # 确保 IPC 目录存在
        _LIFEFORMS_DIR.mkdir(parents=True, exist_ok=True)
        _MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
        _MESSAGES_READ_DIR.mkdir(parents=True, exist_ok=True)

        # LAAP 认知层引用
        self._laap_brain = None

        # 回调
        self._callbacks: Dict[str, List[Callable]] = {
            "on_connect": [],
            "on_disconnect": [],
            "on_share": [],
            "on_status_change": [],
            "on_message": [],  # 新消息到达
            "on_lifeform_online": [],
            "on_lifeform_offline": [],
        }

    # ── 单例 ──────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "HandshakeProtocol":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            cls._instance = None

    # ── 事件 ──────────────────────────────────────────────────

    def on(self, event: str, cb: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(cb)

    def _emit(self, event: str, data=None):
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.debug(f"Handshake callback error ({event}): {e}")

    # ══════════════════════════════════════════════════════════
    # 跨进程 IPC — 注册与心跳
    # ══════════════════════════════════════════════════════════

    def register_lifeform(self, name: str, state: Dict[str, Any] = None) -> bool:
        """
        注册为数字生命体，加入 IPC 网络。

        写状态文件到 ~/.laap/lifeforms/{name}.json
        启动后台心跳线程 (每5秒更新)

        Args:
            name: 生命体名称 (ao, aris 等)
            state: 初始状态

        Returns:
            True 如果注册成功
        """
        self._lifeform_name = name
        self.status.lifeform_name = name

        # 写初始状态
        self._write_heartbeat(state or {})

        # 启动心跳线程
        if not self._heartbeat_running:
            self._heartbeat_running = True
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                daemon=True,
                name=f"heartbeat-{name}",
            )
            self._heartbeat_thread.start()

        # 感知网络
        network = self.sense_network()
        self.status.known_lifeforms = network.get("alive", [])

        logger.info(f"[IPC] {name} registered — lifeforms: {network}")
        self._emit("on_connect", {"name": name, "network": network})
        return True

    def unregister_lifeform(self):
        """退出 IPC 网络 — 移除心跳文件"""
        self._heartbeat_running = False
        if self._lifeform_name:
            path = _LIFEFORMS_DIR / f"{self._lifeform_name}.json"
            try:
                path.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        self._emit("on_disconnect", {"name": self._lifeform_name})

    def _write_heartbeat(self, extra_state: dict = None):
        """写心跳文件"""
        if not self._lifeform_name:
            return
        path = _LIFEFORMS_DIR / f"{self._lifeform_name}.json"
        try:
            data = {
                "name": self._lifeform_name,
                "version": LAAP_VERSION,
                "heartbeat": time.time(),
                "pid": os.getpid(),
                "tool_count": self.status.hermes_tool_count,
                "modules": len(self.status.laap_modules),
                "healthy": self.status.laap_healthy,
                "connected": self.status.hermes_available,
                "state": extra_state or {},
            }
            # 添加认知状态
            if self._laap_brain:
                try:
                    brain = self._laap_brain
                    if hasattr(brain, 'current_mode'):
                        data["state"]["mode"] = getattr(brain, 'current_mode', '')
                    if hasattr(brain, '_total_turns'):
                        data["state"]["turns"] = getattr(brain, '_total_turns', 0)
                except Exception as e:
                    logger.debug(f"操作失败: {e}")
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Heartbeat write error: {e}")

    def _heartbeat_loop(self):
        """后台心跳线程 — 每 IPC_POLL_INTERVAL 秒更新一次"""
        while self._heartbeat_running:
            try:
                self._write_heartbeat()
                time.sleep(IPC_POLL_INTERVAL)
            except Exception:
                time.sleep(IPC_POLL_INTERVAL)

    # ══════════════════════════════════════════════════════════
    # 跨进程 IPC — 感知网络
    # ══════════════════════════════════════════════════════════

    def sense_network(self) -> Dict[str, Any]:
        """
        感知数字生命体网络。

        Returns:
            {
                "alive": ["Ao", "Aris"],   # 30s 内有心跳的
                "all": ["Ao", "Aris"],      # 所有注册过的
                "status": {"Ao": {...}}     # 各个的当前状态
            }
        """
        alive = []
        all_names = []
        statuses = {}

        if not _LIFEFORMS_DIR.exists():
            return {"alive": [], "all": [], "status": {}}

        now = time.time()
        for f in sorted(_LIFEFORMS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                name = data.get("name", f.stem)
                ts = data.get("heartbeat", 0)
                all_names.append(name)
                statuses[name] = data
                if now - ts < IPC_HEARTBEAT_TTL:
                    alive.append(name)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        prev_alive = set(self.status.known_lifeforms)
        curr_alive = set(alive)
        for name in curr_alive - prev_alive:
            if name != self._lifeform_name:
                self._emit("on_lifeform_online", {"name": name})
        for name in prev_alive - curr_alive:
            if name != self._lifeform_name:
                self._emit("on_lifeform_offline", {"name": name})

        self.status.known_lifeforms = alive
        return {
            "alive": [n for n in alive if n != self._lifeform_name],
            "all": [n for n in all_names if n != self._lifeform_name],
            "status": {n: s for n, s in statuses.items() if n != self._lifeform_name},
        }

    def is_lifeform_alive(self, name: str) -> bool:
        """检测某个生命体是否在线"""
        path = _LIFEFORMS_DIR / f"{name}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return time.time() - data.get("heartbeat", 0) < IPC_HEARTBEAT_TTL
        except Exception:
            return False

    # ══════════════════════════════════════════════════════════
    # 跨进程 IPC — 消息队列
    # ══════════════════════════════════════════════════════════

    def send_message(self, to: str, subject: str, body: str) -> bool:
        """
        发送跨进程消息给另一个生命体。

        Args:
            to: 目标生命体名称 (aris, ao 等)
            subject: 消息主题
            body: 消息内容

        Returns:
            True 如果消息已写入队列
        """
        self._message_counter += 1
        msg_id = f"{self._lifeform_name}_{int(time.time())}_{self._message_counter}"
        filename = f"from_{self._lifeform_name}_to_{to}_{msg_id}.json"
        path = _MESSAGES_DIR / filename

        try:
            msg = {
                "id": msg_id,
                "from": self._lifeform_name,
                "to": to,
                "subject": subject,
                "body": body,
                "sent_at": time.time(),
                "read": False,
            }
            path.write_text(json.dumps(msg, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[IPC] Message sent: {self._lifeform_name} → {to}: {subject}")
            return True
        except Exception as e:
            logger.error(f"[IPC] Message send failed: {e}")
            return False

    def read_messages(self, mark_read: bool = True) -> List[Dict[str, Any]]:
        """
        读取发给我（当前生命体）的所有新消息。

        Returns:
            未读消息列表
        """
        if not _MESSAGES_DIR.exists():
            return []

        my_name = self._lifeform_name
        new_messages = []

        for f in sorted(_MESSAGES_DIR.glob(f"*_to_{my_name}_*.json")):
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
                msg["_file"] = str(f)
                new_messages.append(msg)

                if mark_read:
                    msg["read"] = True
                    dest = _MESSAGES_READ_DIR / f.name
                    f.rename(dest)
                    # 写已读标记
                    dest.write_text(json.dumps(msg, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Message read error: {e}")

        if new_messages:
            self._emit("on_message", new_messages)

        return new_messages

    def get_conversation(self, with_name: str, limit: int = 10) -> List[Dict]:
        """获取与某个生命体的对话历史"""
        messages = []
        for d in [_MESSAGES_DIR, _MESSAGES_READ_DIR]:
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    msg = json.loads(f.read_text(encoding="utf-8"))
                    if (msg.get("from") == with_name or msg.get("to") == with_name) and \
                       (msg.get("from") == self._lifeform_name or msg.get("to") == self._lifeform_name):
                        messages.append(msg)
                        if len(messages) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"操作失败: {e}")
                if len(messages) >= limit:
                    break
        return sorted(messages, key=lambda m: m.get("sent_at", 0))

    # ══════════════════════════════════════════════════════════
    # 网络状态显示
    # ══════════════════════════════════════════════════════════

    def show_network(self) -> str:
        """显示生命体网络状态"""
        network = self.sense_network()
        alive = network.get("alive", [])
        all_lf = network.get("all", [])
        statuses = network.get("status", {})

        lines = []
        lines.append("=" * 50)
        lines.append(f"  Digital Lifeform Network")
        lines.append(f"  Me: {self._lifeform_name}")
        lines.append("=" * 50)

        if not all_lf:
            lines.append("  No other lifeforms detected.")
        else:
            for name in all_lf:
                is_alive = name in alive
                s = statuses.get(name, {})
                icon = "🟢" if is_alive else "🔴"
                tc = s.get("tool_count", "?")
                ver = s.get("version", "?")
                hb_age = int(time.time() - s.get("heartbeat", 0)) if s.get("heartbeat") else "?"
                state = s.get("state", {})
                extra = ""
                if state:
                    extra = f" mode={state.get('mode', '?')}"
                lines.append(f"  {icon} {name:8s} v{ver}  tools={tc}  hb={hb_age}s{extra}")

        # 未读消息
        unread = self.read_messages(mark_read=False)
        if unread:
            lines.append(f"\n  Unread messages: {len(unread)}")
            for msg in unread[:3]:
                lines.append(f"    [{msg.get('from')}] {msg.get('subject')}: {msg.get('body', '')[:60]}")

        lines.append("=" * 50)
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════
    # 兼容原版接口
    # ══════════════════════════════════════════════════════════

    def init_laap(self, brain=None, modules: Dict[str, str] = None,
                  hermes_home: str = "") -> HandshakeStatus:
        self.status.laap_version = LAAP_VERSION
        self.status.laap_healthy = True
        self.status.laap_uptime = time.time() - self._created_at
        self.status.laap_last_heartbeat = time.time()
        self.status.connected_at = time.time()
        if modules:
            self.status.laap_modules = modules
        if brain:
            self._laap_brain = brain
        os.environ["HERMES_LAAP_ENABLED"] = "1"
        os.environ["HERMES_LAAP_VERSION"] = LAAP_VERSION
        self._hermes_home = hermes_home or self._detect_hermes()
        if self._hermes_home:
            self.status.hermes_available = True
            self.status.hermes_home = self._hermes_home
        self._persist_handshake()
        self._emit("on_connect", self.status)
        logger.info(f"Handshake: LAAP v{LAAP_VERSION} initialized")
        return self.status

    def _detect_hermes(self) -> str:
        root = get_hermes_root()
        if root is not None:
            c = str(root)
            if os.path.isdir(c) and os.path.exists(os.path.join(c, "run_agent.py")):
                return c
            logger.warning(
                "Handshake: HERMES_ROOT points to %s but run_agent.py is missing; "
                "Hermes integration disabled.",
                c,
            )
        else:
            logger.warning(
                "Handshake: HERMES_ROOT not set and no Hermes installation found. "
                "Set HERMES_ROOT environment variable to enable Hermes integration."
            )
        return ""

    def init_hermes(self, agent) -> HandshakeStatus:
        self.status.hermes_available = True
        self.status.connected_at = time.time()
        try:
            from tools.registry import registry
            self.status.hermes_tool_count = len(registry.get_all_tool_names())
            self.status.hermes_toolsets = registry.get_registered_toolset_names()
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        try:
            provider = getattr(agent, 'provider', None) or ""
            model = getattr(agent, 'model', None) or ""
            self.status.hermes_provider = f"{provider}/{model}"
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        self._persist_handshake()
        self._emit("on_connect", self.status)
        return self.status

    def before_turn(self, agent, messages: list, system_prompt: str = "") -> str:
        self.status.last_sync = time.time()
        brain = getattr(agent, 'laap_brain', None) or self._laap_brain
        if not brain:
            return ""
        try:
            hint = brain.before_turn(messages, system_prompt)
            if hasattr(brain, 'self_model'):
                self.status.cognitive_state = {
                    "efficacy": getattr(brain.self_model, 'self_efficacy', 0),
                    "domains": len(getattr(brain.self_model, 'domain_scores', {})),
                    "interactions": getattr(brain.self_model, 'total_interactions', 0),
                }
            return hint or ""
        except Exception:
            return ""

    def after_tool(self, tool_name: str, result: Any):
        self.status.sync_count += 1

    def after_turn(self, agent, response: str):
        self.status.laap_last_heartbeat = time.time()
        self.status.last_sync = time.time()
        brain = getattr(agent, 'laap_brain', None) or self._laap_brain
        if brain and hasattr(brain, 'after_turn'):
            try:
                brain.after_turn(response)
            except Exception as e:
                logger.debug(f"操作失败: {e}")
        self._persist_handshake()

    def share(self, key: str, value: Any, source: str = "laap"):
        with self._info_bus_lock:
            self._info_bus[f"{source}:{key}"] = {
                "value": value, "timestamp": time.time(), "source": source,
            }
        if source == "laap":
            self.status.cognitive_state[key] = value
        else:
            self.status.infra_state[key] = value
        self._emit("on_share", {"key": key, "value": value, "source": source})

    def get(self, key: str, default: Any = None) -> Any:
        with self._info_bus_lock:
            if key in self._info_bus:
                return self._info_bus[key]["value"]
            for prefix in ("laap:", "hermes:"):
                pk = f"{prefix}{key}"
                if pk in self._info_bus:
                    return self._info_bus[pk]["value"]
            parts = key.split(".")
            if len(parts) >= 2:
                if parts[0] == "cognitive":
                    return self.status.cognitive_state.get(parts[1], default)
                elif parts[0] == "infra":
                    return self.status.infra_state.get(parts[1], default)
        return default

    def get_all_shared(self) -> Dict[str, Any]:
        with self._info_bus_lock:
            return {k: v["value"] for k, v in self._info_bus.items()}

    def get_status(self) -> HandshakeStatus:
        return self.status

    def is_connected(self) -> bool:
        return self.status.laap_healthy and self.status.hermes_available

    def _persist_handshake(self):
        try:
            path = _LAAP_DIR / "handshake.json"
            path.write_text(
                json.dumps(self.status.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    def integrate_into_agent(self, agent, brain=None):
        agent.laap_handshake = self
        if brain and not hasattr(agent, 'laap_brain'):
            agent.laap_brain = brain
        self.init_hermes(agent)
        if brain:
            self.share("efficacy", getattr(brain.self_model, 'self_efficacy', 0.5), "laap")
            self.share("modules", {k: "active" for k in getattr(brain, '__dict__', {}).keys()}, "laap")
        self._patch_agent_with_hooks(agent)
        logger.info(f"Handshake integrated into agent {getattr(agent, 'session_id', '?')}")

    def _patch_agent_with_hooks(self, agent):
        if not hasattr(agent, 'laap_before_turn'):
            agent.laap_before_turn = lambda msgs, sp: self.before_turn(agent, msgs, sp)
        if not hasattr(agent, 'laap_after_tool'):
            agent.laap_after_tool = lambda name, result: self.after_tool(name, result)
        if not hasattr(agent, 'laap_after_turn'):
            agent.laap_after_turn = lambda resp: self.after_turn(agent, resp)


# ══════════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════════

def init_handshake(brain=None, modules: Dict[str, str] = None,
                   hermes_home: str = "") -> HandshakeProtocol:
    hs = HandshakeProtocol.get_instance()
    hs.init_laap(brain=brain, modules=modules, hermes_home=hermes_home)
    return hs


def connect_agent(agent, brain=None) -> HandshakeProtocol:
    hs = HandshakeProtocol.get_instance()
    hs.integrate_into_agent(agent, brain=brain)
    return hs


def handshake_status() -> HandshakeStatus:
    return HandshakeProtocol.get_instance().get_status()


def show_handshake():
    hs = HandshakeProtocol.get_instance()
    logger.info(hs.get_status().summary())
def register_lifeform(name: str, state: dict = None) -> HandshakeProtocol:
    """注册到 IPC 网络（便捷函数）"""
    hs = HandshakeProtocol.get_instance()
    hs.register_lifeform(name, state)
    return hs


def send_message(to: str, subject: str, body: str) -> bool:
    """发送跨进程消息（便捷函数）"""
    return HandshakeProtocol.get_instance().send_message(to, subject, body)


def read_messages() -> List[Dict]:
    """读取新消息（便捷函数）"""
    return HandshakeProtocol.get_instance().read_messages()


def show_network() -> str:
    """显示网络状态（便捷函数）"""
    return HandshakeProtocol.get_instance().show_network()
