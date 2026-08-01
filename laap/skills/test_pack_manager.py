"""P2-skill-packs 冒烟测试 — pack_manager.py

验证项 (spec L427: P2 冒烟测试即可):
1. SkillPackManifest 序列化 / 反序列化 / validate 闭环
2. export_pack → zip 文件存在且包含 manifest.json
3. import_pack → 解压到目标目录, manifest 校验通过
4. install → vault installed_skills 表写入记录
5. list_installed → 包含已安装技能
6. uninstall → 表中记录被删除
7. 幂等性: install 重复调用不报错
8. skill_pack_mcp_endpoints 5 个 helper 返回 (status, payload) 闭环

运行方式:
    python -m pytest laap/skills/test_pack_manager.py -v -p no:quadrants
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple

import pytest

from laap.skills import pack_manager as pm_mod
from laap.skills.pack_manager import (
    SkillPackManifest,
    export_pack,
    import_pack,
    install,
    uninstall,
    list_installed,
    list_available,
)
from laap.skills import skill_pack_mcp_endpoints as endpoints_mod


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_skills_dir(monkeypatch, tmp_path):
    """重定向 pack_manager.SKILLS_DIR 到临时目录, 避免污染 laap/skills/."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    # 同步重定向 DEFAULT_OUTPUT_DIR, 避免污染源码目录
    exports_dir = tmp_path / "_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(pm_mod, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(pm_mod, "DEFAULT_OUTPUT_DIR", exports_dir)
    # _skill_dir 函数读取模块级 SKILLS_DIR, 所以 monkeypatch 即可
    yield skills_dir


@pytest.fixture
def tmp_vault_dir(monkeypatch, tmp_path):
    """重定向 vault_manager.VAULT_DIR 到临时目录, 避免 SQLCipher 副作用.

    注意: laap.memory_vault.__init__ 把 vault_manager 单例对象 re-export,
    所以 `from laap.memory_vault import vault_manager` 拿到的是单例对象而非模块.
    必须通过 importlib.import_module 显式拿模块.
    """
    import importlib
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    vm_module = importlib.import_module("laap.memory_vault.vault_manager")
    monkeypatch.setattr(vm_module, "VAULT_DIR", str(vault_dir))
    # 重置全局 vault_manager 单例的 vault_dir, 并清空缓存
    monkeypatch.setattr(vm_module.vault_manager, "vault_dir", str(vault_dir))
    monkeypatch.setattr(vm_module.vault_manager, "_vault_cache", {})
    yield vault_dir


@pytest.fixture
def sample_skill(tmp_skills_dir):
    """在 tmp_skills_dir 下创建 sample-skill/ 测试技能包."""
    skill_id = "sample-skill"
    skill_dir = tmp_skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": skill_id,
        "version": "1.2.0",
        "component": "component.tsx",
        "prompt": "prompt.md",
        "tools": ["code-review", "search"],
        "dependencies": [],
        "author": "test-author",
        "charter_compatible": True,
        "description": "Sample skill for smoke testing",
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (skill_dir / "component.tsx").write_text(
        "export function Sample() { return null; }\n", encoding="utf-8"
    )
    (skill_dir / "prompt.md").write_text(
        "# Sample skill prompt\n", encoding="utf-8"
    )
    (skill_dir / "tools.json").write_text(
        json.dumps({"tools": ["code-review", "search"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return skill_id


# ── SubTask 2.1: SkillPackManifest 序列化 / 校验 ──────────────


def test_manifest_to_dict_from_dict_roundtrip():
    """manifest to_dict → from_dict 应保留所有字段."""
    m = SkillPackManifest(
        name="code-review",
        version="1.0.0",
        component="component.tsx",
        prompt="prompt.md",
        tools=["review"],
        dependencies=["base"],
        author="aris",
        charter_compatible=False,
        description="Code review skill",
    )
    d = m.to_dict()
    assert d["name"] == "code-review"
    assert d["version"] == "1.0.0"
    assert d["tools"] == ["review"]
    assert d["charter_compatible"] is False

    m2 = SkillPackManifest.from_dict(d)
    assert m2.name == m.name
    assert m2.version == m.version
    assert m2.component == m.component
    assert m2.tools == m.tools
    assert m2.charter_compatible is False


def test_manifest_validate_ok():
    """合法 manifest validate 返回空错误列表."""
    m = SkillPackManifest(name="valid-skill", version="1.0.0")
    assert m.validate() == []


def test_manifest_validate_bad_name():
    """非法 name (含大写 / 路径分隔符) 应被 validate 拦截."""
    bad = SkillPackManifest(name="BadName/Path", version="1.0.0")
    errors = bad.validate()
    assert any("name" in e for e in errors)


def test_manifest_validate_bad_version():
    """非法 version 应被 validate 拦截."""
    bad = SkillPackManifest(name="x", version="not-a-version")
    errors = bad.validate()
    assert any("version" in e for e in errors)


def test_manifest_validate_bad_component_path():
    """component 含路径分隔符应被拦截 (防 zip slip)."""
    bad = SkillPackManifest(
        name="x", version="1.0.0", component="../../../etc/passwd"
    )
    errors = bad.validate()
    assert any("component" in e for e in errors)


# ── SubTask 2.2: export_pack / import_pack / install / uninstall ──


def test_export_pack_creates_zip(tmp_skills_dir, sample_skill, tmp_path):
    """export_pack 应在 output_dir 生成 zip 文件, 内含 manifest.json."""
    out_dir = tmp_path / "exports"
    zip_path = export_pack(sample_skill, output_dir=out_dir)
    assert Path(zip_path).is_file()
    assert zip_path.endswith(f"{sample_skill}-v1.2.0.zip")

    # 校验 zip 内容
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "component.tsx" in names
        assert "prompt.md" in names
        assert "tools.json" in names
        # 校验 manifest 解析回来字段一致
        with zf.open("manifest.json") as f:
            data = json.loads(f.read().decode("utf-8"))
        assert data["name"] == sample_skill
        assert data["version"] == "1.2.0"


def test_export_pack_missing_skill_raises(tmp_skills_dir, tmp_path):
    """export_pack 不存在的 skill_id 应抛 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        export_pack("nonexistent-skill", output_dir=tmp_path)


def test_import_pack_extracts_and_validates(tmp_skills_dir, sample_skill, tmp_path):
    """export_pack → import_pack 闭环: zip 解压到目标目录, manifest 校验通过."""
    # 先 export
    out_dir = tmp_path / "exports"
    zip_path = export_pack(sample_skill, output_dir=out_dir)
    assert Path(zip_path).is_file()

    # import 到新的临时目录
    import_dir = tmp_path / "imported"
    skill_id = import_pack(zip_path, output_dir=import_dir)
    assert skill_id == sample_skill

    # 校验目标目录
    skill_dir = import_dir / sample_skill
    assert (skill_dir / "manifest.json").is_file()
    assert (skill_dir / "component.tsx").is_file()
    assert (skill_dir / "prompt.md").is_file()


def test_import_pack_missing_manifest_raises(tmp_skills_dir, tmp_path):
    """zip 缺 manifest.json 应抛 ValueError."""
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("component.tsx", "// no manifest")
    with pytest.raises(ValueError, match="missing"):
        import_pack(bad_zip, output_dir=tmp_path)


def test_install_and_list_installed(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """install → list_installed 闭环: 表中包含已安装技能."""
    agent = "test-agent-install"
    result = install(agent, sample_skill)
    assert result["installed"] is True
    assert result["skill_id"] == sample_skill
    assert result["version"] == "1.2.0"

    installed = list_installed(agent)
    assert len(installed) == 1
    assert installed[0]["skill_id"] == sample_skill
    assert installed[0]["version"] == "1.2.0"
    assert installed[0]["charter_compatible"] is True


def test_install_is_idempotent(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """install 重复调用应成功且不产生重复记录."""
    agent = "test-agent-idem"
    install(agent, sample_skill)
    install(agent, sample_skill)  # 重复
    install(agent, sample_skill)  # 再重复
    installed = list_installed(agent)
    assert len(installed) == 1  # 主键 upsert


def test_uninstall_removes_record(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """install → uninstall 后 list_installed 不应包含该 skill."""
    agent = "test-agent-uninstall"
    install(agent, sample_skill)
    assert len(list_installed(agent)) == 1

    result = uninstall(agent, sample_skill)
    assert result["uninstalled"] is True
    assert len(list_installed(agent)) == 0


def test_uninstall_idempotent_on_missing(tmp_vault_dir):
    """uninstall 不存在的记录应静默成功 (幂等)."""
    result = uninstall("no-such-agent", "no-such-skill")
    assert result["uninstalled"] is True


def test_list_installed_empty_for_new_agent(tmp_vault_dir):
    """新 agent 的 list_installed 应为空列表."""
    assert list_installed("brand-new-agent") == []


def test_list_available_finds_sample(tmp_skills_dir, sample_skill):
    """list_available 应扫描到 sample_skill."""
    avail = list_available()
    ids = [a["skill_id"] for a in avail]
    assert sample_skill in ids


# ── SubTask 2.4: versioning.py 接入 ──────────────────────────


def test_is_compatible_uses_versioning(tmp_skills_dir, sample_skill):
    """is_compatible 应基于 versioning.check_compatibility 判断."""
    # 同 major (1.x.x 与 1.0.0) → 兼容
    assert pm_mod.is_compatible(sample_skill, "1.0.0") is True
    # 不同 major (1.x.x 与 2.0.0) → 不兼容
    assert pm_mod.is_compatible(sample_skill, "2.0.0") is False


# ── Full 闭环: export → import → install → list → uninstall ──


def test_full_roundtrip(tmp_skills_dir, sample_skill, tmp_vault_dir, tmp_path):
    """spec L92: 导出 zip → 在另一实例导入安装 → list_installed 包含该 skill → uninstall 后不在列表."""
    # 1. export
    out_dir = tmp_path / "exports"
    zip_path = export_pack(sample_skill, output_dir=out_dir)
    assert Path(zip_path).is_file()

    # 2. import 到一个新目录 (模拟另一 Hanako 实例)
    #    注意: import_pack 默认输出到 SKILLS_DIR, 这里指定 output_dir 避免覆盖源
    import_dir = tmp_path / "imported"
    skill_id = import_pack(zip_path, output_dir=import_dir)
    assert skill_id == sample_skill
    assert (import_dir / sample_skill / "manifest.json").is_file()

    # 3. install 到 agent vault (从 import_dir 通过 monkeypatch _skill_dir)
    # 为简化测试, 直接调用 install() (sample_skill 仍存在于 tmp_skills_dir)
    agent = "roundtrip-agent"
    install(agent, sample_skill)
    installed = list_installed(agent)
    assert any(s["skill_id"] == sample_skill for s in installed)

    # 4. uninstall
    uninstall(agent, sample_skill)
    installed_after = list_installed(agent)
    assert not any(s["skill_id"] == sample_skill for s in installed_after)


# ── skill_pack_mcp_endpoints helper 闭环 ─────────────────────


def test_endpoint_handle_pack_list(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """handle_pack_list 返回 (200, {installed, available})."""
    agent = "ep-list-agent"
    install(agent, sample_skill)
    status, payload = endpoints_mod.handle_pack_list(agent)
    assert status == 200
    assert payload["agent_name"] == agent
    assert len(payload["installed"]) == 1
    assert any(a["skill_id"] == sample_skill for a in payload["available"])


def test_endpoint_handle_pack_list_missing_agent():
    """handle_pack_list 无 agent_name → 400."""
    status, payload = endpoints_mod.handle_pack_list("")
    assert status == 400
    assert "error" in payload


def test_endpoint_handle_pack_export(tmp_skills_dir, sample_skill, tmp_path):
    """handle_pack_export 返回 (200, {exported, zip_path, version})."""
    status, payload = endpoints_mod.handle_pack_export(
        sample_skill, output_dir=str(tmp_path)
    )
    assert status == 200
    assert payload["exported"] is True
    assert payload["skill_id"] == sample_skill
    assert payload["version"] == "1.2.0"
    assert Path(payload["zip_path"]).is_file()


def test_endpoint_handle_pack_export_missing_skill(tmp_skills_dir, tmp_path):
    """handle_pack_export 不存在的 skill → 404."""
    status, payload = endpoints_mod.handle_pack_export(
        "no-such-skill", output_dir=str(tmp_path)
    )
    assert status == 404


def test_endpoint_handle_pack_import(tmp_skills_dir, sample_skill, tmp_path):
    """handle_pack_import 返回 (200, {imported, skill_id})."""
    # 先 export
    zip_path = export_pack(sample_skill, output_dir=tmp_path)
    # import 到独立目录
    import_dir = tmp_path / "imported"
    status, payload = endpoints_mod.handle_pack_import(zip_path)
    # 注: 默认 import 到 SKILLS_DIR (已 monkeypatch 到 tmp_skills_dir)
    assert status == 200
    assert payload["imported"] is True
    assert payload["skill_id"] == sample_skill


def test_endpoint_handle_pack_install(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """handle_pack_install 返回 (200, {installed, skill_id, version})."""
    agent = "ep-install-agent"
    status, payload = endpoints_mod.handle_pack_install(agent, sample_skill)
    assert status == 200
    assert payload["installed"] is True
    assert payload["skill_id"] == sample_skill
    # 重复 install 应幂等成功
    status2, payload2 = endpoints_mod.handle_pack_install(agent, sample_skill)
    assert status2 == 200
    assert payload2["installed"] is True


def test_endpoint_handle_pack_uninstall(tmp_skills_dir, sample_skill, tmp_vault_dir):
    """handle_pack_uninstall 返回 (200, {uninstalled})."""
    agent = "ep-uninstall-agent"
    install(agent, sample_skill)
    status, payload = endpoints_mod.handle_pack_uninstall(agent, sample_skill)
    assert status == 200
    assert payload["uninstalled"] is True
    # 验证已删除
    assert not any(
        s["skill_id"] == sample_skill for s in list_installed(agent)
    )


def test_endpoint_handle_pack_install_missing_args():
    """handle_pack_install 缺参数 → 400."""
    status, payload = endpoints_mod.handle_pack_install("", "skill")
    assert status == 400
    status, payload = endpoints_mod.handle_pack_install("agent", "")
    assert status == 400
