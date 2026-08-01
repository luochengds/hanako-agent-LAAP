"""H-QKV: Hamiltonian-Query-Key-Value attention mechanism.

Bias-only formulation (no dimension projection required):

  U = exp(-i·H·dt)                — cognitive unitary (d_cog × d_cog)
  C[i,j] = Σ_k p_k · cos(E_k · Δ) — coherence bias (N × N)
  p_k = |⟨e_k|ψ⟩|²                — Born probability of eigenmode k
  Δ = (j - i) · dt                — relative cognitive time

  A = softmax(Q·K^T/√d + λ·C) · V — bias-modified attention

Physical interpretation:
  H's eigendecomposition gives the 'natural frequencies' of the cognitive system.
  C[i,j] is the quantum propagator's real part — how much cognitive state at
  position i coheres with position j.  High coherence → attend together.
  Low coherence (destructive interference) → attend separately.

This is the quantum version of ALiBi (Attention with Linear Biases) —
instead of a fixed position bias, the bias is dynamically shaped by
the current cognitive state |ψ⟩.
"""

from __future__ import annotations

import math
import logging
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger('hqkv.attention')


class HQKVAttention(nn.Module):
    """Transformer attention with H-QKV cognitive bias injection.

    Parameters
    ----------
    d_model : int
        Transformer model dimension.
    n_heads : int
        Number of attention heads.
    d_cog : int
        Cognitive Hilbert space dimension (default 8).
    use_bias : bool
        If True, apply H-QKV coherence bias.  If False, standard attention.
    """

    def __init__(self, d_model: int, n_heads: int,
                 d_cog: int = 8, use_bias: bool = True):
        super().__init__()
        assert d_model % n_heads == 0, \
            f"d_model ({d_model}) must be divisible by n_heads ({n_heads})"

        self.d_model = d_model
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        self.d_cog = d_cog
        self.use_bias = use_bias

        # Standard attention projections
        self.W_q = nn.Linear(d_model, d_model, bias=False)
        self.W_k = nn.Linear(d_model, d_model, bias=False)
        self.W_v = nn.Linear(d_model, d_model, bias=False)
        self.W_o = nn.Linear(d_model, d_model, bias=False)

        # Cognitive projection (maps each head's Q to cognitive bias space)
        # This is a lightweight linear layer: (d_head,) → (d_cog,)
        self.W_cog = nn.Parameter(
            torch.randn(n_heads, d_cog, self.d_head) * 0.02
        )

        self._init_weights()

    def _init_weights(self):
        """Initialize weights with small normal (standard transformer init)."""
        nn.init.normal_(self.W_q.weight, std=0.02)
        nn.init.normal_(self.W_k.weight, std=0.02)
        nn.init.normal_(self.W_v.weight, std=0.02)
        nn.init.normal_(self.W_o.weight, std=0.02)

    # -- Core: coherence bias computation ----------------------------------

    def compute_coherence_bias(
        self,
        H: torch.Tensor,       # (d_cog, d_cog) Hermitian
        psi: torch.Tensor,     # (d_cog,) complex state vector
        seq_len: int,
        dt: float = 0.025,
        device: Optional[torch.device] = None,
    ) -> torch.Tensor:
        """Compute the coherence bias matrix C ∈ ℝ^(N×N).

        C[i,j] = Σ_k p_k · cos(E_k · (j - i) · dt)

        where {E_k, |e_k⟩} are the eigenvalues/eigenvectors of H,
        and p_k = |⟨e_k|ψ⟩|².

        Parameters
        ----------
        H : torch.Tensor
            Hermitian cognitive Hamiltonian (d_cog, d_cog).
        psi : torch.Tensor
            Current cognitive state vector (d_cog,).
        seq_len : int
            Sequence length N.
        dt : float
            Cognitive time step.
        device : torch.device, optional

        Returns
        -------
        torch.Tensor
            Coherence bias matrix (N, N).
        """
        if device is None:
            device = H.device

        # 1. Eigendecomposition of H
        # H is Hermitian → torch.linalg.eigh returns real eigenvalues
        eigvals, eigvecs = torch.linalg.eigh(H)  # (d_cog,), (d_cog, d_cog)

        # 2. Born probabilities p_k = |⟨e_k|ψ⟩|²
        psi = psi.to(device)
        overlaps = (eigvecs.conj().T @ psi)  # (d_cog,) complex
        probs = overlaps.abs() ** 2           # (d_cog,) real, sums to 1

        # 3. Position difference matrix (N, N)
        pos = torch.arange(seq_len, device=device, dtype=torch.float32)
        delta = pos.unsqueeze(1) - pos.unsqueeze(0)  # (N, N) anti-symmetric

        # 4. Coherence bias C[i,j] = Σ_k p_k · cos(E_k · Δ · dt)
        # Use weighted sum over eigenmodes
        angular = eigvals * dt  # (d_cog,)
        # (N, N) = Σ_k p_k · cos(ω_k · Δ)
        # Einstein sum: p_k · cos(ω_k · Δ_ij)
        # Result shape: (N, N)
        cos_terms = torch.cos(angular.unsqueeze(1).unsqueeze(1) * delta.unsqueeze(0))
        # cos_terms shape: (d_cog, N, N)
        C = (probs.unsqueeze(-1).unsqueeze(-1) * cos_terms).sum(dim=0)
        # C shape: (N, N)

        return C

    # -- Forward pass -------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,           # (B, N, d_model)
        H: Optional[torch.Tensor] = None,    # (d_cog, d_cog) Hermitian
        psi: Optional[torch.Tensor] = None,  # (d_cog,) complex
        lambda_gate: float = 0.3,  # bias strength
        dt: float = 0.025,         # cognitive time step
        mask: Optional[torch.Tensor] = None,  # (B, 1, 1, N) causal mask
        return_attn: bool = False,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Forward pass with optional H-QKV coherence bias.

        Parameters
        ----------
        x : torch.Tensor
            Input tensor (batch, seq_len, d_model).
        H : torch.Tensor, optional
            Hamiltonian matrix (d_cog, d_cog).  If None, standard attention.
        psi : torch.Tensor, optional
            Cognitive state (d_cog,).  If None, uniform distribution.
        lambda_gate : float
            Coherence bias strength.  0 = standard attention.
        dt : float
            Cognitive time step.
        mask : torch.Tensor, optional
            Causal/attention mask.
        return_attn : bool
            If True, return raw attention weights.

        Returns
        -------
        (output, attention_weights)
            output: (B, N, d_model)
            attention_weights: (B, n_heads, N, N) or None
        """
        B, N, D = x.shape

        # Standard QKV projections
        Q = self.W_q(x).view(B, N, self.n_heads, self.d_head).transpose(1, 2)
        K = self.W_k(x).view(B, N, self.n_heads, self.d_head).transpose(1, 2)
        V = self.W_v(x).view(B, N, self.n_heads, self.d_head).transpose(1, 2)

        # Standard attention scores
        scale = 1.0 / math.sqrt(self.d_head)
        scores = (Q @ K.transpose(-2, -1)) * scale  # (B, n_heads, N, N)

        # H-QKV coherence bias
        if self.use_bias and H is not None and lambda_gate != 0.0:
            # Per-head cognitive projection: weight Q by W_cog
            # W_cog: (n_heads, d_cog, d_head)
            # For each head h: proj_h = W_cog[h] @ Q[h] → (B, N, d_cog)
            # This projects Q into cognitive space per head
            q_proj = torch.einsum(
                'hcd,bhnd->bhnc', self.W_cog, Q
            )  # (B, n_heads, N, d_cog)

            # Compute per-head cognitive state (aggregate across batch and head)
            # Use mean projection as effective cognitive feature
            psi_eff = q_proj.mean(dim=(0, 1))  # (N, d_cog)
            # Average over sequence to get single cognitive state
            psi_state = psi_eff.mean(dim=0)  # (d_cog,)

            # Use provided psi if given, otherwise infer from input
            if psi is None:
                psi_norm = psi_state / (psi_state.norm() + 1e-10)
                psi_cog = psi_norm
            else:
                psi_cog = psi.to(x.device)

            # This needs to be H from the quantum engine
            # Fall back to identity-like if not provided
            if H is None:
                H_cog = torch.eye(self.d_cog, device=x.device, dtype=torch.complex64)
            else:
                H_cog = H.to(x.device)

            # Compute coherence bias matrix
            C = self.compute_coherence_bias(H_cog, psi_cog, N, dt, x.device)

            # Apply bias to each head's scores
            scores = scores + lambda_gate * C.unsqueeze(0).unsqueeze(0)

        # Mask
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))

        # Softmax + value
        attn_weights = F.softmax(scores, dim=-1)
        out = attn_weights @ V  # (B, n_heads, N, d_head)

        # Concatenate heads
        out = out.transpose(1, 2).contiguous().view(B, N, D)
        out = self.W_o(out)

        if return_attn:
            return out, attn_weights
        return out, None


# ---------------------------------------------------------------------------
# Diagnostic: compare standard vs H-QKV attention
# ---------------------------------------------------------------------------

def compare_attention(
    model: HQKVAttention,
    x: torch.Tensor,
    H: torch.Tensor,
    psi: torch.Tensor,
    lambda_gate: float,
    mask: Optional[torch.Tensor] = None,
) -> dict:
    """Compare standard vs H-QKV attention outputs.

    Returns a dict with:
      - 'standard': attention weights without bias
      - 'hqkv': attention weights with bias
      - 'bias_matrix': the coherence bias C
      - 'diff': absolute difference
      - 'entropy_std': entropy of standard attention distribution
      - 'entropy_hqkv': entropy of H-QKV attention distribution
    """
    device = x.device

    # Standard
    _, attn_std = model.forward(
        x, H=None, psi=None, lambda_gate=0.0,
        mask=mask, return_attn=True,
    )

    # H-QKV
    _, attn_hqkv = model.forward(
        x, H=H, psi=psi, lambda_gate=lambda_gate,
        mask=mask, return_attn=True,
    )

    # Coherence bias
    with torch.no_grad():
        C = model.compute_coherence_bias(H, psi, x.shape[1], device=device)

    # Entropy of attention distributions
    def _entropy(attn):
        p = attn.clamp(min=1e-10)
        return -(p * p.log()).sum(dim=-1).mean().item()

    return {
        'standard': attn_std,
        'hqkv': attn_hqkv,
        'bias_matrix': C,
        'diff': (attn_hqkv - attn_std).abs().mean().item(),
        'entropy_std': _entropy(attn_std),
        'entropy_hqkv': _entropy(attn_hqkv),
    }
