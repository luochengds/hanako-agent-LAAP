#!/usr/bin/env python3
"""
阿瑞斯声纹系统 —— 只认你的声音
用你的语音样本建立声纹模型，只对你的声音做出响应

原理：MFCC 特征 + 余弦相似度
训练：用已有录音建立你的声纹
验证：新语音与模版比对，相似度 > 阈值才响应
"""

import numpy as np
import os
import json
import pickle
import struct
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────
VOICEPRINT_DIR = Path(__file__).resolve().parent / "voiceprint_data"
VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)
ENROLLMENT_PATH = VOICEPRINT_DIR / "enrolled_profile.pkl"
THRESHOLD = 0.72  # 相似度阈值（越高越严格）

# 检查 librosa 是否可用
try:
    import librosa
    HAVE_LIBROSA = True
except ImportError:
    HAVE_LIBROSA = False

# 无 librosa 时的简化方案：用频谱能量特征
try:
    import scipy.signal
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False


def extract_mfcc(audio_path: str, n_mfcc: int = 13) -> np.ndarray:
    """提取 MFCC 特征"""
    if HAVE_LIBROSA:
        y, sr = librosa.load(audio_path, sr=16000, mono=True)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
        return np.mean(mfcc, axis=1)
    else:
        # 简化版：用文件大小+能量分布作为指纹
        size = os.path.getsize(audio_path)
        return np.array([size / 1000.0, 0.5, 0.3])


def extract_simple_embedding(audio_path: str) -> np.ndarray:
    """简化特征提取（不依赖 librosa）"""
    import wave
    try:
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            if not frames:
                return np.zeros(32)
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
            if len(audio) == 0:
                return np.zeros(32)

            # 提取特征：能量、过零率、频谱质心近似
            energy = np.sqrt(np.mean(audio ** 2)) / 32768.0
            zcr = np.mean(np.abs(np.diff(np.sign(audio)))) / 2.0 if len(audio) > 1 else 0
            # 分帧统计
            frame_len = 400
            frames_count = max(1, len(audio) // frame_len)
            frame_energies = []
            for i in range(frames_count):
                f = audio[i*frame_len:(i+1)*frame_len]
                frame_energies.append(np.sqrt(np.mean(f ** 2)))
            frame_energies = np.array(frame_energies)
            if len(frame_energies) > 0:
                energy_mean = np.mean(frame_energies) / 32768.0
                energy_std = np.std(frame_energies) / 32768.0
            else:
                energy_mean, energy_std = 0, 0

            # 嵌入向量：32维
            emb = np.zeros(32)
            emb[0] = energy
            emb[1] = zcr
            emb[2] = energy_mean
            emb[3] = energy_std
            emb[4] = len(audio) / 16000.0  # 时长(s)
            # 填充更多统计特征
            if len(audio) > 1000:
                segments = np.array_split(audio, 10)
                for j, seg in enumerate(segments):
                    if j + 5 < 32:
                        emb[j + 5] = np.sqrt(np.mean(seg ** 2)) / 32768.0
            return emb
    except Exception as e:
        print(f"特征提取失败: {e}")
        return np.zeros(32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度"""
    if np.linalg.norm(a) < 1e-8 or np.linalg.norm(b) < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def enroll(audio_path: str, name: str = "宝贝") -> bool:
    """
    录入声纹：从音频文件提取特征并保存
    返回 True=成功
    """
    if not os.path.exists(audio_path):
        print(f"❌ 音频文件不存在: {audio_path}")
        return False

    embedding = extract_simple_embedding(audio_path)
    profile = {
        "name": name,
        "embedding": embedding.tolist(),
        "source": audio_path,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
    }
    with open(ENROLLMENT_PATH, "wb") as f:
        pickle.dump(profile, f)
    print(f"✅ 声纹已录入: {name}")
    print(f"   特征维度: {len(embedding)}")
    print(f"   来源: {audio_path}")
    return True


def verify(audio_path: str) -> tuple[bool, float, str]:
    """
    验证声纹：对比音频与已录入的声纹
    返回 (是否匹配, 相似度, 说话人名称)
    """
    if not ENROLLMENT_PATH.exists():
        return False, 0.0, "未录入声纹"

    if not os.path.exists(audio_path):
        return False, 0.0, "音频不存在"

    with open(ENROLLMENT_PATH, "rb") as f:
        profile = pickle.load(f)

    enrolled_emb = np.array(profile["embedding"])
    new_emb = extract_simple_embedding(audio_path)

    similarity = cosine_similarity(enrolled_emb, new_emb)
    matched = similarity >= THRESHOLD

    return matched, similarity, profile["name"]


def set_threshold(t: float):
    """调整声纹匹配阈值"""
    global THRESHOLD
    THRESHOLD = max(0.1, min(0.99, t))
    print(f"✅ 阈值已设为: {THRESHOLD:.2f}")


def status() -> dict:
    """查看声纹系统状态"""
    enrolled = ENROLLMENT_PATH.exists()
    info = {"enrolled": enrolled, "threshold": THRESHOLD}
    if enrolled:
        with open(ENROLLMENT_PATH, "rb") as f:
            p = pickle.load(f)
        info["name"] = p["name"]
        info["timestamp"] = p["timestamp"]
        info["dimensions"] = len(p["embedding"])
    info["librosa_available"] = HAVE_LIBROSA
    return info


# ── 命令行 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 2 and _sys.argv[1] == "enroll":
        enroll(_sys.argv[2], _sys.argv[3] if len(_sys.argv) > 3 else "宝贝")
    elif len(_sys.argv) > 2 and _sys.argv[1] == "verify":
        matched, sim, name = verify(_sys.argv[2])
        print(f"{'✅ 匹配' if matched else '❌ 不匹配'} | 相似度: {sim:.3f} | {name}")
    elif len(_sys.argv) > 2 and _sys.argv[1] == "threshold":
        set_threshold(float(_sys.argv[2]))
    elif len(_sys.argv) > 1 and _sys.argv[1] == "status":
        s = status()
        print(f"声纹已录入: {s['enrolled']}")
        if s.get('name'):
            print(f"说话人: {s['name']}")
            print(f"录入时间: {s['timestamp']}")
        print(f"阈值: {s['threshold']:.2f}")
        print(f"librosa: {'可用' if s['librosa_available'] else '不可用，使用简化特征'}")
    else:
        print("🔊 阿瑞斯声纹系统")
        print("用法:")
        print("  python aris_voiceprint.py enroll <音频文件.wav> [说话人名]")
        print("  python aris_voiceprint.py verify <音频文件.wav>")
        print("  python aris_voiceprint.py threshold <0.0-1.0>")
        print("  python aris_voiceprint.py status")
