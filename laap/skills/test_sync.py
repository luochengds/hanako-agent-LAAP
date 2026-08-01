"""P3-skill-sync: 跨 LAAPer 技能同步协议测试.

覆盖 spec SubTask 3.7 (tasks.md L126):
- 四步状态机: understanding -> adapting -> testing -> adopting -> adopted
- 性格适配差异: 不同 personality_override 产生不同 adapted_prompt
- 沙箱失败回滚: 测试不通过 -> state=rolled_back + 不写入 vault
- 步骤逐步推进: auto_advance=False + advance() 手动推进
- 幂等: 同 (peer_pk, skill_id, target_agent) 进行中返回同一 job_id
- 终态可重跑: adopted 任务可重新创建新 job
- list_jobs 状态过滤
- sidecar 桥接函数: handle_skill_sync_* 错误处理
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 确保导入 laap 包 (若从 laap/skills/ 目录运行 pytest)
_THIS_DIR = Path(__file__).resolve().parent
_LAAP_ROOT = _THIS_DIR.parent.parent
if str(_LAAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_LAAP_ROOT))

from laap.skills import pack_manager as pm_mod
from laap.skills.sync import (
    SkillSyncManager,
    SyncJobState,
    _template_adapt_prompt,
    _template_describe_skill,
    get_skill_sync_manager,
    load_agent_personality,
    reset_skill_sync_manager_for_test,
)
from laap.skills.sync_mcp_endpoints import (
    handle_skill_sync_advance,
    handle_skill_sync_list,
    handle_skill_sync_start,
    handle_skill_sync_status,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_skills_dir(monkeypatch, tmp_path):
    """重定向 pack_manager.SKILLS_DIR 到临时目录."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    exports_dir = tmp_path / "_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pm_mod, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(pm_mod, "DEFAULT_OUTPUT_DIR", exports_dir)
    yield skills_dir


@pytest.fixture
def tmp_vault_dir(monkeypatch, tmp_path):
    """重定向 vault_manager.VAULT_DIR 到临时目录."""
    import importlib
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    vm_module = importlib.import_module("laap.memory_vault.vault_manager")
    monkeypatch.setattr(vm_module, "VAULT_DIR", str(vault_dir))
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
        "tools": ["code-review"],
        "dependencies": [],
        "author": "test-author",
        "charter_compatible": True,
        "description": "Sample skill for sync testing",
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (skill_dir / "component.tsx").write_text(
        "export function Sample() { return null; }\n", encoding="utf-8"
    )
    (skill_dir / "prompt.md").write_text(
        "Review code carefully.\n", encoding="utf-8"
    )
    return skill_id


@pytest.fixture
def skill_with_tests(tmp_skills_dir):
    """创建带 tests.py 测试用例的技能包."""
    skill_id = "skill-with-tests"
    skill_dir = tmp_skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": skill_id,
        "version": "0.5.0",
        "component": None,
        "prompt": "prompt.md",
        "tools": [],
        "dependencies": [],
        "author": "tester",
        "charter_compatible": True,
        "description": "Skill with passing tests",
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (skill_dir / "prompt.md").write_text("Be helpful.\n", encoding="utf-8")
    # 通过测试的测试代码 (设置 result 变量)
    (skill_dir / "tests.py").write_text(
        "assert 1 + 1 == 2\nresult = 'tests_ok'\n",
        encoding="utf-8",
    )
    return skill_id


@pytest.fixture
def skill_with_failing_tests(tmp_skills_dir):
    """创建带失败测试用例的技能包."""
    skill_id = "skill-failing-tests"
    skill_dir = tmp_skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": skill_id,
        "version": "0.1.0",
        "component": None,
        "prompt": "prompt.md",
        "tools": [],
        "dependencies": [],
        "author": "tester",
        "charter_compatible": True,
        "description": "Skill with failing tests",
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (skill_dir / "prompt.md").write_text("Be careful.\n", encoding="utf-8")
    # 失败测试
    (skill_dir / "tests.py").write_text(
        "assert 1 + 1 == 3, 'intentional failure'\n",
        encoding="utf-8",
    )
    return skill_id


class _FakeSandbox:
    """可控 mock sandbox: 根据 should_pass 返回成功/失败结果.

    保留所有调用记录供测试断言.
    """

    def __init__(self, should_pass: bool = True):
        self.should_pass = should_pass
        self.calls: List[Dict[str, Any]] = []

    def run_code(self, code: str, context: dict = None) -> dict:
        self.calls.append({"code": code, "context": context})
        if self.should_pass:
            return {
                "success": True,
                "stdout": "__SANDBOX_OK__\nresult = 'tests_ok'",
                "stderr": "",
                "exit_code": 0,
                "timeout": False,
            }
        return {
            "success": False,
            "stdout": "",
            "stderr": "AssertionError: intentional failure",
            "exit_code": 1,
            "timeout": False,
        }


@pytest.fixture
def fresh_manager():
    """每个测试独立的 SkillSyncManager (使用全局单例 reset)."""
    mgr = reset_skill_sync_manager_for_test(auto_advance=False)
    yield mgr
    # 测试后清理
    reset_skill_sync_manager_for_test()


@pytest.fixture
def auto_manager():
    """auto_advance=True 的 SkillSyncManager."""
    mgr = reset_skill_sync_manager_for_test(auto_advance=True)
    yield mgr
    reset_skill_sync_manager_for_test()


# ──────────────────────────────────────────────────────────────────────
# 模板降级路径单元测试
# ──────────────────────────────────────────────────────────────────────


def test_template_describe_skill_basic():
    """模板生成技能语义描述应包含 manifest 关键字段."""
    manifest = {
        "name": "demo-skill",
        "version": "1.0.0",
        "component": "component.tsx",
        "prompt": "prompt.md",
        "description": "A demo skill",
    }
    desc = _template_describe_skill(manifest, "component code", "prompt text", ["t1"])
    assert "demo-skill" in desc
    assert "1.0.0" in desc
    assert "A demo skill" in desc
    assert "t1" in desc


def test_template_adapt_prompt_no_personality_returns_original():
    """无性格时, 模板适配应原样返回提示词."""
    original = "Review code."
    assert _template_adapt_prompt(original, "") == original
    assert _template_adapt_prompt(original, "   ") == original


def test_template_adapt_prompt_playful_personality_adds_prefix():
    """活泼性格应在原提示词前加活泼风格修饰."""
    original = "Review code."
    adapted = _template_adapt_prompt(original, "性格: 活泼, 童趣")
    assert adapted != original
    assert "活泼" in adapted or "轻松" in adapted
    assert original in adapted  # 原文应保留在后


def test_template_adapt_prompt_architect_personality_uses_architect_style():
    """架构师性格应使用架构视角修饰."""
    original = "Help with task."
    adapted = _template_adapt_prompt(original, "I am an architect.")
    assert adapted != original
    assert "架构" in adapted or "architect" in adapted.lower()


def test_template_adapt_prompt_unknown_personality_adds_generic_prefix():
    """未匹配关键词的性格应使用通用修饰前缀."""
    original = "Do work."
    adapted = _template_adapt_prompt(original, "xyz unknown style")
    assert adapted != original
    assert original in adapted


def test_load_agent_personality_missing_agent_returns_empty():
    """无 ishiki.md 的 agent 应返回空字符串."""
    assert load_agent_personality("nonexistent-agent-xyz") == ""
    assert load_agent_personality("") == ""


# ──────────────────────────────────────────────────────────────────────
# SubTask 3.7: 四步状态机端到端测试
# ──────────────────────────────────────────────────────────────────────


def test_sync_skill_full_pipeline_adopted(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """完整四步状态机: understanding -> adapting -> testing -> adopting -> adopted."""
    # 注入成功 sandbox
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)

    job_id = fresh_manager.sync_skill(
        peer_public_key="peer_pk_test_abc",
        skill_id=sample_skill,
        target_agent="test-adopter",
        personality_override="性格: 严谨专业",
        auto_advance=False,
    )
    # 初始状态: understanding (步骤 1 已执行)
    job = fresh_manager.get_job(job_id)
    assert job is not None
    assert job["state"] == "understanding"
    assert job["current_step"] == 1
    assert job["peer_public_key"] == "peer_pk_test_abc"
    assert job["skill_id"] == sample_skill
    assert job["target_agent"] == "test-adopter"
    # understanding 产物已生成
    ua = job["understanding_artifact"]
    assert "manifest" in ua
    assert "semantic_description" in ua
    assert ua["method"] in ("template", "llm")
    assert "grounding" in ua
    assert "state" in ua["grounding"]

    # 推进到 adapting
    r = fresh_manager.advance(job_id)
    assert r["state"] == "adapting"
    assert r["current_step"] == 2
    aa = r["adapting_artifact"]
    assert "original_prompt" in aa
    assert "adapted_prompt" in aa
    assert aa["style_changed"] is True  # personality 严谨应触发风格变更
    assert aa["personality_summary"]

    # 推进到 testing
    r = fresh_manager.advance(job_id)
    assert r["state"] == "testing"
    assert r["current_step"] == 3
    ta = r["testing_artifact"]
    assert ta["passed"] is True
    assert ta["test_count"] >= 1

    # 推进到 adopting
    r = fresh_manager.advance(job_id)
    assert r["state"] == "adopting"
    assert r["current_step"] == 4

    # 推进到 adopted 终态
    r = fresh_manager.advance(job_id)
    assert r["state"] == "adopted"
    assert r["current_step"] == 5
    oa = r["adopting_artifact"]
    assert oa["installed"] is True
    assert oa["skill_id"] == sample_skill
    assert oa["agent_name"] == "test-adopter"
    assert r["error"] == ""


def test_sync_skill_auto_advance_adopted(
    auto_manager, sample_skill, tmp_vault_dir,
):
    """auto_advance=True (默认) 应一次性跑到 adopted."""
    auto_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)

    job_id = auto_manager.sync_skill(
        peer_public_key="peer_pk_auto",
        skill_id=sample_skill,
        target_agent="auto-adopter",
        personality_override="playful personality",
    )
    job = auto_manager.get_job(job_id)
    assert job is not None
    assert job["state"] == "adopted"
    assert job["current_step"] == 5
    assert job["error"] == ""
    # 所有步骤产物都已填充
    assert job["understanding_artifact"]
    assert job["adapting_artifact"]
    assert job["testing_artifact"]
    assert job["adopting_artifact"]


def test_sync_skill_sandbox_failure_rolls_back(
    fresh_manager, skill_with_failing_tests, tmp_vault_dir,
):
    """沙箱测试失败应转 rolled_back, 且不写入 vault."""
    # 使用真实 Sandbox (会执行 tests.py 并失败)
    # 但为加速测试, 注入失败 fake sandbox
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=False)

    job_id = fresh_manager.sync_skill(
        peer_public_key="peer_pk_fail",
        skill_id=skill_with_failing_tests,
        target_agent="fail-adopter",
        personality_override="",
        auto_advance=True,
    )
    job = fresh_manager.get_job(job_id)
    assert job is not None
    assert job["state"] == "rolled_back"
    assert "testing failed" in job["error"]
    # adopting 步骤未执行, 无 install
    assert job["adopting_artifact"] == {}
    # 不应写入 vault (检查 installed_skills 表为空)
    from laap.skills.pack_manager import list_installed
    installed = list_installed("fail-adopter")
    assert installed == []


def test_sync_skill_idempotent_inflight(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """同一 (peer_pk, skill_id, agent) 进行中重复调用返回同一 job_id."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    fresh_manager._auto_advance = False  # 让任务停在 understanding

    job_id_1 = fresh_manager.sync_skill(
        peer_public_key="peer_pk_idem",
        skill_id=sample_skill,
        target_agent="idem-agent",
        auto_advance=False,
    )
    job_id_2 = fresh_manager.sync_skill(
        peer_public_key="peer_pk_idem",
        skill_id=sample_skill,
        target_agent="idem-agent",
        auto_advance=False,
    )
    assert job_id_1 == job_id_2


def test_sync_skill_terminal_can_rerun(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """终态 (adopted) 任务可重新创建新 job_id 重跑."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)

    job_id_1 = fresh_manager.sync_skill(
        peer_public_key="peer_pk_rerun",
        skill_id=sample_skill,
        target_agent="rerun-agent",
        auto_advance=True,
    )
    assert fresh_manager.get_job(job_id_1)["state"] == "adopted"

    # 重跑: 应得到新 job_id
    job_id_2 = fresh_manager.sync_skill(
        peer_public_key="peer_pk_rerun",
        skill_id=sample_skill,
        target_agent="rerun-agent",
        auto_advance=True,
    )
    assert job_id_2 != job_id_1
    assert fresh_manager.get_job(job_id_2)["state"] == "adopted"


def test_sync_skill_missing_skill_raises_file_not_found(fresh_manager):
    """不存在的 skill_id 应抛 FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        fresh_manager.sync_skill(
            peer_public_key="pk",
            skill_id="nonexistent-skill-xyz",
            target_agent="agent",
        )


def test_sync_skill_empty_params_raises_value_error(fresh_manager):
    """空 peer_public_key / skill_id / target_agent 应抛 ValueError."""
    with pytest.raises(ValueError, match="peer_public_key"):
        fresh_manager.sync_skill("", "skill", "agent")
    with pytest.raises(ValueError, match="skill_id"):
        fresh_manager.sync_skill("pk", "", "agent")
    with pytest.raises(ValueError, match="target_agent"):
        fresh_manager.sync_skill("pk", "skill", "")


# ──────────────────────────────────────────────────────────────────────
# SubTask 3.7: 性格适配差异测试
# ──────────────────────────────────────────────────────────────────────


def test_personality_adaptation_differs(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """不同性格应产生不同 adapted_prompt (LLM 不可用时走模板降级)."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)

    # 性格 A: 活泼
    job_a = fresh_manager.sync_skill(
        peer_public_key="pk_a",
        skill_id=sample_skill,
        target_agent="agent_a",
        personality_override="性格活泼, 童趣",
        auto_advance=False,
    )
    fresh_manager.advance(job_a)  # 推进到 adapting, 执行步骤 2
    adapting_a = fresh_manager.get_job(job_a)["adapting_artifact"]

    # 性格 B: 严谨
    fresh_manager.reset_for_test()
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    job_b = fresh_manager.sync_skill(
        peer_public_key="pk_b",
        skill_id=sample_skill,
        target_agent="agent_b",
        personality_override="性格严谨专业",
        auto_advance=False,
    )
    fresh_manager.advance(job_b)
    adapting_b = fresh_manager.get_job(job_b)["adapting_artifact"]

    # 两次 adapted_prompt 应不同 (因为性格不同, 模板修饰前缀不同)
    assert adapting_a["adapted_prompt"] != adapting_b["adapted_prompt"]
    # 都与原 prompt 不同
    assert adapting_a["adapted_prompt"] != adapting_a["original_prompt"]
    assert adapting_b["adapted_prompt"] != adapting_b["original_prompt"]
    # 风格变更标记
    assert adapting_a["style_changed"] is True
    assert adapting_b["style_changed"] is True


def test_no_personality_keeps_original_prompt(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """空性格应保持原提示词不变 (style_changed=False)."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    job_id = fresh_manager.sync_skill(
        peer_public_key="pk",
        skill_id=sample_skill,
        target_agent="no-personality-agent",
        personality_override="",
        auto_advance=False,
    )
    fresh_manager.advance(job_id)  # 到 adapting
    adapting = fresh_manager.get_job(job_id)["adapting_artifact"]
    assert adapting["adapted_prompt"] == adapting["original_prompt"]
    assert adapting["style_changed"] is False


# ──────────────────────────────────────────────────────────────────────
# SubTask 3.7: 沙箱测试用例读取测试
# ──────────────────────────────────────────────────────────────────────


def test_skill_with_tests_uses_tests_py(
    fresh_manager, skill_with_tests, tmp_vault_dir,
):
    """带 tests.py 的技能应使用该文件作为测试源."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    job_id = fresh_manager.sync_skill(
        peer_public_key="pk",
        skill_id=skill_with_tests,
        target_agent="test-agent",
        auto_advance=False,
    )
    fresh_manager.advance(job_id)  # adapting
    r = fresh_manager.advance(job_id)  # testing
    ta = r["testing_artifact"]
    assert ta["test_source"] == "tests.py"
    assert ta["test_count"] >= 1
    assert ta["passed"] is True


def test_skill_without_tests_uses_smoke(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """无测试文件的技能应使用冒烟测试 (manifest 合法性)."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    job_id = fresh_manager.sync_skill(
        peer_public_key="pk",
        skill_id=sample_skill,
        target_agent="smoke-agent",
        auto_advance=False,
    )
    fresh_manager.advance(job_id)  # adapting
    r = fresh_manager.advance(job_id)  # testing
    ta = r["testing_artifact"]
    assert ta["test_source"] == "(smoke)"
    assert ta["test_count"] == 1


# ──────────────────────────────────────────────────────────────────────
# 查询接口测试
# ──────────────────────────────────────────────────────────────────────


def test_list_jobs_state_filter(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """list_jobs 状态过滤应正确分类."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)

    # 创建 2 个 adopted 任务 + 1 个 rolled_back 任务
    fresh_manager.sync_skill(
        peer_public_key="pk1", skill_id=sample_skill,
        target_agent="a1", auto_advance=True,
    )
    fresh_manager.sync_skill(
        peer_public_key="pk2", skill_id=sample_skill,
        target_agent="a2", auto_advance=True,
    )
    # 第三个用失败 sandbox 制造 rolled_back
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=False)
    fresh_manager.sync_skill(
        peer_public_key="pk3", skill_id=sample_skill,
        target_agent="a3", auto_advance=True,
    )

    all_jobs = fresh_manager.list_jobs()
    assert len(all_jobs) == 3

    adopted = fresh_manager.list_jobs(state_filter="adopted")
    assert len(adopted) == 2
    assert all(j["state"] == "adopted" for j in adopted)

    rolled = fresh_manager.list_jobs(state_filter="rolled_back")
    assert len(rolled) == 1
    assert rolled[0]["state"] == "rolled_back"

    # 不存在的状态过滤返回空
    empty = fresh_manager.list_jobs(state_filter="nonexistent")
    assert empty == []


def test_get_job_not_found(fresh_manager):
    """不存在的 job_id 应返回 None."""
    assert fresh_manager.get_job("sync_nonexistent") is None


def test_advance_unknown_job_returns_error(fresh_manager):
    """advance 不存在的 job_id 应返回 error dict, 不抛异常."""
    result = fresh_manager.advance("sync_unknown")
    assert "error" in result
    assert "sync_job not found" in result["error"]


def test_advance_terminal_job_no_op(
    fresh_manager, sample_skill, tmp_vault_dir,
):
    """终态任务 advance 应返回当前状态, 不抛异常."""
    fresh_manager._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    job_id = fresh_manager.sync_skill(
        peer_public_key="pk", skill_id=sample_skill,
        target_agent="a", auto_advance=True,
    )
    assert fresh_manager.get_job(job_id)["state"] == "adopted"
    # advance 终态: 不变
    r = fresh_manager.advance(job_id)
    assert r["state"] == "adopted"


# ──────────────────────────────────────────────────────────────────────
# 桥接函数 handle_skill_sync_* 测试
# ──────────────────────────────────────────────────────────────────────


def test_handle_skill_sync_start_invalid_params():
    """handle_skill_sync_start 空参数应返回 synced=False."""
    r = json.loads(handle_skill_sync_start("", "skill", "agent"))
    assert r["synced"] is False
    assert "peer_public_key" in r["error"]

    r = json.loads(handle_skill_sync_start("pk", "", "agent"))
    assert r["synced"] is False

    r = json.loads(handle_skill_sync_start("pk", "skill", ""))
    assert r["synced"] is False


def test_handle_skill_sync_start_success(
    monkeypatch, sample_skill, tmp_vault_dir,
):
    """handle_skill_sync_start 成功路径应返回 synced=True + job 信息."""
    # 重置全局单例
    mgr = reset_skill_sync_manager_for_test(auto_advance=True)
    mgr._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    try:
        r_str = handle_skill_sync_start(
            peer_public_key="pk_bridge",
            skill_id=sample_skill,
            target_agent="bridge-agent",
            personality_override="playful",
        )
        r = json.loads(r_str)
        assert r["synced"] is True
        assert r["state"] == "adopted"
        assert r["skill_id"] == sample_skill
        assert r["target_agent"] == "bridge-agent"
        assert r["peer_public_key"] == "pk_bridge"
        assert "sync_job_id" in r
    finally:
        reset_skill_sync_manager_for_test()


def test_handle_skill_sync_start_skill_not_found():
    """不存在的 skill 应返回 synced=False + skill not found."""
    reset_skill_sync_manager_for_test()
    r = json.loads(handle_skill_sync_start(
        peer_public_key="pk",
        skill_id="definitely-nonexistent-skill-xyz",
        target_agent="agent",
    ))
    assert r["synced"] is False
    assert "skill not found" in r["error"] or "not found" in r["error"]
    reset_skill_sync_manager_for_test()


def test_handle_skill_sync_status_not_found():
    """status 查询不存在 job 应返回 error."""
    r = json.loads(handle_skill_sync_status("sync_nonexistent_xyz"))
    assert "error" in r
    assert "sync_job not found" in r["error"]


def test_handle_skill_sync_status_empty_id():
    """status 空 ID 应返回错误."""
    r = json.loads(handle_skill_sync_status(""))
    assert "error" in r


def test_handle_skill_sync_list_empty():
    """无任务时 list 返回空数组."""
    reset_skill_sync_manager_for_test()
    r = json.loads(handle_skill_sync_list())
    assert r["count"] == 0
    assert r["jobs"] == []
    reset_skill_sync_manager_for_test()


def test_handle_skill_sync_list_with_jobs(
    monkeypatch, sample_skill, tmp_vault_dir,
):
    """list 端点应返回创建的任务."""
    mgr = reset_skill_sync_manager_for_test(auto_advance=True)
    mgr._sandbox_factory = lambda: _FakeSandbox(should_pass=True)
    try:
        handle_skill_sync_start(
            peer_public_key="pk1", skill_id=sample_skill,
            target_agent="agent1", personality_override="",
        )
        handle_skill_sync_start(
            peer_public_key="pk2", skill_id=sample_skill,
            target_agent="agent2", personality_override="",
        )
        r = json.loads(handle_skill_sync_list())
        assert r["count"] == 2
        assert all("sync_job_id" in j for j in r["jobs"])
    finally:
        reset_skill_sync_manager_for_test()


def test_handle_skill_sync_advance_unknown_job():
    """advance 不存在 job 应返回 advanced=False."""
    r = json.loads(handle_skill_sync_advance("sync_nonexistent"))
    assert "error" in r
    assert "sync_job not found" in r["error"]


def test_handle_skill_sync_advance_empty_id():
    """advance 空 ID 应返回 advanced=False."""
    r = json.loads(handle_skill_sync_advance(""))
    assert r["advanced"] is False
    assert "error" in r


# ──────────────────────────────────────────────────────────────────────
# 真实 Sandbox 集成测试 (慢, 但验证实际执行路径)
# ──────────────────────────────────────────────────────────────────────


def test_real_sandbox_passing_tests(skill_with_tests, tmp_vault_dir):
    """使用真实 Sandbox 执行带 tests.py 的技能, 应通过."""
    mgr = reset_skill_sync_manager_for_test(auto_advance=True)
    # 不注入 sandbox_factory, 使用默认真实 Sandbox
    try:
        job_id = mgr.sync_skill(
            peer_public_key="pk_real",
            skill_id=skill_with_tests,
            target_agent="real-test-agent",
            personality_override="",
        )
        job = mgr.get_job(job_id)
        assert job["state"] == "adopted"
        assert job["testing_artifact"]["passed"] is True
        assert job["testing_artifact"]["test_source"] == "tests.py"
    finally:
        reset_skill_sync_manager_for_test()


def test_real_sandbox_smoke_test_passes(sample_skill, tmp_vault_dir):
    """无 tests.py 的技能用真实 Sandbox 跑冒烟测试, 应通过."""
    mgr = reset_skill_sync_manager_for_test(auto_advance=True)
    try:
        job_id = mgr.sync_skill(
            peer_public_key="pk_smoke",
            skill_id=sample_skill,
            target_agent="smoke-real-agent",
            personality_override="",
        )
        job = mgr.get_job(job_id)
        assert job["state"] == "adopted"
        assert job["testing_artifact"]["test_source"] == "(smoke)"
    finally:
        reset_skill_sync_manager_for_test()


# ──────────────────────────────────────────────────────────────────────
# 全局单例测试
# ──────────────────────────────────────────────────────────────────────


def test_get_skill_sync_manager_singleton():
    """get_skill_sync_manager 应返回同一实例."""
    reset_skill_sync_manager_for_test()
    m1 = get_skill_sync_manager()
    m2 = get_skill_sync_manager()
    assert m1 is m2
    reset_skill_sync_manager_for_test()


def test_reset_for_test_clears_jobs():
    """reset_for_test 应清空所有任务."""
    mgr = reset_skill_sync_manager_for_test()
    # 直接造一个 job 进 _jobs
    from laap.skills.sync import SkillSyncJob
    fake_id = "sync_fake"
    mgr._jobs[fake_id] = SkillSyncJob(
        sync_job_id=fake_id,
        peer_public_key="pk",
        skill_id="x",
        target_agent="a",
    )
    assert len(mgr._jobs) == 1
    mgr.reset_for_test()
    assert len(mgr._jobs) == 0
    assert len(mgr._idempotency) == 0
