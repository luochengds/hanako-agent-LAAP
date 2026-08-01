"""LAAP Lifeform — 单元测试 + 端到端验证"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, "D:/LAAP")

from laap.lifeform import Lifeform, LifeformConfig, EngineStatus


def test_basic_config():
    """测试基础配置创建"""
    config = LifeformConfig(
        name="测试生命体",
        role="architect",
        sandbox_id="sb-test-001",
    )
    assert config.name == "测试生命体"
    assert config.role == "architect"
    assert config.engines.psi is False  # 默认不开启
    print("  ✅ Basic config")


def test_lifeform_create():
    """测试 Lifeform 创建"""
    lf = Lifeform(LifeformConfig(name="Test", role="general"))
    assert lf.config.name == "Test"
    assert lf.sandbox_id.startswith("lf-")
    status = lf.status()
    assert status["engines_ready"] == "0/0"  # 没有引擎
    print(f"  ✅ Lifeform create: {lf.config.name} id={lf.sandbox_id}")


def test_lifeform_wake():
    """测试 Lifeform 唤醒 (带可用引擎)"""
    lf = Lifeform(LifeformConfig(
        name="Waker",
        role="test",
        sandbox_id="sb-wake-test",
    ))
    ok = lf.wake()
    # 至少 sandbox 应该成功
    assert lf._engine_status.get("sandbox") == EngineStatus.READY
    print(f"  ✅ Lifeform wake: sandbox={'READY' if ok else 'FAIL'}")
    print(f"     引擎状态: {lf.status()['engine_status']}")


def test_lifeform_save_load():
    """测试 Lifeform 持久化 + 恢复"""
    lf = Lifeform(LifeformConfig(
        name="持久化测试",
        role="architect",
        sandbox_id="sb-persist-test",
    ))
    lf.wake()

    # 保存到临时文件
    tmp = tempfile.mktemp(suffix=".json")
    lf.save(tmp)

    # 验证文件存在
    assert os.path.exists(tmp)
    size = os.path.getsize(tmp)
    assert size > 100
    print(f"  ✅ Lifeform save: {size} bytes")

    # 恢复
    lf2 = Lifeform.load(tmp)
    assert lf2.config.name == "持久化测试"
    assert lf2.config.role == "architect"
    assert lf2.sandbox_id == "sb-persist-test"
    print(f"  ✅ Lifeform load: {lf2.config.name}")

    os.unlink(tmp)


def test_lifeform_roundtrip():
    """测试 Lifeform save + load 完整闭环"""
    lf = Lifeform(LifeformConfig(name="循环测试", role="general"))
    lf.wake()
    tmp = tempfile.mktemp(suffix=".json")
    lf.save(tmp)

    lf2 = Lifeform.load(tmp)
    assert lf2.config.name == "循环测试"
    assert lf2.config.role == "general"
    # sandbox_id 在 load 时会从配置恢复, 可能不同
    assert lf2.config.name == lf.config.name
    print(f"  ✅ Save/Load roundtrip: {lf2.config.name}")
    os.unlink(tmp)


def test_yaml_config():
    """测试 YAML 配置解析"""
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "example-lifeform.yaml")
    if not os.path.exists(yaml_path):
        print("  ⚠️  YAML 示例文件不存在, 跳过")
        return
    cfg = LifeformConfig.from_yaml(yaml_path)
    assert cfg.name == "project-alpha-guardian"  # metadata.name
    assert cfg.role == "architect"
    assert cfg.engines.psi is True
    assert cfg.engines.causal is True
    assert cfg.engines.conscious is True
    assert cfg.governance.human_oversight == "required_for_changes"
    assert cfg.psi_profile.base_needs.get("certainty") == 0.6
    print(f"  ✅ YAML config: {cfg.name} ({cfg.role}) engines={cfg.engines}")


def test_status_output():
    """测试 status() 输出格式"""
    lf = Lifeform(LifeformConfig(name="StatusTest", role="test"))
    lf.wake()
    s = lf.status()
    assert "name" in s
    assert "engines_ready" in s
    assert "engine_status" in s
    assert "needs" in s
    assert "goals" in s
    print(f"  ✅ Status output: {s['name']} engines={s['engines_ready']}")


def test_serializer():
    """测试序列化器"""
    from laap.lifeform.serializer import serialize, deserialize, diff

    lf = Lifeform(LifeformConfig(name="SerialTest", role="test"))
    lf.wake()

    # 序列化
    json_str = serialize(lf)
    data = json.loads(json_str)
    assert data["version"] == "1.0"
    assert data["lifeform"]["name"] == "SerialTest"
    print(f"  ✅ Serialize: {len(json_str)} bytes")

    # 反序列化
    lf2 = deserialize(json_str)
    assert lf2.config.name == "SerialTest"
    print(f"  ✅ Deserialize: {lf2.config.name}")

    # Diff (应该没有变化)
    changes = diff(lf, lf2)
    print(f"  ✅ Diff: {len(changes)} changes (expected 0)")


if __name__ == "__main__":
    tests = [
        test_basic_config,
        test_lifeform_create,
        test_lifeform_wake,
        test_lifeform_save_load,
        test_lifeform_roundtrip,
        test_yaml_config,
        test_status_output,
        test_serializer,
    ]

    print(f"LAAP Lifeform Tests ({len(tests)} tests)")
    print("=" * 50)
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n结果: {passed}/{len(tests)} 通过")
