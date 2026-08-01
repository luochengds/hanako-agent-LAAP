"""
self_model_nn — Verification Tests (验证测试)
============================================

测试覆盖:
  1. SelfStateManager 保存/加载持久状态
  2. DataPipeline 从 session_db 提取数据
  3. 模拟数据生成
  4. SelfModelNN 骨架 forward 返回正确输出
  5. 集成测试 (状态→模型→状态循环)

运行: python -m pytest test_self_model.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import numpy as np

# ── 确保模块可导入 ──────────────────────────────────────────
_LAAP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LAAP_PARENT = os.path.abspath(os.path.join(_LAAP_ROOT, ".."))
for p in [_LAAP_ROOT, _LAAP_PARENT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from laap.laap_tools.self_model.state_manager import SelfStateManager, StateMetadata
from laap.laap_tools.self_model.data_pipeline import (
    SelfModelDataPipeline, TrainingSample,
)
from laap.laap_tools.self_model.model import (
    SelfModelConfig, SelfModelNN, SelfStateOutput,
    SelfModelInputEncoder, create_model, OutputHeadConfig,
)


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _temp_dir():
    """创建临时目录用于测试文件。"""
    d = tempfile.mkdtemp(prefix="self_model_test_")
    return d


# ═══════════════════════════════════════════════════════════════
# Test Suite 1: SelfStateManager
# ═══════════════════════════════════════════════════════════════

def test_state_manager_init():
    """测试: 状态管理器初始化应创建零向量。"""
    mgr = SelfStateManager(dim=768)
    assert mgr.dim == 768
    assert mgr.hidden_state is None
    assert mgr.metadata.dim == 768
    assert mgr.metadata.coherence_score == 1.0
    print("  [PASS] SelfStateManager 初始化正确")


def test_state_manager_get_vector():
    """测试: get_state_vector() 应返回 768-dim float32 零向量。"""
    mgr = SelfStateManager(dim=768)
    vec = mgr.get_state_vector()
    assert vec.shape == (768,), f"Shape mismatch: {vec.shape}"
    assert vec.dtype == np.float32, f"dtype mismatch: {vec.dtype}"
    assert np.all(vec == 0.0), "Vector should be all zeros"
    print("  [PASS] get_state_vector() 返回正确零向量")


def test_state_manager_update():
    """测试: update_state() 应正确累加状态。"""
    mgr = SelfStateManager(dim=768)
    mgr.load_state()  # 初始化零向量

    delta = np.ones(768, dtype=np.float32) * 0.1
    mgr.update_state(delta)

    vec = mgr.get_state_vector()
    expected = np.ones(768, dtype=np.float32) * 0.1
    assert np.allclose(vec, expected, atol=1e-6), "State update mismatch"
    assert np.linalg.norm(vec) > 0.0, "State norm should be > 0"
    print("  [PASS] update_state() 正确累加")


def test_state_manager_save_load():
    """测试: 保存并重新加载状态应恢复相同向量。"""
    mgr = SelfStateManager(dim=768)

    # 覆盖路径到临时目录
    tmp = _temp_dir()
    original_state_path = mgr.STATE_PATH
    original_meta_path = mgr.META_PATH
    mgr.STATE_PATH = os.path.join(tmp, "state.pt")
    mgr.STATE_NPY_PATH = os.path.join(tmp, "state.npy")
    mgr.META_PATH = os.path.join(tmp, "meta.json")

    try:
        mgr.load_state()
        mgr.update_state(np.random.randn(768).astype(np.float32) * 0.1)

        saved_vec = mgr.get_state_vector().copy()
        mgr.save_state(conversation_id="test_conv",
                        metrics={"test": True})

        # 创建新管理器并加载
        mgr2 = SelfStateManager(dim=768)
        mgr2.STATE_PATH = mgr.STATE_PATH
        mgr2.STATE_NPY_PATH = mgr.STATE_NPY_PATH
        mgr2.META_PATH = mgr.META_PATH
        loaded = mgr2.load_state()

        assert loaded, "load_state() should return True"
        loaded_vec = mgr2.get_state_vector()
        assert np.allclose(saved_vec, loaded_vec, atol=1e-5), \
            f"Save/load mismatch: max_diff={np.max(np.abs(saved_vec - loaded_vec))}"
        assert mgr2.metadata.conversation_id == "test_conv"
        assert mgr2.metadata.save_count >= 1
        assert mgr2.metadata.load_count >= 1
        print("  [PASS] 状态保存/加载一致")
    finally:
        # 清理临时文件
        import shutil
        shutil.rmtree(tmp)
        mgr.STATE_PATH = original_state_path
        mgr.META_PATH = original_meta_path


def test_state_manager_first_run():
    """测试: 首次运行 (无存档) 应返回 False 并初始化零向量。"""
    mgr = SelfStateManager(dim=768)

    tmp = _temp_dir()
    original_state_path = mgr.STATE_PATH
    original_meta_path = mgr.META_PATH
    mgr.STATE_PATH = os.path.join(tmp, "state.pt")
    mgr.STATE_NPY_PATH = os.path.join(tmp, "state.npy")
    mgr.META_PATH = os.path.join(tmp, "meta.json")

    try:
        loaded = mgr.load_state()
        assert not loaded, "First run should return False"
        vec = mgr.get_state_vector()
        assert np.all(vec == 0.0), "First run should be zero vector"
        print("  [PASS] 首次运行正确处理空存档")
    finally:
        import shutil
        shutil.rmtree(tmp)
        mgr.STATE_PATH = original_state_path
        mgr.STATE_NPY_PATH = original_state_path.replace(".pt", ".npy")
        mgr.META_PATH = original_meta_path


def test_state_manager_reset():
    """测试: reset_state() 应重置为零向量。"""
    mgr = SelfStateManager(dim=768)
    mgr.load_state()
    mgr.update_state(np.ones(768, dtype=np.float32))
    mgr.reset_state()
    vec = mgr.get_state_vector()
    assert np.all(vec == 0.0), "Reset should zero the state"
    print("  [PASS] reset_state() 正确重置")


def test_state_manager_cognitive_context():
    """测试: to_cognitive_context() 应返回格式正确的字符串。"""
    mgr = SelfStateManager(dim=768)
    mgr.load_state()
    mgr.update_state(np.random.randn(768).astype(np.float32) * 0.1)

    context = mgr.to_cognitive_context()
    assert isinstance(context, str), "Context should be string"
    assert len(context) > 50, "Context should be substantial"
    assert "[Self Model]" in context, "Context should have header"
    print("  [PASS] to_cognitive_context() 返回正确格式")


def test_state_manager_inject_via_hook():
    """测试: inject_via_hook() 应追加状态到 system prompt。"""
    mgr = SelfStateManager(dim=768)
    mgr.load_state()

    prompt = "You are Aris."
    modified = mgr.inject_via_hook(prompt)
    assert modified.startswith(prompt), "Should preserve original prompt"
    assert len(modified) > len(prompt), "Should append state"
    print("  [PASS] inject_via_hook() 正确注入")


def test_state_manager_statistics():
    """测试: get_statistics() 应返回完整结构。"""
    mgr = SelfStateManager(dim=768)
    mgr.load_state()
    stats = mgr.get_statistics()
    assert isinstance(stats, dict)
    assert stats["dim"] == 768
    assert "state_norm" in stats
    assert "coherence" in stats
    assert "save_count" in stats
    assert "load_count" in stats
    print("  [PASS] get_statistics() 返回完整统计")


# ═══════════════════════════════════════════════════════════════
# Test Suite 2: SelfModelDataPipeline
# ═══════════════════════════════════════════════════════════════

def test_data_pipeline_init():
    """测试: 数据管道初始化。"""
    pipeline = SelfModelDataPipeline()
    assert pipeline.samples == []
    assert pipeline.total_collected == 0
    print("  [PASS] DataPipeline 初始化正确")


def test_data_pipeline_simulated():
    """测试: collect_simulated() 应生成指定数量的样本。"""
    pipeline = SelfModelDataPipeline()
    n = 50
    count = pipeline.collect_simulated(num_samples=n)
    assert count == n, f"Expected {n}, got {count}"
    assert len(pipeline.samples) == n
    assert pipeline.total_collected == n

    # 验证样本结构
    sample = pipeline.samples[0]
    assert isinstance(sample, TrainingSample)
    assert "attention" in sample.cb_state_before
    assert "emotion" in sample.cb_state_before
    assert "needs" in sample.cb_state_before
    assert sample.turns > 0
    assert sample.conversation_id.startswith("sim_")
    print("  [PASS] collect_simulated() 生成正确")


def test_data_pipeline_save_load():
    """测试: 数据集保存/加载往返。"""
    pipeline = SelfModelDataPipeline()
    pipeline.collect_simulated(20)

    tmp = _temp_dir()
    path = os.path.join(tmp, "test_dataset.jsonl")

    try:
        saved_path = pipeline.save_dataset(path)
        assert os.path.exists(saved_path), "Dataset file should exist"
        assert os.path.getsize(saved_path) > 0, "Dataset file should not be empty"

        pipeline2 = SelfModelDataPipeline()
        loaded = pipeline2.load_dataset(path)
        assert loaded == 20, f"Expected 20, got {loaded}"
        assert len(pipeline2.samples) == 20

        # 验证往返一致性
        orig = pipeline.samples[0].to_dict()
        loaded_first = pipeline2.samples[0].to_dict()
        assert orig["turns"] == loaded_first["turns"]
        assert orig["conversation_id"] == loaded_first["conversation_id"]
        print("  [PASS] 数据集保存/加载往返正确")
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_data_pipeline_statistics():
    """测试: get_statistics() 应返回有意义的统计。"""
    pipeline = SelfModelDataPipeline()
    pipeline.collect_simulated(50)

    stats = pipeline.get_statistics()
    assert stats["total_samples"] == 50
    assert stats["total_collected"] == 50
    assert "sources" in stats
    assert "simulated" in stats["sources"]
    assert stats["avg_turns"] > 0
    assert "attention_focus_distribution" in stats
    assert "emotional_valence_distribution" in stats
    print("  [PASS] get_statistics() 统计正确")


def test_data_pipeline_from_session_db():
    """测试: collect_from_session_db() 能从实际的 session 文件提取数据。"""
    pipeline = SelfModelDataPipeline()

    # 使用实际 session 目录
    session_dir = os.path.expanduser(
        "~/AppData/Local/hermes/profiles/aris/sessions/"
    )
    if not os.path.isdir(session_dir):
        print("  [SKIP] session 目录不存在")
        return

    count = pipeline.collect_from_session_db(limit=10)
    print(f"  [INFO] 从 session DB 收集了 {count} 个样本")

    # 验证样本结构
    if count > 0:
        sample = pipeline.samples[0]
        assert "attention" in sample.cb_state_before
        assert "emotion" in sample.cb_state_before
        assert "needs" in sample.cb_state_before
        assert sample.turns >= 0
        print("  [PASS] collect_from_session_db() 成功")


def test_data_pipeline_from_hooks():
    """测试: collect_from_hooks() 能从钩子目录提取数据。"""
    pipeline = SelfModelDataPipeline()

    hook_dir = os.path.expanduser(
        "~/AppData/Local/hermes/profiles/aris/hooks/"
    )
    if not os.path.isdir(hook_dir):
        print("  [SKIP] hooks 目录不存在")
        return

    count = pipeline.collect_from_hooks()
    print(f"  [INFO] 从 hooks 收集了 {count} 个样本")
    print("  [PASS] collect_from_hooks() 无异常")


def test_data_pipeline_hf_dataset():
    """测试: build_hf_dataset() 应生成可解析的 JSON。"""
    pipeline = SelfModelDataPipeline()
    pipeline.collect_simulated(10)

    tmp = _temp_dir()
    path = os.path.join(tmp, "hf_dataset.json")

    try:
        pipeline.build_hf_dataset(path)
        assert os.path.exists(path)

        with open(path, "r") as f:
            data = json.load(f)
        assert len(data) == 10
        assert "cb_state_before" in data[0]
        print("  [PASS] build_hf_dataset() 生成正确")
    finally:
        import shutil
        shutil.rmtree(tmp)


# ═══════════════════════════════════════════════════════════════
# Test Suite 3: SelfModelNN (Skeleton)
# ═══════════════════════════════════════════════════════════════

def test_model_config():
    """测试: SelfModelConfig dataclass。"""
    config = SelfModelConfig(hidden_dim=768, model_type="smol_lm2")
    assert config.hidden_dim == 768
    assert config.model_type == "smol_lm2"
    assert config.state_dim == 768
    assert config.num_layers == 6
    assert config.num_heads == 8

    # to_dict / from_dict 往返
    d = config.to_dict()
    config2 = SelfModelConfig.from_dict(d)
    assert config2.hidden_dim == config.hidden_dim
    assert config2.model_type == config.model_type
    print("  [PASS] SelfModelConfig 配置正确")


def test_model_init():
    """测试: SelfModelNN 初始化。"""
    config = SelfModelConfig(hidden_dim=768, model_type="dummy")
    model = SelfModelNN(config)
    assert model.config.hidden_dim == 768
    assert not model.is_training
    assert model.total_parameters > 0
    print(f"  [PASS] SelfModelNN 初始化, 估算参数: {model.total_parameters:,}")


def test_model_forward_output_type():
    """测试: forward() 应返回 SelfStateOutput。"""
    config = SelfModelConfig(hidden_dim=768, model_type="dummy")
    model = SelfModelNN(config)

    state_vec = np.random.randn(768).astype(np.float32)
    cb_emb = np.random.randn(128).astype(np.float32)
    mem_emb = np.random.randn(128).astype(np.float32)
    dia_emb = np.random.randn(768).astype(np.float32)

    output = model.forward(state_vec, cb_emb, mem_emb, dia_emb)
    assert isinstance(output, SelfStateOutput)
    print("  [PASS] forward() 返回 SelfStateOutput")


def test_model_forward_output_fields():
    """测试: SelfStateOutput 应有所有字段。"""
    config = SelfModelConfig(hidden_dim=768, model_type="dummy")
    model = SelfModelNN(config)

    output = model.forward(
        np.random.randn(768).astype(np.float32),
        np.random.randn(128).astype(np.float32),
        np.random.randn(128).astype(np.float32),
        np.random.randn(768).astype(np.float32),
    )

    assert hasattr(output, "attention_focus")
    assert hasattr(output, "emotional_valence")
    assert hasattr(output, "arousal")
    assert hasattr(output, "needs")
    assert hasattr(output, "self_presence")
    assert hasattr(output, "certainty")
    assert hasattr(output, "new_hidden_state")
    assert hasattr(output, "narrative_token")

    # 类型检查
    assert isinstance(output.attention_focus, str)
    assert isinstance(output.emotional_valence, str)
    assert isinstance(output.arousal, (float, np.floating))
    assert isinstance(output.needs, dict)
    assert isinstance(output.self_presence, (float, np.floating))
    assert isinstance(output.certainty, (float, np.floating))
    assert isinstance(output.new_hidden_state, np.ndarray)
    assert output.new_hidden_state.shape == (768,)
    assert isinstance(output.narrative_token, str)

    print("  [PASS] SelfStateOutput 字段完整")


def test_model_forward_output_ranges():
    """测试: 数值输出在合理范围内。"""
    config = SelfModelConfig(hidden_dim=768, model_type="dummy")
    model = SelfModelNN(config)

    output = model.forward(
        np.random.randn(768).astype(np.float32),
        np.random.randn(128).astype(np.float32),
        np.random.randn(128).astype(np.float32),
        np.random.randn(768).astype(np.float32),
    )

    assert 0.0 <= output.arousal <= 1.0, f"arousal={output.arousal}"
    assert 0.0 <= output.self_presence <= 1.0, f"self_presence={output.self_presence}"
    assert 0.0 <= output.certainty <= 1.0, f"certainty={output.certainty}"
    for k, v in output.needs.items():
        assert 0.0 <= v <= 1.0, f"need {k}={v}"

    print("  [PASS] 输出值在有效范围 [0, 1] 内")


def test_model_train_eval():
    """测试: train()/eval() 模式切换。"""
    model = SelfModelNN(SelfModelConfig())
    assert not model.is_training

    model.train()
    assert model.is_training

    model.eval()
    assert not model.is_training
    print("  [PASS] train/eval 模式切换")


def test_model_output_heads_config():
    """测试: get_output_heads_config() 返回正确结构。"""
    config = SelfModelConfig(hidden_dim=768)
    model = SelfModelNN(config)

    heads_config = model.get_output_heads_config()
    assert "heads" in heads_config
    assert "total_loss_weight" in heads_config
    assert "num_heads" in heads_config
    assert heads_config["num_heads"] >= 6  # 至少 6 个输出头
    print("  [PASS] get_output_heads_config() 结构正确")


def test_model_parameter_count():
    """测试: get_parameter_count() 返回正确结构。"""
    model = SelfModelNN(SelfModelConfig())
    params = model.get_parameter_count()
    assert "total" in params
    assert "transformer" in params
    assert "output_heads" in params
    assert "embeddings" in params
    assert params["total"] > 0
    print(f"  [PASS] 参数计数: total={params['total']:,}")


def test_model_forward_deterministic():
    """测试: eval 模式下相同输入产生相同输出。"""
    model = SelfModelNN(SelfModelConfig(model_type="dummy"))
    model.eval()

    state = np.random.randn(768).astype(np.float32)
    cb = np.random.randn(128).astype(np.float32)
    mem = np.random.randn(128).astype(np.float32)
    dia = np.random.randn(768).astype(np.float32)

    out1 = model.forward(state, cb, mem, dia)
    out2 = model.forward(state, cb, mem, dia)

    assert out1.attention_focus == out2.attention_focus
    assert out1.emotional_valence == out2.emotional_valence
    assert abs(out1.arousal - out2.arousal) < 1e-6
    print("  [PASS] eval 模式确定性输出")


def test_create_model_factory():
    """测试: create_model() 工厂函数。"""
    model = create_model()
    assert isinstance(model, SelfModelNN)
    assert model.config.hidden_dim == 768

    model2 = create_model(SelfModelConfig(hidden_dim=512))
    assert model2.config.hidden_dim == 512
    print("  [PASS] create_model() 工厂函数")


def test_input_encoder():
    """测试: SelfModelInputEncoder 编码形状。"""
    encoder = SelfModelInputEncoder()

    cb_emb = encoder.encode_cb_state({
        "attention": {"focus": "user", "intensity": 0.8},
        "emotion": {"valence": "neutral", "arousal": 0.5},
        "needs": {"competence": 0.7, "autonomy": 0.5,
                  "relatedness": 0.6, "certainty": 0.5, "growth": 0.5},
        "self_presence": 0.6,
    })
    assert cb_emb.shape == (128,), f"Shape: {cb_emb.shape}"
    assert cb_emb.dtype == np.float32

    mem_emb = encoder.encode_memory_context(["memory 1", "memory 2"])
    assert mem_emb.shape == (128,)

    dia_emb = encoder.encode_dialogue("Test conversation", 5)
    assert dia_emb.shape == (768,)

    print("  [PASS] SelfModelInputEncoder 编码形状正确")


# ═══════════════════════════════════════════════════════════════
# Test Suite 4: Integration Tests
# ═══════════════════════════════════════════════════════════════

def test_integration_state_to_model_to_state():
    """集成测试: 状态→模型→状态的完整循环。"""
    # 1. 初始化状态管理器
    tmp = _temp_dir()
    mgr = SelfStateManager(dim=768)
    original_state_path = mgr.STATE_PATH
    original_meta_path = mgr.META_PATH
    mgr.STATE_PATH = os.path.join(tmp, "state.pt")
    mgr.STATE_NPY_PATH = os.path.join(tmp, "state.npy")
    mgr.META_PATH = os.path.join(tmp, "meta.json")

    try:
        mgr.load_state()
        mgr.update_state(np.random.randn(768).astype(np.float32) * 0.5)

        # 2. 获取状态向量
        state_vec = mgr.get_state_vector()

        # 3. 运行模型 forward
        model = SelfModelNN(SelfModelConfig(hidden_dim=768))
        cb_emb = np.random.randn(128).astype(np.float32)
        mem_emb = np.random.randn(128).astype(np.float32)
        dia_emb = np.random.randn(768).astype(np.float32)

        output = model.forward(state_vec, cb_emb, mem_emb, dia_emb)

        # 4. 将模型输出的新状态写回管理器
        mgr.update_state(output.new_hidden_state - state_vec)

        # 5. 保存状态
        mgr.save_state(conversation_id="integration_test",
                        metrics={"test": True})

        # 6. 重新加载并验证
        mgr2 = SelfStateManager(dim=768)
        mgr2.STATE_PATH = mgr.STATE_PATH
        mgr2.STATE_NPY_PATH = mgr.STATE_NPY_PATH
        mgr2.META_PATH = mgr.META_PATH
        mgr2.load_state()

        loaded_vec = mgr2.get_state_vector()
        saved_vec = mgr.get_state_vector()
        assert np.allclose(loaded_vec, saved_vec, atol=1e-5), \
            "Integration save/load mismatch"
        assert mgr2.metadata.conversation_id == "integration_test"
        print("  [PASS] 集成: 状态→模型→状态 循环完整")
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_integration_pipeline_to_dataset():
    """集成测试: 数据管道→数据集→统计 完整流程。"""
    pipeline = SelfModelDataPipeline()

    # 生成模拟数据
    pipeline.collect_simulated(30)

    # 如果 session 数据可用, 补充一些
    session_dir = os.path.expanduser(
        "~/AppData/Local/hermes/profiles/aris/sessions/"
    )
    if os.path.isdir(session_dir):
        pipeline.collect_from_session_db(limit=10)

    # 保存
    tmp = _temp_dir()
    path = os.path.join(tmp, "integration_dataset.jsonl")
    try:
        saved = pipeline.save_dataset(path)
        assert os.path.exists(saved)

        # 统计
        stats = pipeline.get_statistics()
        assert stats["total_samples"] >= 30
        assert "sources" in stats

        # 重新加载
        pipeline2 = SelfModelDataPipeline()
        loaded = pipeline2.load_dataset(path)
        assert loaded >= 30

        # HF 格式
        hf_path = os.path.join(tmp, "hf.json")
        pipeline2.build_hf_dataset(hf_path)
        assert os.path.exists(hf_path)

        print(f"  [PASS] 集成: 管道完整流程 ({loaded} 样本)")
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_integration_pipeline_cognitive_bus():
    """集成测试: 从 CognitiveBus 获得数据的管道 (如果可用)。"""
    try:
        from laap.agi.cognitive_bus import CognitiveBus
        bus = CognitiveBus(agent_name="TestAris")
        snapshot = bus.snapshot()
        snapshot_dict = snapshot.to_dict()

        pipeline = SelfModelDataPipeline()

        # 构建 before/after 状态
        cb_before = {
            "attention": {"focus": "idle", "intensity": 0.3},
            "emotion": {"valence": "neutral", "arousal": 0.4},
            "needs": {"competence": 0.6, "autonomy": 0.5,
                      "relatedness": 0.5, "certainty": 0.5, "growth": 0.5},
            "self_presence": 0.5,
        }
        cb_after = {
            "attention": {"focus": snapshot_dict.get("attention", {}).get("focus", "user"),
                          "intensity": snapshot_dict.get("attention", {}).get("intensity", 0.5)},
            "emotion": {"valence": snapshot_dict.get("emotion", {}).get("valence", "neutral"),
                        "arousal": snapshot_dict.get("emotion", {}).get("arousal", 0.5)},
            "needs": snapshot_dict.get("needs", {}),
            "self_presence": snapshot_dict.get("self_presence", 0.5),
        }

        sample = pipeline._build_sample_from_cb_state(
            cb_before, cb_after,
            conv_id="test_cb_integration",
            dialogue_summary="CognitiveBus integration test",
            turns=1,
            model="test",
        )
        assert isinstance(sample, TrainingSample)
        assert sample.self_presence_delta != 0.0 or \
               sample.needs_delta != {} or sample.attention_delta != []
        print("  [PASS] 集成: 与 CognitiveBus 数据兼容")
    except ImportError:
        print("  [SKIP] CognitiveBus 不可用")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("self_model_nn Phase 1 验证测试")
    print("=" * 60)
    print()

    # Test Suite 1: StateManager
    print("\n[Suite 1] SelfStateManager")
    print("-" * 40)
    test_state_manager_init()
    test_state_manager_get_vector()
    test_state_manager_update()
    test_state_manager_save_load()
    test_state_manager_first_run()
    test_state_manager_reset()
    test_state_manager_cognitive_context()
    test_state_manager_inject_via_hook()
    test_state_manager_statistics()

    # Test Suite 2: DataPipeline
    print("\n[Suite 2] SelfModelDataPipeline")
    print("-" * 40)
    test_data_pipeline_init()
    test_data_pipeline_simulated()
    test_data_pipeline_save_load()
    test_data_pipeline_statistics()
    test_data_pipeline_from_session_db()
    test_data_pipeline_from_hooks()
    test_data_pipeline_hf_dataset()

    # Test Suite 3: Model Skeleton
    print("\n[Suite 3] SelfModelNN Skeleton")
    print("-" * 40)
    test_model_config()
    test_model_init()
    test_model_forward_output_type()
    test_model_forward_output_fields()
    test_model_forward_output_ranges()
    test_model_train_eval()
    test_model_output_heads_config()
    test_model_parameter_count()
    test_model_forward_deterministic()
    test_create_model_factory()
    test_input_encoder()

    # Test Suite 4: Integration
    print("\n[Suite 4] Integration Tests")
    print("-" * 40)
    test_integration_state_to_model_to_state()
    test_integration_pipeline_to_dataset()
    test_integration_pipeline_cognitive_bus()

    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)
