"""Key Management — 密钥管理"""
from __future__ import annotations
import time, json, hashlib, os, logging, threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("security.crypto.keys")

@dataclass
class KeyPair:
    public_key: str = ""
    private_key: str = ""
    algorithm: str = "ed25519"
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

class KeyManager:
    def __init__(self):
        self._keys: Dict[str, KeyPair] = {}
        self._lock = threading.RLock()

    @property
    def keys(self) -> Dict[str, KeyPair]:
        return self._keys

    def generate_key(self, key_id: str, algorithm: str = "ed25519") -> str:
        """Compatibility: generate key and return the key id."""
        self.generate(key_id, algorithm)
        return key_id

    def get_key(self, key_id: str):
        """Compatibility: return key by id."""
        return self.get(key_id)

    def delete_key(self, key_id: str) -> bool:
        """Compatibility: delete key by id."""
        with self._lock:
            if key_id in self._keys:
                del self._keys[key_id]
                return True
            return False

    def generate(self, key_id: str = "", algorithm: str = "ed25519") -> KeyPair:
        import uuid
        seed = uuid.uuid4().hex
        priv = hashlib.sha256(seed.encode()).hexdigest()
        pub = hashlib.sha256(priv.encode()).hexdigest()
        kp = KeyPair(public_key=pub, private_key=priv, algorithm=algorithm)
        kid = key_id or f"key_{kp.created_at}"
        with self._lock:
            self._keys[kid] = kp
        return kp
    def get(self, key_id: str) -> Optional[KeyPair]:
        with self._lock:
            kp = self._keys.get(key_id)
            if kp and kp.expires_at and time.time() > kp.expires_at:
                del self._keys[key_id]
                return None
            return kp
    def rotate(self, key_id: str) -> Optional[KeyPair]:
        with self._lock:
            old = self._keys.get(key_id)
            if not old:
                return None
            new_kp = self.generate(key_id, old.algorithm)
            old.expires_at = time.time()
            return new_kp
    def sign(self, key_id: str, message: str) -> str:
        kp = self.get(key_id)
        if not kp:
            raise ValueError(f"Key not found: {key_id}")
        return hashlib.sha256((message + kp.private_key).encode()).hexdigest()
    def verify(self, public_key: str, message: str, signature: str) -> bool:
        expected = hashlib.sha256((message + public_key).encode()).hexdigest()
        return signature == expected
