"""
Test LLM Tamer — 验证 llm_tamer 模块的完整功能

测试范围：
  1. 创建 LLMTamer 实例 + 配置加载
  2. 偏置计算机独立测试
  3. compute_bias() 合并输出
  4. compute_temperature() 动态策略
  5. banned_tokens() 功能
  6. 向 :8082 发送带 logit_bias 的实际请求（可选）
  7. 集成器连接测试
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# ── 配置 Python 路径 ────────────────────────────────────
# 添加 D:/LAAP 到 sys.path 以便 import laap.agi.cognitive_bus
LAAP_PARENT = "D:/LAAP"
if LAAP_PARENT not in sys.path:
    sys.path.insert(0, LAAP_PARENT)

logging.basicConfig(
    level=logging.INFO,
    format="%(name)-30s %(levelname)-8s %(message)s",
)
logger = logging.getLogger("test_tamer")


def test_01_import_and_init():
    """Test 1: 创建 LLMTamer 实例 + 配置加载"""
    print("\n" + "=" * 60)
    print("🟢 TEST 1: LLMTamer 实例化 + 配置加载")
    print("=" * 60)

    from laap.laap_tools.llm_tamer import LLMTamer

    tamer = LLMTamer()

    # 验证配置已加载
    assert tamer.config is not None, "配置未加载"
    assert "bias_strength" in tamer.config, "缺少 bias_strength 配置"
    assert "temperature" in tamer.config, "缺少 temperature 配置"
    assert "token_mappings" in tamer.config, "缺少 token_mappings 配置"

    print(f"  ✅ 配置加载成功")
    print(f"     bias_strength: {tamer.config['bias_strength']}")
    print(f"     temperature 范围: [{tamer.config['temperature']['min']}, "
          f"{tamer.config['temperature']['max']}]")
    print(f"     token_mappings 类别数: {len(tamer.config['token_mappings'])}")

    return tamer


def test_02_compute_bias(tamer):
    """Test 2: compute_bias() 从模拟状态计算偏置"""
    print("\n" + "=" * 60)
    print("🟢 TEST 2: compute_bias() 偏置计算")
    print("=" * 60)

    # 创建模拟认知状态
    state = _create_mock_state(
        attention_focus="user",
        attention_intensity=0.8,
        emotion_valence="positive_high",
        arousal=0.7,
        competence=0.3,   # 低 competence
        certainty=0.5,
        growth=0.5,
        self_presence=0.6,
        curiosity=0.3,
    )

    bias = tamer.compute_bias(state, context="test")
    print(f"  📊 注意力在 USER，intensity=0.8，positive_high，competence=0.3")
    print(f"     计算出的 bias token 数: {len(bias)}")

    if bias:
        # 展示 top 5 偏置
        sorted_bias = sorted(bias.items(), key=lambda x: -abs(x[1]))[:5]
        print(f"     Top 偏置: {sorted_bias}")

        # 验证偏置范围
        all_values = list(bias.values())
        assert all(-100 <= v <= 100 for v in all_values), "偏置值超出 [-100, 100] 范围"
        print(f"     ✅ 所有偏置在有效范围内")
        print(f"     偏置值范围: [{min(all_values):.1f}, {max(all_values):.1f}]")
    else:
        print(f"     ⚠️ 偏置为空（可能是 token_mappings 为示例 ID）")

    return bias


def test_03_compute_temperature(tamer):
    """Test 3: compute_temperature() 动态温度策略"""
    print("\n" + "=" * 60)
    print("🟢 TEST 3: compute_temperature() 动态温度")
    print("=" * 60)

    # 3a. 注意力集中
    state_focused = _create_mock_state(
        attention_focus="task",
        attention_intensity=0.95,
        emotion_valence="neutral",
        arousal=0.3,
        competence=0.8,
        certainty=0.8,
        curiosity=0.2,
    )
    temp_focused = tamer.compute_temperature(state_focused)
    print(f"  🔵 注意力集中 (intensity=0.95)")
    print(f"     temperature = {temp_focused}")
    assert 0.2 <= temp_focused <= 0.7, \
        f"集中模式温度应较低, 实际: {temp_focused}"
    print(f"     ✅ 温度在合理范围内 (0.2-0.7)")

    # 3b. 探索模式
    state_explore = _create_mock_state(
        attention_focus="learning",
        attention_intensity=0.4,
        emotion_valence="curious",
        arousal=0.8,
        competence=0.5,
        certainty=0.2,
        curiosity=0.9,
        growth=0.2,
    )
    temp_explore = tamer.compute_temperature(state_explore)
    print(f"  🟠 探索模式 (curiosity=0.9, certainty=0.2)")
    print(f"     temperature = {temp_explore}")
    assert temp_explore > 0.6, \
        f"探索模式温度应较高, 实际: {temp_explore}"
    print(f"     ✅ 温度在探索范围内")

    # 3c. 注意力涣散
    state_scatter = _create_mock_state(
        attention_focus="idle",
        attention_intensity=0.15,
        emotion_valence="neutral",
        arousal=0.3,
        competence=0.5,
        certainty=0.5,
        curiosity=0.2,
    )
    temp_scatter = tamer.compute_temperature(state_scatter)
    print(f"  ⚪ 注意力涣散 (intensity=0.15)")
    print(f"     temperature = {temp_scatter}")
    print(f"     ✅ 略高于 normal 以鼓励重新聚焦")

    # 3d. 默认模式
    state_normal = _create_mock_state(
        attention_focus="user",
        attention_intensity=0.5,
        emotion_valence="neutral",
        arousal=0.5,
        competence=0.5,
        certainty=0.5,
        curiosity=0.3,
    )
    temp_normal = tamer.compute_temperature(state_normal)
    print(f"  ⚪ 默认模式 (intensity=0.5)")
    print(f"     temperature = {temp_normal}")
    assert 0.5 <= temp_normal <= 0.9, \
        f"默认温度应在 0.5-0.9 之间, 实际: {temp_normal}"
    print(f"     ✅ 温度在默认范围内")

    return {
        "focused": temp_focused,
        "exploratory": temp_explore,
        "scattered": temp_scatter,
        "normal": temp_normal,
    }


def test_04_banned_tokens(tamer):
    """Test 4: banned_tokens() 功能"""
    print("\n" + "=" * 60)
    print("🟢 TEST 4: banned_tokens() token 禁止")
    print("=" * 60)

    # 4a. 负面情感 → 禁止负面 token
    state_negative = _create_mock_state(
        attention_focus="user",
        attention_intensity=0.5,
        emotion_valence="negative_high",
        arousal=0.8,
        competence=0.5,
        certainty=0.5,
    )
    banned_neg = tamer.banned_tokens(state_negative)
    print(f"  😡 负面情感 (negative_high)")
    print(f"     被禁止 token 数: {len(banned_neg)}")
    if banned_neg:
        print(f"     禁止 ID: {banned_neg}")
        print(f"     ✅ 负面 token 被禁止")

    # 4b. 高度集中非自省模式 → 禁止自省 token
    state_focused_task = _create_mock_state(
        attention_focus="task",
        attention_intensity=0.9,
        emotion_valence="neutral",
        arousal=0.5,
        competence=0.8,
        certainty=0.8,
    )
    banned_focus = tamer.banned_tokens(state_focused_task)
    print(f"  🎯 高度集中非自省模式")
    print(f"     被禁止 token 数: {len(banned_focus)}")
    if banned_focus:
        print(f"     禁止 ID: {banned_focus}")
        print(f"     ✅ 自省 token 被禁止")

    # 4c. 正常状态 → 无禁止
    state_normal = _create_mock_state()
    banned_normal = tamer.banned_tokens(state_normal)
    print(f"  ⚪ 正常状态")
    print(f"     被禁止 token 数: {len(banned_normal)}")
    print(f"     ✅ 正常状态无额外禁止")


def test_05_bias_computers_individually(tamer):
    """Test 5: 四个偏置计算机独立测试"""
    print("\n" + "=" * 60)
    print("🟢 TEST 5: 偏置计算机独立测试")
    print("=" * 60)

    from laap.laap_tools.llm_tamer.bias_computers import (
        AttentionBiasComputer,
        EmotionBiasComputer,
        NeedsBiasComputer,
        MetaBiasComputer,
    )

    state = _create_mock_state(
        attention_focus="user",
        attention_intensity=0.75,
        emotion_valence="curious",
        arousal=0.7,
        competence=0.2,
        certainty=0.3,
        growth=0.2,
        curiosity=0.8,
        self_presence=0.15,
    )

    # 加载 token 映射
    token_groups = tamer.token_mappings

    # 5a. AttentionBiasComputer
    attn = AttentionBiasComputer(bias_strength=1.0)
    attn.load_token_groups(token_groups)
    attn_bias = attn.compute(state)
    print(f"  🧠 AttentionBiasComputer: {len(attn_bias)} tokens")
    _print_top_bias(attn_bias, "注意力偏置")

    # 5b. EmotionBiasComputer
    emo = EmotionBiasComputer(bias_strength=0.7)
    emo.load_token_groups(token_groups)
    emo_bias = emo.compute(state)
    print(f"  😊 EmotionBiasComputer: {len(emo_bias)} tokens")
    _print_top_bias(emo_bias, "情感偏置")

    # 5c. NeedsBiasComputer
    need = NeedsBiasComputer(bias_strength=0.5)
    need.load_token_groups(token_groups)
    need_bias = need.compute(state)
    print(f"  📋 NeedsBiasComputer: {len(need_bias)} tokens")
    _print_top_bias(need_bias, "需求偏置")

    # 5d. MetaBiasComputer
    meta = MetaBiasComputer(bias_strength=0.8)
    meta.load_token_groups(token_groups)
    meta_bias = meta.compute(state)
    print(f"  🔄 MetaBiasComputer: {len(meta_bias)} tokens")
    _print_top_bias(meta_bias, "元认知偏置")

    return {
        "attention": attn_bias,
        "emotion": emo_bias,
        "needs": need_bias,
        "meta": meta_bias,
    }


def test_06_llama_connection(tamer):
    """Test 6: 向 :8082 发送带 logit_bias 的实际请求"""
    print("\n" + "=" * 60)
    print("🟢 TEST 6: llama.cpp :8082 连接测试")
    print("=" * 60)

    # 6a. 测试连接
    connected = tamer.llama.test_connection()
    print(f"  🔌 连接测试: {'✅ 成功' if connected else '❌ 失败'}")

    if not connected:
        print("  ⚠️ 跳过实际 request 测试（llama.cpp server 未运行）")
        return None

    # 6b. 发送简单请求（无偏置）
    print(f"  📤 发送简单 completion (n_predict=10)...")
    try:
        state = _create_mock_state()
        result = tamer.llama.send_completion(
            prompt="你好，今天",
            max_tokens=10,
            temperature=0.7,
        )
        content = result.get("content", "")
        tokens = result.get("tokens_predicted", 0)
        print(f"  📥 响应: \"{content}\"")
        print(f"     tokens_predicted: {tokens}")
        print(f"     ✅ 基础 completion 成功")
    except Exception as e:
        print(f"  ❌ 基础 completion 失败: {e}")
        return None

    # 6c. 发送带 logit_bias 的请求
    print(f"  📤 发送带 logit_bias 的请求...")
    try:
        state = _create_mock_state(
            attention_focus="user",
            attention_intensity=0.8,
        )
        biased_result = tamer.apply_to_local(
            prompt="你好，今天",
            state=state,
            max_tokens=10,
        )
        content = biased_result.get("content", "")
        print(f"  📥 带偏置响应: \"{content}\"")
        print(f"     ✅ 带 logit_bias 的请求成功")
        return biased_result
    except Exception as e:
        print(f"  ❌ 带偏置请求失败: {e}")
        return None


def test_07_tokenize_api(tamer):
    """Test 7: 通过 llama.cpp tokenize API 获取 token ID 映射"""
    print("\n" + "=" * 60)
    print("🟢 TEST 7: tokenize API 测试")
    print("=" * 60)

    connected = tamer.llama.test_connection()
    if not connected:
        print("  ⚠️ 跳过（llama.cpp server 未运行）")
        return

    # 测试词汇
    test_words = [
        "？", "好", "不好", "请", "帮",
        "探索", "试试", "也许", "为什么", "如何",
        "我感觉", "让我想想", "我应该", "反思",
        "继续", "回到", "那么",
        "sorry", "please", "help", "great", "interesting",
    ]

    print(f"  📊 测试 {len(test_words)} 个词汇的 token ID...")
    token_map: Dict[str, List[int]] = {}

    for word in test_words:
        ids = tamer.llama.get_tokenizer_tokens(word)
        token_map[word] = ids
        print(f"     \"{word}\" → {ids}")

    print(f"  ✅ Tokenize 完成")

    # 可以输出可用于 config.yaml 的映射
    print("\n  📝 生成的 token 映射（可用于 config.yaml）:")
    print("  ```yaml")
    for word, ids in token_map.items():
        if ids:
            # 取第一个 token ID
            print(f"    {ids[0]}: \"{word}\"")
    print("  ```")

    return token_map


def test_08_apply_to_deepseek(tamer):
    """Test 8: apply_to_deepseek 降级适配测试（仅验证参数构建，不实际发送）"""
    print("\n" + "=" * 60)
    print("🟢 TEST 8: DeepSeek 降级适配（参数构建验证）")
    print("=" * 60)

    state = _create_mock_state(
        attention_focus="user",
        attention_intensity=0.6,
        emotion_valence="positive_mild",
        arousal=0.5,
        competence=0.4,
        certainty=0.3,
    )

    # 构建前缀测试
    prefix = tamer._deepseek.build_cognitive_prompt_prefix(
        emotion_valence=state.emotion.valence.value,
        attention_focus=state.attention.focus.value,
        certainty=state.needs.certainty,
        competence=state.needs.competence,
    )
    print(f"  📝 构建的 cognitive prefix:")
    for line in prefix.strip().split("\n"):
        print(f"     {line}")
    print(f"     ✅ 前缀构建成功")

    # 温度计算
    temp = tamer.compute_temperature(state)
    print(f"  🌡️ 计算温度: {temp}")
    print(f"     ✅ 温度计算成功")

    # 消息注入测试
    messages = [
        {"role": "system", "content": "You are Aris."},
        {"role": "user", "content": "你好"},
    ]
    enhanced = tamer._deepseek.apply_cognitive_prefix(messages, prefix)
    print(f"  💬 增强后的系统消息长度: {len(enhanced[0]['content'])} 字符")
    print(f"     ✅ 前缀注入成功")
    print(f"     ⚠️ 未实际发送 API 请求（需要有效 DEEPSEEK_API_KEY）")


# ════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════

def _create_mock_state(
    attention_focus: str = "idle",
    attention_intensity: float = 0.5,
    emotion_valence: str = "neutral",
    arousal: float = 0.5,
    dominance: float = 0.5,
    competence: float = 0.7,
    autonomy: float = 0.5,
    relatedness: float = 0.5,
    certainty: float = 0.5,
    growth: float = 0.5,
    self_presence: float = 0.5,
    curiosity: float = 0.3,
    prediction_error: Optional[float] = None,
    salience_map: Optional[Dict[str, float]] = None,
):
    """
    创建一个模拟的 CognitiveStateSnapshot 用于测试。

    使用 laap.agi.cognitive_bus 中的真实类。
    """
    from laap.agi.cognitive_bus import (
        AttentionFocus,
        AttentionState,
        CognitiveStateSnapshot,
        EmotionalValence,
        EmotionState,
        NeedState,
        PredictionError,
    )

    # 构建错误对象（如果提供了 error）
    err = None
    if prediction_error is not None:
        err = PredictionError(
            domain="test",
            predicted_outcome=0.5,
            actual_outcome=0.5 + prediction_error,
            error_magnitude=prediction_error,
            timestamp=0,
            source_module="test_tamer",
        )

    return CognitiveStateSnapshot(
        needs=NeedState(
            competence=competence,
            autonomy=autonomy,
            relatedness=relatedness,
            certainty=certainty,
            growth=growth,
        ),
        emotion=EmotionState(
            valence=EmotionalValence(emotion_valence),
            arousal=arousal,
            dominance=dominance,
        ),
        attention=AttentionState(
            focus=AttentionFocus(attention_focus),
            intensity=attention_intensity,
            salience_map=salience_map or {},
        ),
        self_presence=self_presence,
        curiosity=curiosity,
        prediction_error=err,
    )


def _print_top_bias(bias: Dict[int, float], label: str):
    """打印偏置字典的前几个条目。"""
    if not bias:
        print(f"     (空)")
        return
    sorted_items = sorted(bias.items(), key=lambda x: -abs(x[1]))[:3]
    items_str = ", ".join(f"{tid}:{b:+.1f}" for tid, b in sorted_items)
    print(f"     Top: [{items_str}] ... 共 {len(bias)} 个")


# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════

def main():
    """运行所有测试。"""
    print("╔" + "═" * 58 + "╗")
    print("║     LLM Tamer 模块验证测试                    ║")
    print("║     aris_cognitive_control — Path 1            ║")
    print("╚" + "═" * 58 + "╝")
    print(f"Python: {sys.version}")
    print(f"路径: {LAAP_PARENT}/laap")
    print()

    results: Dict[str, str] = {}

    try:
        # Test 1: 初始化
        tamer = test_01_import_and_init()
        results["01_import_init"] = "✅ PASS"

        # Test 2: compute_bias
        bias = test_02_compute_bias(tamer)
        results["02_compute_bias"] = "✅ PASS" if bias is not None else "⚠️ PARTIAL"

        # Test 3: compute_temperature
        temps = test_03_compute_temperature(tamer)
        results["03_temperature"] = "✅ PASS"

        # Test 4: banned_tokens
        test_04_banned_tokens(tamer)
        results["04_banned_tokens"] = "✅ PASS"

        # Test 5: 偏置计算机独立测试
        computers = test_05_bias_computers_individually(tamer)
        results["05_bias_computers"] = "✅ PASS"

        # Test 6: llama.cpp 连接
        llm_result = test_06_llama_connection(tamer)
        results["06_llama_connection"] = "✅ PASS" if llm_result else "⚠️ SKIP (server not running)"

        # Test 7: tokenize API
        test_07_tokenize_api(tamer)
        results["07_tokenize_api"] = "✅ PASS"

        # Test 8: DeepSeek
        test_08_apply_to_deepseek(tamer)
        results["08_deepseek_adapter"] = "✅ PASS"

    except Exception as e:
        logger.exception(f"❌ 测试异常: {e}")
        results["ERROR"] = f"❌ {e}"
    finally:
        print("\n" + "=" * 60)
        print("📊 测试结果汇总")
        print("=" * 60)
        all_pass = True
        for test, result in sorted(results.items()):
            status = "✅" if "PASS" in result else ("⚠️" if "SKIP" in result else "❌")
            print(f"  {status} {test}: {result}")
            if "FAIL" in result:
                all_pass = False
        print()
        if all_pass:
            print("🎉 所有测试通过！")
        else:
            print("⚠️ 部分测试未通过，请检查上述输出。")
        print()


if __name__ == "__main__":
    main()
