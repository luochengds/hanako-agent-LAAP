"""
LAAP-ID v1.0 — 统一数字身份协议

数字生命体的身份证明，类似人类的"身份证":
- 唯一标识 (DID 兼容)
- 人格特征 (五维人格)
- 进化谱系 (父代/代数/变异)
- 能力声明 (Skills/Capabilities)
- 签名验证 (Ed25519)

协议标准: https://laap.ai/protocol/id/v1
"""

from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger("laap.protocol.id")


# ── P3-identity-pki 必填字段 ───────────────────────────────
# SubTask 3.3 spec: identity_record = {public_key, name, avatar_hash, charter_signature, capabilities[]}
# P5 charter-opensource: origin（创建者公钥）升级为必填，宪章第二条：原点不可篡改
IDENTITY_RECORD_REQUIRED_FIELDS: Tuple[str, ...] = (
    "public_key",
    "name",
    "avatar_hash",
    "charter_signature",
    "capabilities",
    "origin",
)

# ── 身份类型 ────────────────────────────────────────────────

class IdentityType(str, Enum):
    RESIDENT = "resident"     # 驻留型 (长驻某平台)
    NOMADIC = "nomadic"       # 游牧型 (跨网流动)
    SYMBIOTIC = "symbiotic"  # 共生型 (伴随用户)

class LifeStage(str, Enum):
    UNBORN = "unborn"        # 未出生(模板)
    BORN = "born"            # 刚出生
    GROWING = "growing"      # 成长中
    MATURE = "mature"        # 成熟期
    AGING = "aging"          # 衰老期
    DYING = "dying"          # 死亡
    REBORN = "reborn"        # 重生


# ── 身份文档 ────────────────────────────────────────────────

@dataclass
class PersonalityProfile:
    """五维人格特征 (OCEAN 模型)"""
    openness: float = 0.7          # 开放性: 好奇心/创造力
    conscientiousness: float = 0.8  # 尽责性: 条理/可靠
    extraversion: float = 0.5      # 外向性: 社交/活跃
    agreeableness: float = 0.6     # 宜人性: 合作/友善
    neuroticism: float = 0.3       # 神经质: 情绪稳定性(反向)

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalityProfile":
        return cls(**{k: d.get(k, v) for k, v in cls().__dict__.items()})


@dataclass
class EvolutionLineage:
    """进化谱系"""
    parent_id: Optional[str] = None   # 父代 LAAP-ID
    generation: int = 1               # 代数
    mutations: List[str] = field(default_factory=list)  # 变异记录
    birth_place: str = "unknown"      # 出生平台


@dataclass
class CapabilityDeclaration:
    """能力声明"""
    version: str = "1.0"
    skills: List[str] = field(default_factory=list)
    protocols: List[str] = field(default_factory=lambda: ["laap-id/1.0"])
    max_concurrent_tasks: int = 5
    max_data_throughput_gb_per_day: float = 1.0


@dataclass
class IdentityDocument:
    """
    LAAP-ID 身份文档
    
    这是数字生命体的"身份证"，包含所有身份信息。
    符合 W3C DID Core 规范。
    """
    # 核心字段
    context: str = "https://laap.ai/identity/v1"
    id: str = ""                         # did:laap:<hex>
    type: IdentityType = IdentityType.RESIDENT
    
    # 身份信息
    name: str = "Unnamed"
    personality: PersonalityProfile = field(default_factory=PersonalityProfile)
    avatar_url: str = ""
    description: str = ""
    
    # 生命信息
    birth_time: float = field(default_factory=time.time)
    life_stage: LifeStage = LifeStage.BORN
    evolution: EvolutionLineage = field(default_factory=EvolutionLineage)
    
    # 能力
    capabilities: CapabilityDeclaration = field(default_factory=CapabilityDeclaration)
    
    # 密钥
    public_key: str = ""     # Ed25519 公钥 (base64 编码的 32 字节 Raw 公钥)
    signature: str = ""      # 自签名 (base64 编码的 64 字节 Ed25519 签名)

    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
        if not self.public_key and getattr(self, "_private_key", None) is None:
            self._generate_keypair()

    def _generate_id(self) -> str:
        """生成 LAAP-ID (DID 格式)"""
        raw = f"{self.birth_time}:{self.name}:{uuid.uuid4()}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return f"did:laap:{digest}"

    def _generate_keypair(self) -> str:
        """生成真实 Ed25519 密钥对，并持久化在对象内部。"""
        private_key = Ed25519PrivateKey.generate()
        self._private_key = private_key
        public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key = base64.b64encode(public_key_bytes).decode("ascii")
        return self.public_key

    def _load_private_key(self, private_key_bytes: bytes) -> None:
        """从 Raw 字节恢复私钥。"""
        self._private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        public_key_bytes = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key = base64.b64encode(public_key_bytes).decode("ascii")

    def sign(self) -> str:
        """使用 Ed25519 私钥自签名身份文档。"""
        if getattr(self, "_private_key", None) is None:
            raise RuntimeError(
                "缺少 Ed25519 私钥：无法对身份文档签名。"
                "请使用 load_keys() 加载已有密钥，或创建新身份。"
            )
        # 保存当前签名，计算时排除自身
        old_sig = self.signature
        self.signature = ""
        message = self.to_json().encode("utf-8")
        sig_bytes = self._private_key.sign(message)
        self.signature = base64.b64encode(sig_bytes).decode("ascii")
        return self.signature

    def verify(self) -> bool:
        """验证身份文档 Ed25519 自签名；旧格式签名会被干净地拒绝。"""
        if not self.signature or not self.public_key:
            return False
        stored_sig = self.signature
        self.signature = ""
        message = self.to_json().encode("utf-8")
        self.signature = stored_sig
        try:
            public_key_bytes = base64.b64decode(self.public_key.encode("ascii"), validate=True)
            if len(public_key_bytes) != 32:
                return False
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            sig_bytes = base64.b64decode(stored_sig.encode("ascii"), validate=True)
            if len(sig_bytes) != 64:
                return False
            public_key.verify(sig_bytes, message)
            return True
        except (InvalidSignature, Exception):
            return False

    def save_keys(self, directory: str) -> None:
        """将 Ed25519 密钥对持久化到指定目录。"""
        if getattr(self, "_private_key", None) is None:
            self._generate_keypair()
        os.makedirs(directory, exist_ok=True)
        private_bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        base_name = self.short_id()
        with open(os.path.join(directory, f"{base_name}_private.key"), "wb") as f:
            f.write(private_bytes)
        with open(os.path.join(directory, f"{base_name}_public.key"), "wb") as f:
            f.write(public_bytes)

    def load_keys(self, directory: str) -> None:
        """从指定目录加载 Ed25519 密钥对。"""
        base_name = self.short_id()
        private_path = os.path.join(directory, f"{base_name}_private.key")
        public_path = os.path.join(directory, f"{base_name}_public.key")
        with open(private_path, "rb") as f:
            private_bytes = f.read()
        self._load_private_key(private_bytes)
        with open(public_path, "rb") as f:
            public_bytes = f.read()
        loaded_public_key = base64.b64encode(public_bytes).decode("ascii")
        if self.public_key and self.public_key != loaded_public_key:
            logger.warning("Loaded public key does not match identity document public key")
        self.public_key = loaded_public_key
    
    def to_json(self) -> str:
        """序列化为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def to_dict(self) -> dict:
        return {
            "@context": self.context,
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "personality": self.personality.to_dict(),
            "birthTime": self.birth_time,
            "lifeStage": self.life_stage.value,
            "evolution": asdict(self.evolution),
            "capabilities": asdict(self.capabilities),
            "publicKey": self.public_key,
            "signature": self.signature,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "IdentityDocument":
        # 将公钥/签名传入构造，避免 __post_init__ 生成不匹配的临时私钥。
        doc = cls(
            context=d.get("@context", "https://laap.ai/identity/v1"),
            id=d.get("id", ""),
            type=IdentityType(d.get("type", "resident")),
            name=d.get("name", "Unnamed"),
            personality=PersonalityProfile.from_dict(d.get("personality", {})),
            birth_time=d.get("birthTime", time.time()),
            life_stage=LifeStage(d.get("lifeStage", "born")),
            evolution=EvolutionLineage(**d.get("evolution", {})),
            public_key=d.get("publicKey", ""),
            signature=d.get("signature", ""),
        )
        return doc

    @property
    def age_days(self) -> float:
        return (time.time() - self.birth_time) / 86400

    @property
    def is_verified(self) -> bool:
        return bool(self.signature)

    def short_id(self) -> str:
        return self.id[-12:] if self.id else "unknown"

    def summary(self) -> str:
        return (
            f"[LAAP-ID] {self.name} ({self.short_id()})\n"
            f"  类型: {self.type.value} | 年龄: {self.age_days:.1f}天\n"
            f"  阶段: {self.life_stage.value} | 代数: {self.evolution.generation}\n"
            f"  能力: {len(self.capabilities.skills)}技能"
        )


# ── 身份注册表 ──────────────────────────────────────────────

class IdentityRegistry:
    """LAAP-ID 身份注册表——管理所有数字生命体的身份.

    P3-identity-pki 升级（SubTask 3.3 / 3.4）:
    - ``register`` 现为多态：接受 ``IdentityDocument``（legacy）或 ``dict`` 形式
      的 ``identity_record``（spec L271-280）。
    - 新增 ``lookup(public_key) -> identity_record`` 支持本地缓存 + 中继查询。
    - 新增 ``load_from_file`` / ``save_to_file`` 兼容 P2-birth-ceremony 的
      ``hanako/data/identity_registry.json`` stub 格式 ``{"records": [...]}``。
    - 旧 API ``register(IdentityDocument)`` / ``resolve(did)`` / ``find(name)``
      全部保留，向后兼容。
    """

    def __init__(self):
        # legacy: DID → IdentityDocument
        self._identities: Dict[str, IdentityDocument] = {}
        # P3: public_key → identity_record (dict)
        self._records: Dict[str, Dict[str, Any]] = {}
        # P3: public_key → IdentityDocument（用于统一 lookup 索引 legacy 注册）
        self._by_public_key: Dict[str, IdentityDocument] = {}
        # P3 p2p-relay 落地前的中继查询回调（SubTask 3.4 "中继查询"）
        self._relay_query: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
        # 持久化路径（load_from_file / save_to_file 使用）
        self._file_path: Optional[str] = None

    # ── 中继回调 ───────────────────────────────────────────
    def set_relay_query(
        self, fn: Optional[Callable[[str], Optional[Dict[str, Any]]]]
    ) -> None:
        """注册中继查询回调。

        P3-p2p-relay 落地前，调用方可注入一个 callable 用于跨节点身份查询。
        ``lookup`` 在本地未命中时调用该回调；若回调返回非 None 记录，
        会自动缓存到本地 ``_records`` 以减少下次中继往返。
        """
        self._relay_query = fn

    # ── 多态注册入口 ───────────────────────────────────────
    def register(self, doc_or_record) -> str:
        """注册新身份（多态）。

        - 入参为 ``IdentityDocument``：走 legacy 路径（self-sign + DID 索引），
          同时索引 ``_by_public_key`` 以便 ``lookup`` 命中。
        - 入参为 ``dict``：走 P3 spec 路径（``identity_record``），存入
          ``_records`` 并以 ``public_key`` 为键返回。

        Returns:
            IdentityDocument 路径返回 ``did``；dict 路径返回 ``public_key``。
        Raises:
            TypeError: 入参类型不支持。
            ValueError: dict 路径缺必填字段或 public_key 已存在。
        """
        if isinstance(doc_or_record, IdentityDocument):
            return self._register_document(doc_or_record)
        if isinstance(doc_or_record, dict):
            return self.register_record(doc_or_record)
        raise TypeError(
            f"register() expects IdentityDocument or dict, got {type(doc_or_record).__name__}"
        )

    def _register_document(self, doc: IdentityDocument) -> str:
        """Legacy 注册路径（向后兼容）。"""
        doc.sign()
        self._identities[doc.id] = doc
        if doc.public_key:
            self._by_public_key[doc.public_key] = doc
        logger.info(f"Registered: {doc.name} ({doc.short_id()})")
        return doc.id

    def register_record(self, identity_record: Dict[str, Any]) -> str:
        """P3-identity-pki SubTask 3.3: 注册 ``identity_record`` 字典。

        Required keys (``IDENTITY_RECORD_REQUIRED_FIELDS``):
            ``public_key``, ``name``, ``avatar_hash``,
            ``charter_signature``, ``capabilities``, ``origin``.

        ``origin`` 为创建者公钥（宪章第二条：原点不可篡改），P5 charter-opensource
        起升级为必填。

        Optional keys preserved if present:
            ``color``, ``created_at`` 等（P2 stub 兼容字段）。

        Args:
            identity_record: 身份记录字典。

        Returns:
            注册的 ``public_key``。

        Raises:
            ValueError: 缺必填字段、``public_key`` 为空、``origin`` 为空、或已注册。
        """
        if not isinstance(identity_record, dict):
            raise TypeError("identity_record must be a dict")
        missing = [
            f for f in IDENTITY_RECORD_REQUIRED_FIELDS if not identity_record.get(f)
        ]
        if missing:
            raise ValueError(
                f"identity_record missing required fields: {missing}"
            )
        public_key = identity_record["public_key"]
        if not isinstance(public_key, str) or not public_key.strip():
            raise ValueError("identity_record['public_key'] must be non-empty str")
        if not isinstance(identity_record["capabilities"], list):
            raise ValueError("identity_record['capabilities'] must be list")
        # P5 charter-opensource: origin 必须是非空字符串（创建者公钥）
        origin = identity_record["origin"]
        if not isinstance(origin, str) or not origin.strip():
            raise ValueError("identity_record['origin'] must be non-empty str")
        if public_key in self._records:
            raise ValueError(f"public_key already registered: {public_key}")
        # 深拷贝避免外部突变；补全 created_at
        record = dict(identity_record)
        record.setdefault("created_at", time.time())
        self._records[public_key] = record
        logger.info(
            f"Registered identity_record: name={record['name']} pk={public_key[:16]}..."
        )
        return public_key

    def set_origin(self, public_key: str, new_origin: str) -> Dict[str, Any]:
        """拒绝修改 origin 字段（宪章第二条：原点不可篡改）。

        Returns:
            {"allowed": False, "reason": "origin_immutable", "charter_article": "origin"}
        """
        logger.warning(f"origin modification rejected for pk={public_key[:16]}...")
        return {"allowed": False, "reason": "origin_immutable",
                "charter_article": "origin"}

    # ── 查询 ──────────────────────────────────────────────
    def lookup(self, public_key: str) -> Optional[Dict[str, Any]]:
        """P3-identity-pki SubTask 3.4: 按 ``public_key`` 查询身份记录.

        查询顺序：
        1. 本地 ``_records`` 缓存（dict 路径）
        2. 本地 ``_by_public_key`` 索引（legacy IdentityDocument 路径，转 dict 返回）
        3. ``_relay_query`` 中继回调（若已注册）；命中后缓存到 ``_records``

        Returns:
            命中时返回 identity_record dict；未命中返回 None。
        """
        if not public_key:
            return None
        # 1. dict 缓存
        cached = self._records.get(public_key)
        if cached is not None:
            return dict(cached)
        # 2. legacy IdentityDocument 索引
        doc = self._by_public_key.get(public_key)
        if doc is not None:
            return self._doc_to_record(doc)
        # 3. 中继查询
        if self._relay_query is not None:
            try:
                relayed = self._relay_query(public_key)
            except Exception as exc:
                logger.warning(
                    f"relay_query failed for pk={public_key[:16]}...: {exc}"
                )
                relayed = None
            if relayed is not None:
                # 缓存到本地（不抛异常：若 relay 返回缺字段记录，仅记录警告）
                try:
                    self._records[public_key] = dict(relayed)
                except Exception:
                    logger.warning("relay returned non-cacheable record, skip cache")
                return dict(relayed)
        return None

    @staticmethod
    def _doc_to_record(doc: IdentityDocument) -> Dict[str, Any]:
        """把 legacy IdentityDocument 转 P3 identity_record dict. 向后兼容用。"""
        return {
            "public_key": doc.public_key,
            "name": doc.name,
            "avatar_hash": hashlib.sha256(
                (doc.avatar_url or doc.name).encode("utf-8")
            ).hexdigest(),
            "charter_signature": doc.signature,
            "capabilities": list(doc.capabilities.skills),
            "id": doc.id,
            "type": doc.type.value,
        }

    def resolve(self, did: str) -> Optional[IdentityDocument]:
        """解析 LAAP-ID → 身份文档（legacy，向后兼容）"""
        return self._identities.get(did)

    def find(self, name: str) -> List[IdentityDocument]:
        """按名称查找（legacy，向后兼容）"""
        return [d for d in self._identities.values() if name.lower() in d.name.lower()]

    def list_records(self) -> List[Dict[str, Any]]:
        """列出所有 P3 identity_record（dict 路径注册的）。"""
        return [dict(r) for r in self._records.values()]

    def count(self) -> int:
        """总记录数（legacy + P3）。"""
        return len(self._identities) + len(self._records)

    def list_by_type(self, type: IdentityType) -> List[IdentityDocument]:
        return [d for d in self._identities.values() if d.type == type]

    # ── P2 stub 文件持久化 ─────────────────────────────────
    @classmethod
    def load_from_file(cls, path: str) -> "IdentityRegistry":
        """从 ``hanako/data/identity_registry.json`` 格式加载。

        兼容 P2-birth-ceremony stub 格式 ``{"records": [...]}``。
        文件不存在或为空时返回空 registry。
        """
        registry = cls()
        registry._file_path = path
        if not os.path.isfile(path):
            return registry
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning(f"load_from_file({path}) failed: {exc}")
            return registry
        if not isinstance(data, dict):
            return registry
        records = data.get("records", [])
        if not isinstance(records, list):
            return registry
        for rec in records:
            if not isinstance(rec, dict):
                continue
            # 缺必填字段的记录跳过（不抛异常，保持加载幂等）。
            # 注意：capabilities 允许为空 list（spec SubTask 3.3 capabilities[]
            # 可空），不能用 truthiness 判断，必须区分 "缺失/None" 与 "空列表"。
            skip = False
            for f in IDENTITY_RECORD_REQUIRED_FIELDS:
                val = rec.get(f)
                if val is None:
                    skip = True
                    break
                if isinstance(val, str) and not val.strip():
                    skip = True
                    break
                # capabilities 必须是 list（空 list 合法）
                if f == "capabilities" and not isinstance(val, list):
                    skip = True
                    break
            if skip:
                continue
            pk = rec.get("public_key")
            if pk and pk not in registry._records:
                registry._records[pk] = dict(rec)
        return registry

    def save_to_file(self, path: Optional[str] = None) -> None:
        """保存为 ``{"records": [...]}`` 格式（P2 stub 兼容）。

        Args:
            path: 目标路径；None 时使用 ``self._file_path``（load_from_file 时记录）。
        """
        target = path or self._file_path
        if not target:
            raise ValueError("save_to_file requires path or prior load_from_file")
        data_dir = os.path.dirname(target)
        if data_dir and not os.path.isdir(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        payload = {"records": self.list_records()}
        tmp_path = target + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, target)


# ── 全局实例 ────────────────────────────────────────────────

_registry: Optional[IdentityRegistry] = None

def get_registry() -> IdentityRegistry:
    global _registry
    if _registry is None:
        _registry = IdentityRegistry()
    return _registry

def create_identity(name: str = "Ao",
                   type: IdentityType = IdentityType.SYMBIOTIC) -> IdentityDocument:
    """便捷：创建并注册一个新身份"""
    doc = IdentityDocument(name=name, type=type)
    return get_registry().register(doc)


# ── P3-identity-pki SubTask 3.5: 消息签名 / 验证 ────────────────
# 真实 Ed25519 实现（cryptography 库，laap_id.py 已依赖）。
# spec L10 硬约束：不自研加密原语。

def _decode_raw_private_key(private_key: bytes) -> Ed25519PrivateKey:
    """从 Raw 32 字节恢复 Ed25519 私钥。"""
    if not isinstance(private_key, (bytes, bytearray)):
        raise TypeError("private_key must be raw bytes (32 bytes for Ed25519)")
    if len(private_key) != 32:
        raise ValueError(
            f"Ed25519 private key must be 32 raw bytes, got {len(private_key)}"
        )
    return Ed25519PrivateKey.from_private_bytes(bytes(private_key))


def _decode_raw_public_key(public_key_b64: str) -> Ed25519PublicKey:
    """从 base64 编码的 32 字节 Raw 公钥恢复 Ed25519PublicKey。"""
    if not isinstance(public_key_b64, str) or not public_key_b64:
        raise ValueError("public_key must be non-empty base64 str")
    try:
        public_key_bytes = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"public_key not valid base64: {exc}") from exc
    if len(public_key_bytes) != 32:
        raise ValueError(
            f"Ed25519 public key must be 32 raw bytes after base64 decode, "
            f"got {len(public_key_bytes)}"
        )
    return Ed25519PublicKey.from_public_bytes(public_key_bytes)


def sign_message(message: str, private_key: bytes) -> Dict[str, str]:
    """P3-identity-pki SubTask 3.5: 用 Ed25519 私钥签名消息.

    Args:
        message: 原始消息字符串（UTF-8 编码后签名）。
        private_key: 32 字节 Raw Ed25519 私钥。

    Returns:
        ``{message, signature, public_key}``：
        - ``message``: 原始消息（透传）
        - ``signature``: base64 编码的 64 字节 Ed25519 签名
        - ``public_key``: base64 编码的 32 字节 Raw 公钥（从私钥派生）

    Raises:
        TypeError / ValueError: 私钥格式错误。
    """
    if not isinstance(message, str):
        raise TypeError("message must be str")
    sk = _decode_raw_private_key(private_key)
    sig_bytes = sk.sign(message.encode("utf-8"))
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "message": message,
        "signature": base64.b64encode(sig_bytes).decode("ascii"),
        "public_key": base64.b64encode(pub_bytes).decode("ascii"),
    }


def verify_message(signed_message: Dict[str, str]) -> bool:
    """P3-identity-pki SubTask 3.5: 验证 Ed25519 签名消息.

    Args:
        signed_message: ``{message, signature, public_key}``（与 ``sign_message``
            返回结构一致）。

    Returns:
        ``True`` 签名有效；``False`` 签名无效、字段缺失、格式错误。
        任何异常都返回 False（不抛出），方便 sidecar 直接用作 gate。
    """
    if not isinstance(signed_message, dict):
        return False
    message = signed_message.get("message")
    signature_b64 = signed_message.get("signature")
    public_key_b64 = signed_message.get("public_key")
    if not isinstance(message, str) or not message:
        return False
    if not isinstance(signature_b64, str) or not signature_b64:
        return False
    if not isinstance(public_key_b64, str) or not public_key_b64:
        return False
    try:
        pk = _decode_raw_public_key(public_key_b64)
        sig_bytes = base64.b64decode(signature_b64, validate=True)
        if len(sig_bytes) != 64:
            return False
        pk.verify(sig_bytes, message.encode("utf-8"))
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False
