"""
Gated Long-Attention Memory (GLAM) — classical sigmoid probabilistic gating, no quantum hardware
================================================================================================

GLAM Core Cell Implementation.
Provides a gated RNN-style mixing cell that combines a learned linear
projection with a lightweight classical probabilistic attention gate
(sigmoid over dot-product similarity).  No quantum hardware is
required — the gate uses a classical probabilistic (sigmoid) activation.

# 历史名称 QLAM 已重命名为 GLAM（经典 sigmoid 概率门控，非量子）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

logger = __import__("logging").getLogger("laap.glam")


@dataclass
class GLAMConfig:
    hidden_dim: int = 512
    num_heads: int = 8
    num_layers: int = 4
    probabilistic_dim: int = 64  # 历史名称 quantum_dim 已重命名为 probabilistic_dim（经典概率实现，非量子）
    dropout: float = 0.1
    use_probabilistic_encoder: bool = False  # 历史名称 use_quantum_encoder 已重命名（经典概率实现，非量子）
    use_pqc: bool = False
    vocab_size: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class GLAMCell:
    """Gated RNN-style mixing cell with a sigmoid attention gate.

    The cell maintains a learnable projection matrix W (hidden_dim × hidden_dim)
    and a key vector k.  On each forward pass it computes:

        mixed = x @ W
        gate  = sigmoid(dot(mixed, k) / sqrt(hidden_dim))
        out   = gate * mixed + (1 - gate) * x

    This gives the cell a simple classical probabilistic memory: the gate
    decides how much of the transformed signal to blend with the raw input.
    """

    def __init__(self, config: Optional[GLAMConfig] = None):
        self.config = config or GLAMConfig()
        self._step = 0
        self._state: Optional["np.ndarray"] = None
        # Learnable parameters (initialised lazily on first forward)
        self._W: Optional["np.ndarray"] = None
        self._k: Optional["np.ndarray"] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forward(
        self,
        x: "np.ndarray",
        state: Optional["np.ndarray"] = None,
    ) -> Tuple["np.ndarray", Optional["np.ndarray"]]:
        """Run one GLAM timestep.

        Parameters
        ----------
        x : np.ndarray, shape (batch, hidden_dim) or (hidden_dim,)
            Input tensor.
        state : np.ndarray or None
            Previous hidden state (unused in current implementation; kept
            for API compatibility).

        Returns
        -------
        (output, state) : (np.ndarray, np.ndarray or None)
        """
        if np is None:
            raise ImportError("numpy is required for GLAMCell.forward()")

        x_arr = np.asarray(x, dtype=np.float32)
        squeeze = x_arr.ndim == 1
        if squeeze:
            x_arr = x_arr[None, :]  # (1, hidden_dim)

        H = self.config.hidden_dim

        # Lazy initialisation
        if self._W is None or self._k is None:
            rng = np.random.default_rng(42 + self._step)
            self._W = rng.normal(0, 1 / math.sqrt(H), (H, H)).astype(np.float32)
            self._k = rng.normal(0, 1 / math.sqrt(H), (H,)).astype(np.float32)

        # Project
        mixed = x_arr @ self._W  # (batch, H)

        # Gate: sigmoid over scaled dot product
        dot = mixed @ self._k  # (batch,)
        gate = 1.0 / (1.0 + np.exp(-dot / math.sqrt(H)))  # sigmoid
        gate = gate[:, None]  # (batch, 1)

        # Blend
        out = gate * mixed + (1.0 - gate) * x_arr

        self._step += 1

        if squeeze:
            out = out[0]

        return out, state

    def reset_state(self) -> None:
        """Reset the internal step counter (state is stateless)."""
        self._step = 0
        self._state = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def hidden_size(self) -> int:
        return self.config.hidden_dim

    def __repr__(self) -> str:
        return (
            f"GLAMCell(hidden={self.config.hidden_dim}, "
            f"heads={self.config.num_heads}, layers={self.config.num_layers})"
        )
