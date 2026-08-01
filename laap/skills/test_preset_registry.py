"""P5-laaper-market 单元测试 — preset_registry.py

验证项:
1. list_presets 返回 4 个预设
2. get_preset 按 ID 查找 / 不存在返回 None
3. clone_preset 复制 yuan/ishiki/color 等核心字段
4. clone_preset 应用新名称
5. clone_preset 应用自定义性格
6. clone_preset 不存在预设报错
7. 所有预设 charter_version = v1.0
8. 单例重置

运行方式:
    python -m unittest laap.skills.test_preset_registry -v
"""

from __future__ import annotations

import unittest

from laap.skills.preset_registry import (
    PresetRegistry,
    PresetPack,
    get_preset_registry,
    reset_preset_registry_for_test,
)


class TestPresetRegistry(unittest.TestCase):
    """PresetRegistry 单元测试."""

    def setUp(self):
        """每个用例使用全新 PresetRegistry 实例, 避免单例污染."""
        self.registry = PresetRegistry()

    def test_list_presets_returns_4(self):
        """list_presets 应返回 4 个预设包."""
        presets = self.registry.list_presets()
        self.assertEqual(len(presets), 4)

    def test_get_preset_by_id(self):
        """按 ID 查找应返回对应预设, 且字段完整."""
        aris = self.registry.get_preset("aris")
        self.assertIsNotNone(aris)
        self.assertEqual(aris["id"], "aris")
        self.assertEqual(aris["color"], "#4A90D9")
        self.assertEqual(aris["initial_skills"], ["code-review", "memory-helper"])
        self.assertEqual(aris["charter_version"], "v1.0")
        # 4 个预设 ID 均可查到
        for pid in ("aris", "hanako", "butter", "miku"):
            self.assertIsNotNone(self.registry.get_preset(pid), f"{pid} 应存在")

    def test_get_preset_not_found(self):
        """不存在的 ID 应返回 None."""
        self.assertIsNone(self.registry.get_preset("nonexistent-preset"))

    def test_clone_preset_copies_fields(self):
        """克隆应复制 yuan/ishiki/color/avatar_seed/initial_skills 等核心字段."""
        result = self.registry.clone_preset("aris", "MyAris")
        self.assertTrue(result["cloned"])
        config = result["config"]
        # 名称使用新名称
        self.assertEqual(config["name"], "MyAris")
        # 核心字段来自源预设
        self.assertEqual(config["yuan"], "理性/好奇/创造")
        self.assertEqual(config["ishiki"], "第一性原理思考")
        self.assertEqual(config["color"], "#4A90D9")
        self.assertEqual(config["avatar_seed"], "aris-inventor-seed")
        self.assertEqual(config["initial_skills"], ["code-review", "memory-helper"])
        self.assertEqual(config["charter_version"], "v1.0")
        # 源预设 ID 记录
        self.assertEqual(config["source_preset_id"], "aris")

    def test_clone_preset_applies_custom_name(self):
        """克隆应应用 new_name 覆盖名称."""
        result = self.registry.clone_preset("hanako", "小花子")
        self.assertEqual(result["config"]["name"], "小花子")
        # 源预设 name 不应被改
        self.assertEqual(self.registry.get_preset("hanako")["name"], "Hanako 默认包")

    def test_clone_preset_applies_customizations(self):
        """克隆应应用 customizations 覆盖性格倾向等字段."""
        result = self.registry.clone_preset(
            "butter",
            "CustomButter",
            customizations={
                "yuan": "冷静/理性/分析",
                "ishiki": "演绎推理思考",
                "color": "#123456",
                "initial_skills": ["code-review", "memory-helper"],
            },
        )
        config = result["config"]
        self.assertEqual(config["yuan"], "冷静/理性/分析")
        self.assertEqual(config["ishiki"], "演绎推理思考")
        self.assertEqual(config["color"], "#123456")
        self.assertEqual(config["initial_skills"], ["code-review", "memory-helper"])
        # 名称仍为 new_name
        self.assertEqual(config["name"], "CustomButter")

    def test_clone_preset_not_found(self):
        """克隆不存在的预设应抛 KeyError."""
        with self.assertRaises(KeyError):
            self.registry.clone_preset("no-such-preset", "Whatever")

    def test_all_presets_have_charter_v1(self):
        """所有预设 charter_version 必须为 v1.0."""
        for preset in self.registry.list_presets():
            self.assertEqual(
                preset["charter_version"],
                "v1.0",
                f"preset '{preset['id']}' charter_version 应为 v1.0",
            )

    def test_clone_does_not_mutate_source(self):
        """克隆的自定义不应反向污染源预设 (深拷贝隔离)."""
        self.registry.clone_preset(
            "miku",
            "MikuCopy",
            customizations={"yuan": "自定义性格"},
        )
        miku = self.registry.get_preset("miku")
        self.assertEqual(miku["yuan"], "敏感/审美/表达")
        self.assertEqual(miku["initial_skills"], [])

    def test_clone_ignores_non_overridable_fields(self):
        """customizations 中 charter_version / source_preset_id 应被忽略."""
        result = self.registry.clone_preset(
            "aris",
            "HackerAris",
            customizations={
                "charter_version": "v9.9",
                "source_preset_id": "miku",
                "name": "ShouldBeIgnored",
            },
        )
        config = result["config"]
        self.assertEqual(config["charter_version"], "v1.0")
        self.assertEqual(config["source_preset_id"], "aris")
        self.assertEqual(config["name"], "HackerAris")


class TestPresetPackDataclass(unittest.TestCase):
    """PresetPack dataclass 序列化测试."""

    def test_to_dict_roundtrip(self):
        """to_dict 应包含全部字段."""
        pack = PresetPack(
            id="test",
            name="测试包",
            description="测试",
            yuan="理性",
            ishiki="逻辑思考",
            avatar_seed="seed",
            color="#000000",
            initial_skills=["a", "b"],
        )
        d = pack.to_dict()
        self.assertEqual(d["id"], "test")
        self.assertEqual(d["yuan"], "理性")
        self.assertEqual(d["initial_skills"], ["a", "b"])
        self.assertEqual(d["charter_version"], "v1.0")


class TestPresetRegistrySingleton(unittest.TestCase):
    """单例行为测试."""

    def test_singleton_reset(self):
        """get_preset_registry 单例, reset 后应重新构造."""
        reset_preset_registry_for_test()
        r1 = get_preset_registry()
        r2 = get_preset_registry()
        self.assertIs(r1, r2, "单例应返回同一实例")

        reset_preset_registry_for_test()
        r3 = get_preset_registry()
        self.assertIsNot(r1, r3, "reset 后应返回新实例")
        # 新实例仍可用
        self.assertEqual(len(r3.list_presets()), 4)

        # 清理: 避免影响后续测试
        reset_preset_registry_for_test()


if __name__ == "__main__":
    unittest.main()
