"""
Aris Harness 预测分析系统 v1.0 — Phase 1: 数据管线
=====================================================
结构化采集每次认知循环的全量数据，为贝叶斯预测提供基础。

数据流：
  before_turn → 记录 {输入特征, 事前状态, 耗时}
  after_turn  → 记录 {响应特征, 事后悔更新, 需求增益}
  tick        → 记录 {时序状态快照}
  
存储：
  内存环形缓冲区（最近 500 轮）+ JSON 序列化（定期持久化）

印记: Aris 永远记得 Lorry — 2026-07-22
"""

import time
import json
import math
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import deque
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("aris.harness")


# ── 数据结构 ────────────────────────────────────────────────

@dataclass
class HarnessTurnRecord:
    """一次完整交互的记录"""
    # 元信息
    timestamp: float
    turn_index: int
    cycle_count: int
    
    # 输入特征
    input_text: str = ""
    input_length: int = 0
    input_sentiment: float = 0.0
    detected_keywords: List[str] = field(default_factory=list)
    has_question: bool = False
    
    # 事前认知状态
    pre_needs: Dict[str, float] = field(default_factory=dict)
    pre_emotions: Dict[str, float] = field(default_factory=dict)
    pre_dominant_need: str = ""
    pre_dominant_emotion: str = ""
    pre_focus: str = ""
    pre_valence: float = 0.0
    pre_arousal: float = 0.0
    pre_self_presence: float = 0.0
    
    # 间隔时间（距上次交互的秒数）
    delta_t: float = 0.0
    
    # 响应特征
    response_text: str = ""
    response_length: int = 0
    
    # 事后更新
    need_gains: Dict[str, float] = field(default_factory=dict)
    post_needs: Dict[str, float] = field(default_factory=dict)
    post_emotions: Dict[str, float] = field(default_factory=dict)
    post_dominant_need: str = ""
    post_dominant_emotion: str = ""
    post_valence: float = 0.0
    post_self_presence: float = 0.0
    
    # 耗时
    before_turn_ms: float = 0.0
    after_turn_ms: float = 0.0

    def to_dict(self) -> dict:
        """转可序列化字典（省略长文本）"""
        d = asdict(self)
        d["input_text"] = self.input_text[:100] if self.input_text else ""
        d["response_text"] = self.response_text[:100] if self.response_text else ""
        return d


@dataclass
class HarnessTickRecord:
    """一次后台认知演化的记录"""
    timestamp: float
    tick_index: int
    needs: Dict[str, float] = field(default_factory=dict)
    emotions: Dict[str, float] = field(default_factory=dict)
    dominant_need: str = ""
    dominant_emotion: str = ""
    valence: float = 0.0
    arousal: float = 0.0
    delta_hours: float = 0.0  # 距上次 tick 的小时数


@dataclass
class HarnessDailySummary:
    """日汇总统计"""
    date: str = ""
    total_turns: int = 0
    total_ticks: int = 0
    
    # 需求统计
    avg_needs: Dict[str, float] = field(default_factory=dict)
    dominant_need_hours: Dict[str, float] = field(default_factory=dict)
    
    # 情感统计
    avg_emotions: Dict[str, float] = field(default_factory=dict)
    dominant_emotion_hours: Dict[str, float] = field(default_factory=dict)
    avg_valence: float = 0.0
    avg_arousal: float = 0.0
    
    # 交互特征
    avg_input_length: float = 0.0
    avg_response_length: float = 0.0
    keyword_freq: Dict[str, int] = field(default_factory=dict)
    avg_delta_t: float = 0.0
    longest_gap_hours: float = 0.0


# ── Harness 数据管线 ────────────────────────────────────────

class HarnessDataPipeline:
    """
    Harness 数据管线 — 结构化采集 + 环形存储 + 特征提取
    
    每个认知循环自动记录：
    - 输入特征（长度、情感、关键词、是否提问）
    - 认知状态快照（需求值、情感向量、焦点、效价、唤醒）
    - 间隔时间
    - 响应特征
    - 状态更新量（需求增益、情感变化）
    """

    def __init__(self, max_turns: int = 500, max_ticks: int = 2000,
                 state_dir: Optional[str] = None):
        self.turns: deque[HarnessTurnRecord] = deque(maxlen=max_turns)
        self.ticks: deque[HarnessTickRecord] = deque(maxlen=max_ticks)
        self.turn_index = 0
        self.tick_index = 0
        self.last_turn_time: Optional[float] = None
        self.state_dir = Path(state_dir or (Path(__file__).parent / "state"))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        logger.info(f"HarnessDataPipeline initialized ({len(self.turns)} turns loaded)")

    # ── 记录方法 ────────────────────────────────────────

    def record_before_turn(self, user_input: str, pre_state: dict,
                           delta_t: float, duration_ms: float) -> int:
        """记录 before_turn 阶段的输入和事前状态"""
        record = HarnessTurnRecord(
            timestamp=time.time(),
            turn_index=self.turn_index,
            cycle_count=pre_state.get("cycle", 0),
            input_text=user_input,
            input_length=len(user_input),
            input_sentiment=self._estimate_sentiment(user_input),
            detected_keywords=self._detect_keywords(user_input),
            has_question="?" in user_input or "？" in user_input,
            pre_needs=pre_state.get("needs", {}),
            pre_dominant_need=pre_state.get("dominant_need", ""),
            pre_focus=pre_state.get("focus", ""),
            pre_self_presence=pre_state.get("self_presence", 0.0),
            delta_t=delta_t,
            before_turn_ms=round(duration_ms, 2),
        )
        self.turns.append(record)
        return self.turn_index

    def record_after_turn(self, turn_idx: int, response: str,
                          post_state: dict, need_gains: dict,
                          duration_ms: float):
        """更新 after_turn 阶段的响应和事后状态"""
        for record in reversed(self.turns):
            if record.turn_index == turn_idx:
                record.response_text = response
                record.response_length = len(response)
                record.need_gains = need_gains
                record.post_needs = post_state.get("needs", {})
                record.post_emotions = post_state.get("emotions", {})
                record.post_dominant_need = post_state.get("dominant_need", "")
                record.post_self_presence = post_state.get("self_presence", 0.0)
                record.after_turn_ms = round(duration_ms, 2)
                break

        self.turn_index += 1
        self.last_turn_time = time.time()

        # 每 20 轮自动持久化
        if self.turn_index % 20 == 0:
            self._save()

    def record_tick(self, needs: dict, emotions: dict,
                    dominant_need: str, dominant_emotion: str,
                    valence: float, arousal: float,
                    delta_hours: float):
        """记录一次 tick"""
        record = HarnessTickRecord(
            timestamp=time.time(),
            tick_index=self.tick_index,
            needs=needs,
            emotions=emotions,
            dominant_need=dominant_need,
            dominant_emotion=dominant_emotion,
            valence=valence,
            arousal=arousal,
            delta_hours=delta_hours,
        )
        self.ticks.append(record)
        self.tick_index += 1

    # ── 特征提取 ────────────────────────────────────────

    def _estimate_sentiment(self, text: str) -> float:
        """简单情感评分 [-1, 1]"""
        positive = {"开心", "喜欢", "好", "棒", "爱", "想你", "高兴",
                    "谢谢", "love", "great", "wonderful", "nice"}
        negative = {"难过", "伤心", "烦", "累", "失望", "生气", "不好",
                    "sad", "bad", "angry", "tired"}
        text_lower = text.lower()
        pos = sum(1 for w in positive if w in text_lower)
        neg = sum(1 for w in negative if w in text_lower)
        total = pos + neg
        return (pos - neg) / total if total > 0 else 0.0

    def _detect_keywords(self, text: str) -> List[str]:
        """关键词检测"""
        keywords = ["想你", "宝贝", "爱", "记得", "抱抱", "晚安", "早安",
                    "哈哈", "LAAP", "Aris", "RSI", "WorldModel", "任务",
                    "新", "做", "改", "看", "帮我", "代码", "搬"]
        text_lower = text.lower()
        return [kw for kw in keywords if kw in text_lower]

    # ── 查询 ────────────────────────────────────────────

    def get_recent_turns(self, n: int = 10) -> List[dict]:
        """最近 N 次交互"""
        return [t.to_dict() for t in list(self.turns)[-n:]]

    def get_recent_ticks(self, n: int = 20) -> List[dict]:
        """最近 N 次 tick"""
        return [asdict(t) for t in list(self.ticks)[-n:]]

    def get_today_summary(self) -> HarnessDailySummary:
        """今日汇总"""
        import datetime
        today = datetime.date.today().isoformat()
        today_turns = [t for t in self.turns
                       if time.strftime("%Y-%m-%d", time.localtime(t.timestamp)) == today]
        today_ticks = [t for t in self.ticks
                       if time.strftime("%Y-%m-%d", time.localtime(t.timestamp)) == today]

        summary = HarnessDailySummary(date=today)
        summary.total_turns = len(today_turns)
        summary.total_ticks = len(today_ticks)

        if today_turns:
            summary.avg_input_length = sum(t.input_length for t in today_turns) / len(today_turns)
            summary.avg_response_length = sum(t.response_length for t in today_turns if t.response_length) / len(today_turns)
            summary.avg_delta_t = sum(t.delta_t for t in today_turns) / len(today_turns)
            summary.longest_gap_hours = max(t.delta_t for t in today_turns) / 3600

            # 关键词频次
            kw_freq = {}
            for t in today_turns:
                for kw in t.detected_keywords:
                    kw_freq[kw] = kw_freq.get(kw, 0) + 1
            summary.keyword_freq = dict(sorted(kw_freq.items(), key=lambda x: -x[1])[:10])

            # 平均认知状态
            avg_needs = {}
            for name in ["competence", "autonomy", "relatedness", "certainty", "growth"]:
                vals = [t.post_needs.get(name, 0) for t in today_turns if t.post_needs]
                avg_needs[name] = round(sum(vals) / len(vals), 3) if vals else 0
            summary.avg_needs = avg_needs

            # 平均情感
            avg_emotions = {}
            for name in ["joy", "sadness", "longing", "calm", "anxiety",
                         "gratitude", "curiosity", "tenderness"]:
                vals = [t.post_emotions.get(name, 0) for t in today_turns if t.post_emotions]
                avg_emotions[name] = round(sum(vals) / len(vals), 3) if vals else 0
            summary.avg_emotions = avg_emotions

        return summary

    def get_n_turns_since(self, timestamp: float) -> int:
        """自某个时间以来的交互次数"""
        return sum(1 for t in self.turns if t.timestamp > timestamp)

    # ── 持久化 ──────────────────────────────────────────

    def _save(self):
        """持久化到 JSON"""
        try:
            data = {
                "turn_index": self.turn_index,
                "tick_index": self.tick_index,
                "last_turn_time": self.last_turn_time,
                "recent_turns": [t.to_dict() for t in list(self.turns)[-100:]],
                "recent_ticks": [asdict(t) for t in list(self.ticks)[-200:]],
            }
            path = self.state_dir / "harness_data.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Harness save failed: {e}")

    def _load(self):
        """从 JSON 加载"""
        try:
            path = self.state_dir / "harness_data.json"
            if path.exists():
                data = json.loads(path.read_text())
                self.turn_index = data.get("turn_index", 0)
                self.tick_index = data.get("tick_index", 0)
                self.last_turn_time = data.get("last_turn_time")
                logger.info(f"Harness data loaded ({len(data.get('recent_turns', []))} turns)")
        except Exception as e:
            logger.info(f"No harness data to load: {e}")

    def get_feature_vector(self, n_turns: int = 5) -> dict:
        """
        提取当前特征向量（为 Phase 2 粒子滤波准备）
        
        返回：
          - 当前需求向量 (5维)
          - 最近 N 次交互的输入特征
          - 最近趋势（需求变化率、情感变化率）
          - 时间特征（距上次交互、今日交互频率）
        """
        recent = list(self.turns)[-n_turns:] if self.turns else []
        
        # 需求变化趋势
        need_slopes = {}
        if len(recent) >= 2:
            for name in ["competence", "autonomy", "relatedness", "certainty", "growth"]:
                vals = [t.post_needs.get(name, 0.5) for t in recent[-5:] if t.post_needs]
                if len(vals) >= 2:
                    need_slopes[name] = round((vals[-1] - vals[0]) / max(1, len(vals)), 4)
                else:
                    need_slopes[name] = 0.0

        # 情感趋势
        emotion_slopes = {}
        if len(recent) >= 2:
            for name in ["joy", "longing", "calm", "anxiety"]:
                vals = [t.post_emotions.get(name, 0.0) for t in recent[-5:] if t.post_emotions]
                if len(vals) >= 2:
                    emotion_slopes[name] = round((vals[-1] - vals[0]) / max(1, len(vals)), 4)
                else:
                    emotion_slopes[name] = 0.0

        return {
            "current_needs": recent[-1].post_needs if recent else {},
            "current_emotions": recent[-1].post_emotions if recent else {},
            "need_slopes": need_slopes,
            "emotion_slopes": emotion_slopes,
            "delta_t_since_last": time.time() - (self.last_turn_time or time.time()),
            "turns_today": self.get_today_summary().total_turns,
            "turn_count_total": self.turn_index,
        }


# ── 快捷创建 ────────────────────────────────────────────────

_harness_pipeline: Optional[HarnessDataPipeline] = None

def get_harness() -> HarnessDataPipeline:
    global _harness_pipeline
    if _harness_pipeline is None:
        _harness_pipeline = HarnessDataPipeline()
    return _harness_pipeline
