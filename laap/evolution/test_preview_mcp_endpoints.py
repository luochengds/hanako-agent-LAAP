"""LAAP — preview_mcp_endpoints 冒烟测试（SubTask 2.6）

测试用例：
- compute_line_diff: LCS 算法正确性（added/removed/unchanged）
- _is_path_allowed: 路径校验（允许根 + 阻止核心文件 + 阻止路径穿越）
- handle_preview_component: initial load 返回 old_source + 空 diff；带 diff 时正确生成
- handle_hot_replace: 成功替换 + 备份；幂等跳过；路径禁止拒绝；新文件创建

见证迹部分用 monkeypatch mock（避免依赖真实 vault）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from laap.evolution.preview_mcp_endpoints import (
    DiffLine,
    _is_path_allowed,
    _write_witness_trail,
    compute_line_diff,
    handle_hot_replace,
    handle_preview_component,
)


# ── compute_line_diff ──────────────────────────────────────


class TestComputeLineDiff:
    def test_identical_sources_all_unchanged(self):
        diff = compute_line_diff("a\nb\nc", "a\nb\nc")
        assert len(diff) == 3
        assert all(line.type == "unchanged" for line in diff)
        assert diff[0].old_line_no == 1 and diff[0].new_line_no == 1

    def test_added_line(self):
        diff = compute_line_diff("a\nc", "a\nb\nc")
        added = [l for l in diff if l.type == "added"]
        removed = [l for l in diff if l.type == "removed"]
        unchanged = [l for l in diff if l.type == "unchanged"]
        assert len(added) == 1 and added[0].content == "b"
        assert len(removed) == 0
        assert len(unchanged) == 2

    def test_removed_line(self):
        diff = compute_line_diff("a\nb\nc", "a\nc")
        added = [l for l in diff if l.type == "added"]
        removed = [l for l in diff if l.type == "removed"]
        assert len(added) == 0
        assert len(removed) == 1 and removed[0].content == "b"

    def test_modified_line_emits_remove_plus_add(self):
        diff = compute_line_diff("a\nold\nc", "a\nNEW\nc")
        added = [l for l in diff if l.type == "added"]
        removed = [l for l in diff if l.type == "removed"]
        assert len(added) == 1 and added[0].content == "NEW"
        assert len(removed) == 1 and removed[0].content == "old"

    def test_empty_sources(self):
        diff = compute_line_diff("", "")
        # split("") 返回 [""]，所以 1 个 unchanged 空行
        assert len(diff) == 1
        assert diff[0].type == "unchanged"

    def test_diffline_to_dict_keys(self):
        line = DiffLine("added", "x", None, 5)
        d = line.to_dict()
        assert d == {"type": "added", "content": "x", "newLineNo": 5}
        assert "oldLineNo" not in d


# ── _is_path_allowed ──────────────────────────────────────


class TestIsPathAllowed:
    def test_laap_path_allowed(self):
        assert _is_path_allowed("laap/evolution/sandbox.py") is True

    def test_hanako_plugins_path_allowed(self):
        assert _is_path_allowed("hanako/plugins/bubble-field/Bubble.tsx") is True

    def test_desktop_react_blocked(self):
        assert _is_path_allowed("hanako/desktop/src/react/App.tsx") is False

    def test_aris_bridge_blocked(self):
        assert _is_path_allowed("hanako/aris-bridge/aris-engine/sidecar.py") is False

    def test_path_traversal_blocked(self):
        assert _is_path_allowed("laap/../hanako/desktop/src/react/App.tsx") is False

    def test_absolute_unix_path_blocked(self):
        assert _is_path_allowed("/etc/passwd") is False

    def test_windows_drive_blocked(self):
        assert _is_path_allowed("C:/Windows/System32/drivers/etc/hosts") is False

    def test_empty_path_blocked(self):
        assert _is_path_allowed("") is False

    def test_root_level_file_blocked(self):
        assert _is_path_allowed("README.md") is False


# ── handle_preview_component ──────────────────────────────


class TestHandlePreviewComponent:
    def test_initial_load_returns_old_source_and_empty_diff(self, tmp_path):
        component = tmp_path / "laap" / "evolution" / "test_comp.py"
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_text("line1\nline2\nline3\n", encoding="utf-8")
        rel_path = "laap/evolution/test_comp.py"

        result = handle_preview_component(rel_path, "", repo_root=str(tmp_path))

        assert result["old_source"] == "line1\nline2\nline3\n"
        assert result["new_source"] == "line1\nline2\nline3\n"
        assert result["render_result"]["success"] is True
        assert all(d["type"] == "unchanged" for d in result["diff"])

    def test_preview_with_diff(self, tmp_path):
        component = tmp_path / "laap" / "evolution" / "test_comp.py"
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_text("line1\nline2\nline3\n", encoding="utf-8")
        rel_path = "laap/evolution/test_comp.py"
        new_content = "line1\nMODIFIED\nline3\n"

        result = handle_preview_component(
            rel_path, new_content, repo_root=str(tmp_path)
        )

        assert result["old_source"] == "line1\nline2\nline3\n"
        assert result["new_source"] == "line1\nMODIFIED\nline3\n"
        added = [d for d in result["diff"] if d["type"] == "added"]
        removed = [d for d in result["diff"] if d["type"] == "removed"]
        assert len(added) == 1 and added[0]["content"] == "MODIFIED"
        assert len(removed) == 1 and removed[0]["content"] == "line2"

    def test_preview_nonexistent_file_returns_empty_old(self, tmp_path):
        result = handle_preview_component(
            "laap/evolution/nonexistent.py", "", repo_root=str(tmp_path)
        )
        assert result["old_source"] == ""
        assert result["render_result"]["success"] is True


# ── handle_hot_replace ───────────────────────────────────


@pytest.fixture
def mock_witness_trail(monkeypatch):
    """Mock 见证迹写入，避免依赖真实 vault。"""
    monkeypatch.setattr(
        "laap.evolution.preview_mcp_endpoints._write_witness_trail",
        lambda **kwargs: "wit_test_mock",
    )
    return "wit_test_mock"


class TestHandleHotReplace:
    def test_successful_replace_with_backup(self, tmp_path, mock_witness_trail):
        component = tmp_path / "laap" / "evolution" / "test_comp.py"
        component.parent.mkdir(parents=True, exist_ok=True)
        original = "line1\nline2\n"
        component.write_text(original, encoding="utf-8")
        rel_path = "laap/evolution/test_comp.py"
        new_content = "line1\nMODIFIED\n"

        result = handle_hot_replace(
            rel_path, new_content, confirmed_by="test_user", repo_root=str(tmp_path)
        )

        assert result["replaced"] is True
        assert result["witness_trail_id"] == "wit_test_mock"
        assert result["skipped"] is False
        assert result["backup_path"] != ""
        assert ".bak." in result["backup_path"]
        # 文件已写入新内容
        assert component.read_text(encoding="utf-8") == new_content
        # 备份文件存在且含原内容
        backup = Path(result["backup_path"])
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == original

    def test_idempotent_same_content_skipped(self, tmp_path, mock_witness_trail):
        component = tmp_path / "laap" / "evolution" / "test_comp.py"
        component.parent.mkdir(parents=True, exist_ok=True)
        original = "line1\nline2\n"
        component.write_text(original, encoding="utf-8")
        rel_path = "laap/evolution/test_comp.py"

        result = handle_hot_replace(
            rel_path, original, confirmed_by="test_user", repo_root=str(tmp_path)
        )

        assert result["replaced"] is True
        assert result["skipped"] is True
        assert result["backup_path"] == ""
        # 文件内容不变
        assert component.read_text(encoding="utf-8") == original
        # 无 .bak 文件产生
        bak_files = list(component.parent.glob("*.bak.*"))
        assert bak_files == []

    def test_path_blocked_rejects_replace(self, tmp_path, mock_witness_trail):
        component = tmp_path / "hanako" / "desktop" / "src" / "react" / "App.tsx"
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_text("old\n", encoding="utf-8")
        rel_path = "hanako/desktop/src/react/App.tsx"

        result = handle_hot_replace(
            rel_path, "new\n", confirmed_by="test_user", repo_root=str(tmp_path)
        )

        assert result["replaced"] is False
        assert "error" in result and result["error"]
        # 文件未被修改
        assert component.read_text(encoding="utf-8") == "old\n"

    def test_replace_creates_new_file_when_not_exists(
        self, tmp_path, mock_witness_trail
    ):
        rel_path = "laap/evolution/new_file.py"
        new_content = "# new file\n"

        result = handle_hot_replace(
            rel_path, new_content, confirmed_by="test_user", repo_root=str(tmp_path)
        )

        assert result["replaced"] is True
        assert result["backup_path"] == ""  # 原文件不存在，无需备份
        new_file = tmp_path / rel_path
        assert new_file.exists()
        assert new_file.read_text(encoding="utf-8") == new_content

    def test_double_replace_only_one_backup(self, tmp_path, mock_witness_trail):
        """连续两次替换（不同内容），每次都备份（非幂等场景）。"""
        component = tmp_path / "laap" / "evolution" / "test_comp.py"
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_text("v0\n", encoding="utf-8")
        rel_path = "laap/evolution/test_comp.py"

        # 第一次替换
        r1 = handle_hot_replace(
            rel_path, "v1\n", confirmed_by="u", repo_root=str(tmp_path)
        )
        assert r1["replaced"] is True and r1["backup_path"] != ""
        assert component.read_text(encoding="utf-8") == "v1\n"

        # 第二次替换（不同内容）
        r2 = handle_hot_replace(
            rel_path, "v2\n", confirmed_by="u", repo_root=str(tmp_path)
        )
        assert r2["replaced"] is True and r2["backup_path"] != ""
        assert component.read_text(encoding="utf-8") == "v2\n"

        # 应该有两个 .bak 文件
        bak_files = sorted(component.parent.glob("test_comp.py.bak.*"))
        assert len(bak_files) == 2
        assert bak_files[0].read_text(encoding="utf-8") == "v0\n"
        assert bak_files[1].read_text(encoding="utf-8") == "v1\n"

    def test_hanako_plugins_path_allowed(self, tmp_path, mock_witness_trail):
        """hanako/plugins/ 下文件应允许替换（SubTask 2.5 安全约束）。"""
        component = (
            tmp_path / "hanako" / "plugins" / "hot-compile-preview" / "test.tsx"
        )
        component.parent.mkdir(parents=True, exist_ok=True)
        component.write_text("old\n", encoding="utf-8")
        rel_path = "hanako/plugins/hot-compile-preview/test.tsx"

        result = handle_hot_replace(
            rel_path, "new\n", confirmed_by="u", repo_root=str(tmp_path)
        )

        assert result["replaced"] is True
        assert component.read_text(encoding="utf-8") == "new\n"
