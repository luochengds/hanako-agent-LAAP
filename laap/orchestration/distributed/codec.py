"""AetherMessage codec using msgpack."""

from __future__ import annotations

import msgpack

from laap.orchestration.primitives import AetherMessage


class AetherCodec:
    """Serialize and deserialize :class:`AetherMessage` instances."""

    def encode(self, msg: AetherMessage) -> bytes:
        return msgpack.packb(msg.to_dict(), use_bin_type=True)

    def decode(self, payload: bytes) -> AetherMessage:
        data = msgpack.unpackb(payload, raw=False)
        return AetherMessage.from_dict(data)
