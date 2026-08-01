"""文本 → 复相位向量的编码器。

PoC 阶段使用确定性哈希 + 伪随机投影，保证：
- 无需外部模型依赖
- 同文本得到同向量
- 向量模长归一化，可直接用于 CRM 亲和度计算

后续可无缝替换为 sentence-transformers 或 LAAP 自有编码器。
"""

from __future__ import annotations

import hashlib
from typing import Iterable

import numpy as np


class TextEncoder:
    """将文本编码为固定维度的复相位向量。"""

    def __init__(self, dim: int = 64, seed: int = 2026):
        if dim <= 0 or dim % 2 != 0:
            raise ValueError("dim 必须是正偶数")
        self.dim = dim
        self.seed = seed
        # 全局投影矩阵：实部/虚部分别用高斯随机矩阵投影
        rng = np.random.default_rng(seed)
        self._real_proj = rng.standard_normal((dim, dim))
        self._imag_proj = rng.standard_normal((dim, dim))

    def _ngram_features(self, text: str) -> np.ndarray:
        """用字符 n-gram 构造语义特征向量，使相似文本共享特征。"""
        text = text.strip().lower()
        if not text:
            return np.zeros(self.dim, dtype=np.float32)

        features = np.zeros(self.dim, dtype=np.float32)
        # 字符级 n-gram（2-5 gram）混合，覆盖局部语义与拼写
        for n in (2, 3, 4):
            for i in range(len(text) - n + 1):
                gram = text[i : i + n]
                h = int(hashlib.sha256(gram.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dim
                # 用 hash 高位决定符号，使不同 gram 可能互相抵消而非单向累加
                sign = 1.0 if (h >> 32) & 1 else -1.0
                features[idx] += sign * (1.0 / n)  # 长 gram 权重略低，避免冲突主导
        # 单字也参与，保证短文本有信号
        for ch in text:
            h = int(hashlib.sha256(ch.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 32) & 1 else -1.0
            features[idx] += sign * 0.5
        return features

    def encode(self, text: str) -> np.ndarray:
        """将单条文本编码为归一化复向量。"""
        text = text.strip()
        if not text:
            return np.zeros(self.dim, dtype=np.complex64)

        # 1. 用 n-gram 构造语义特征
        features = self._ngram_features(text)
        if np.linalg.norm(features) == 0:
            return np.zeros(self.dim, dtype=np.complex64)

        # 2. 线性投影到实部和虚部，形成复向量
        real = self._real_proj @ features
        imag = self._imag_proj @ features
        vec = real + 1j * imag

        # 3. 归一化（避免模长爆炸）
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.complex64)

    def encode_batch(self, texts: Iterable[str]) -> list[np.ndarray]:
        """批量编码。"""
        return [self.encode(t) for t in texts]

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算两个复向量的实部余弦相似度（调试/测试用）。"""
        a = np.asarray(a, dtype=complex).ravel()
        b = np.asarray(b, dtype=complex).ravel()
        if a.size != self.dim or b.size != self.dim:
            raise ValueError("向量维度与 encoder.dim 不符")
        return float(np.vdot(a, b).real)
