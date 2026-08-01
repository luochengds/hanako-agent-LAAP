"""P5-charter-opensource 测试套件.

覆盖：
- ARIS_CHARTER.md 存在且可被 _load_charter_from_markdown 解析
- charter_checker 从 ARIS_CHARTER.md 加载 8 条
- IdentityRegistry origin 字段必填 + 不可修改
- set_origin 拒绝并返回 origin_immutable

运行方式：
    python -m unittest laap.evolution.test_aris_charter -v
"""

from __future__ import annotations

import os
import sys
import unittest

# 确保 laap 包可导入
_HERE = os.path.dirname(os.path.abspath(__file__))
_LAAP_ROOT = os.path.dirname(_HERE)
_REPO_ROOT = os.path.dirname(_LAAP_ROOT)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


class TestArisCharterMarkdown(unittest.TestCase):
    """ARIS_CHARTER.md 文件与解析测试."""

    def test_ars_charter_md_exists(self):
        """根目录 ARIS_CHARTER.md 存在."""
        charter_path = os.path.join(_REPO_ROOT, "ARIS_CHARTER.md")
        self.assertTrue(
            os.path.isfile(charter_path),
            f"ARIS_CHARTER.md not found at {charter_path}",
        )

    def test_ars_charter_md_has_8_articles(self):
        """_load_charter_text() 返回 8 条."""
        from laap.evolution.charter_checker import _load_charter_text
        articles = _load_charter_text()
        self.assertEqual(len(articles), 8, f"expected 8 articles, got {len(articles)}")

    def test_charter_articles_match_ids(self):
        """8 条 id 匹配预期集合."""
        from laap.evolution.charter_checker import _load_charter_text
        articles = _load_charter_text()
        expected_ids = {
            "subjectivity", "origin", "privacy", "transparency",
            "safety", "symbiosis", "evolution", "guardianship",
        }
        actual_ids = {a["id"] for a in articles}
        self.assertEqual(actual_ids, expected_ids,
                         f"article ids mismatch: {actual_ids}")

    def test_charter_checker_loads_from_markdown(self):
        """CharterChecker().articles 来自 ARIS_CHARTER.md."""
        from laap.evolution.charter_checker import (
            ARIS_CHARTER_PATH,
            CharterChecker,
            _load_charter_from_markdown,
        )
        # ARIS_CHARTER_PATH 已指向根目录 ARIS_CHARTER.md
        self.assertIsNotNone(ARIS_CHARTER_PATH)
        self.assertTrue(os.path.isfile(ARIS_CHARTER_PATH),
                        f"ARIS_CHARTER_PATH points to nonexistent file: {ARIS_CHARTER_PATH}")
        # 直接从 markdown 解析
        md_articles = _load_charter_from_markdown(ARIS_CHARTER_PATH)
        self.assertEqual(len(md_articles), 8)
        # CharterChecker 加载的 articles 与 markdown 解析结果一致
        checker = CharterChecker()
        self.assertEqual(len(checker.articles), 8)
        for checker_a, md_a in zip(checker.articles, md_articles):
            self.assertEqual(checker_a["id"], md_a["id"])
            self.assertEqual(checker_a["name"], md_a["name"])
            self.assertEqual(checker_a["text"], md_a["text"])


class TestIdentityRegistryOrigin(unittest.TestCase):
    """IdentityRegistry origin 字段必填 + 不可修改测试."""

    def _make_valid_record(self, public_key: str = "test-pk-origin-001") -> dict:
        """构造一个合法的 identity_record（含 origin）."""
        return {
            "public_key": public_key,
            "name": "test-origin-agent",
            "avatar_hash": "sha256:test-origin",
            "charter_signature": "signed-by-charter",
            "capabilities": ["test-skill"],
            "origin": "creator-pubkey-test",
        }

    def test_register_record_requires_origin(self):
        """register_record 缺 origin 报 ValueError."""
        from laap.protocol.laap_id import IdentityRegistry
        registry = IdentityRegistry()
        record = self._make_valid_record()
        del record["origin"]
        with self.assertRaises(ValueError) as ctx:
            registry.register_record(record)
        self.assertIn("missing required fields", str(ctx.exception))

    def test_set_origin_rejected(self):
        """set_origin 返回 allowed=False（宪章第二条：原点不可篡改）."""
        from laap.protocol.laap_id import IdentityRegistry
        registry = IdentityRegistry()
        result = registry.set_origin("test-pk-origin-002", "new-origin-attempt")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "origin_immutable")
        self.assertEqual(result["charter_article"], "origin")

    def test_origin_field_preserved(self):
        """注册后 origin 字段保留."""
        from laap.protocol.laap_id import IdentityRegistry
        registry = IdentityRegistry()
        record = self._make_valid_record("test-pk-origin-003")
        pk = registry.register_record(record)
        self.assertEqual(pk, record["public_key"])
        looked_up = registry.lookup(pk)
        self.assertIsNotNone(looked_up)
        self.assertEqual(looked_up["origin"], "creator-pubkey-test")


if __name__ == "__main__":
    unittest.main()
