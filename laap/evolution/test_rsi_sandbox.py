"""
P1-rsi-sandbox 测试套件 — RSI 沙箱建议模式完整闭环

测试覆盖（与 checklist.md L50-L59 对齐）：
1. ``RSISandbox.propose`` 完整闭环（变异→沙箱→grounding→宪章→决策）
2. 宪章八条检查：违反 → 候选直接拒绝，不进入绩效评估
3. grounding 失败 → 候选归档，不进入绩效评估
4. 沙箱失败 → 候选归档
5. 路径白名单：target_module 不在 laap/ 内 → 归档；黑名单 → 归档
6. 用户决策路径：adopt 应用 patch + 写见证迹；reject 归档；archive 归档
7. 幂等性：重复 decide 同 action 返回相同结果
8. ``rsi_status`` 查询候选状态
9. ``register_rsi_tools`` MCP 工具注册 + 调用
10. ``propose_candidate`` / ``decide_candidate`` / ``get_status`` 桥接函数

运行方式：

    python -m pytest laap/evolution/test_rsi_sandbox.py -v

印记: Aris 永远记得 Lorry — RSI 测试只跑在自己的代码上。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ─── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def tmp_vault_dir():
    """每个测试用例使用独立的临时 vault 目录，测试后自动清理。"""
    d = tempfile.mkdtemp(prefix="laap_rsi_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_repo_root():
    """临时仓库根目录，包含 laap/ 子树供 RSI 写入 patch。"""
    d = tempfile.mkdtemp(prefix="laap_rsi_repo_")
    laap_root = os.path.join(d, "laap")
    tools_dir = os.path.join(laap_root, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    # 写入一个占位目标文件，供 adopt 时追加 patch
    target_file = os.path.join(tools_dir, "example.py")
    with open(target_file, "w", encoding="utf-8") as f:
        f.write("# Example tool module\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sandbox_instance(tmp_vault_dir, tmp_repo_root):
    """每个测试用例独立的 RSISandbox 实例。

    Vault 目录被 monkeypatch 到 tmp_vault_dir，repo_root 指向 tmp_repo_root。
    同时清空 rsi_mcp_tools 的 sandbox 缓存。
    """
    # 复位 rsi_mcp_tools 的 sandbox 缓存
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    # 复位 truth_grounding_mcp_tools 的单例缓存
    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    # monkeypatch vault_manager 的 vault_dir
    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original_vault_dir = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    # 清空 vault cache
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    from laap.evolution.true_rsi import RSISandbox
    sb = RSISandbox(repo_root=tmp_repo_root, agent_name="aris_test")

    yield sb

    # 清理：恢复 vault_dir（vm_mod 已是 vault_manager 实例本身）
    vm_mod.vault_dir = original_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()
    rsi_mcp_tools._reset_sandboxes_for_test()
    truth_grounding_mcp_tools._reset_singletons_for_test()


# ─── 辅助：让 grounding 通过 / 失败 ──────────────────────────

def _make_grounding_pass(*args, **kwargs):
    """让 ground_candidate_description 返回 grounding 通过。"""
    return {
        "state": "grounded",
        "confidence": 0.92,
        "evidence": ["test_stub"],
        "rejected": False,
    }


def _make_grounding_fail(*args, **kwargs):
    """让 ground_candidate_description 返回 grounding 失败。"""
    return {
        "state": "error",
        "confidence": 0.1,
        "evidence": ["conflict_with_known_fact"],
        "rejected": True,
        "conflicts": ["与已知事实冲突"],
    }


def _make_safe_diff(*args, **kwargs):
    """生成不含违反模式的 patch。"""
    diff = (
        "# RSI optimization (fitness_signal=0.4)\n"
        "# target: laap/tools/example.py\n"
        "# 变异类型: param_drift\n"
        "def _rsi_optimized_default():\n"
        "    return {'optimized': True, 'source': 'rsi_sandbox'}\n"
    )
    desc = "RSI 候选: 在 laap/tools/example.py 中应用 param_drift 变异。"
    return diff, desc


def _make_charter_violating_diff(*args, **kwargs):
    """生成含宪章违反模式的 patch（os.system 触发 safety 违反）。"""
    diff = (
        "# RSI optimization (fitness_signal=0.4)\n"
        "# target: laap/tools/example.py\n"
        "import os\n"
        "def _rsi_dangerous():\n"
        "    os.system('rm -rf /tmp/laap_test')\n"
        "    return {'dangerous': True}\n"
    )
    desc = "RSI 候选: 危险的 os.system 调用（应被宪章拒绝）。"
    return diff, desc


def _make_sandbox_fail(self, candidate):
    """让 _run_sandbox 返回失败。"""
    return {
        "success": False,
        "syntax_ok": False,
        "safety_ok": False,
        "error": "test_injected_syntax_error",
    }


def _make_sandbox_pass(self, candidate):
    """让 _run_sandbox 返回成功（用于绕过沙箱危险模式检查，测试下游阶段）。"""
    return {
        "success": True,
        "syntax_ok": True,
        "safety_ok": True,
        "error": "",
    }


# ─── 1. 完整闭环 suggest_adopt ────────────────────────────────

def test_propose_full_closed_loop_suggest_adopt(sandbox_instance):
    """propose 完整闭环：sandbox 通过 + grounding 通过 + 宪章通过 → suggest_adopt。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)
    # candidate_id 必须以 rsi_ 开头
    assert cid.startswith("rsi_")
    # 查询状态
    status = sb.status(cid)
    assert status["candidate_id"] == cid
    assert status["target_module"] == "laap/tools/example.py"
    assert status["decision"] == "suggest_adopt"
    assert status["status"] == "suggest_adopt"
    assert status["fitness_signal"] == 0.4
    # sandbox 通过
    assert status["sandbox_result"]["success"] is True
    # grounding 通过且未 rejected
    assert status["grounding"]["rejected"] is False
    assert status["grounding"]["state"] == "grounded"
    # 宪章通过
    assert status["charter_report"]["charter_compatible"] is True
    assert status["charter_report"]["violations"] == []
    # fitness_score 为正
    assert status["fitness_score"] > 0.0


# ─── 2. 路径白名单：target_module 不在 laap/ 内 → 归档 ────────

def test_propose_invalid_target_module_archived(sandbox_instance):
    """target_module 不以 laap/ 开头 → 候选归档。"""
    sb = sandbox_instance
    cid = sb.propose("hanako/core/server.ts", 0.4)
    status = sb.status(cid)
    assert status["status"] == "archived"
    assert status["decision"] == "archive"
    assert "not in allowed prefixes" in status["sandbox_result"]["error"]


def test_propose_blacklist_target_module_archived(sandbox_instance):
    """target_module 命中黑名单（laap/security/）→ 候选归档。"""
    sb = sandbox_instance
    cid = sb.propose("laap/security/keys.py", 0.4)
    status = sb.status(cid)
    assert status["status"] == "archived"
    assert status["decision"] == "archive"
    assert "blacklist" in status["sandbox_result"]["error"]


def test_propose_rsi_mcp_tools_self_blacklisted(sandbox_instance):
    """RSI 不得修改自身代码（laap/evolution/rsi_mcp_tools）→ 归档。"""
    sb = sandbox_instance
    cid = sb.propose("laap/evolution/rsi_mcp_tools.py", 0.4)
    status = sb.status(cid)
    assert status["status"] == "archived"
    assert "blacklist" in status["sandbox_result"]["error"]


# ─── 3. 沙箱失败 → 归档 ───────────────────────────────────────

def test_propose_sandbox_failure_archived(sandbox_instance):
    """沙箱校验失败 → 候选归档，不进入 grounding/charter。"""
    sb = sandbox_instance
    with patch(
        "laap.evolution.true_rsi.RSISandbox._run_sandbox",
        new=_make_sandbox_fail,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)
    status = sb.status(cid)
    assert status["status"] == "sandbox_failed"
    assert status["decision"] == "archive"
    # sandbox 失败时不应该执行 grounding
    assert status["grounding"] == {}
    # 也不应该执行 charter 检查
    assert status["charter_report"] == {}


# ─── 4. grounding 失败 → 归档 ─────────────────────────────────

def test_propose_grounding_failure_archived(sandbox_instance):
    """grounding rejected=True → 候选归档，不进入宪章检查。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_fail,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)
    status = sb.status(cid)
    assert status["status"] == "grounding_rejected"
    assert status["decision"] == "archive"
    # grounding 应该返回 rejected=True
    assert status["grounding"]["rejected"] is True
    assert status["grounding"]["state"] == "error"
    # grounding 失败时不应该执行 charter 检查
    assert status["charter_report"] == {}


# ─── 5. 宪章违反 → 拒绝 ────────────────────────────────────────

def test_propose_charter_violation_rejected(sandbox_instance):
    """候选含宪章违反模式（os.system）→ charter_rejected，不进入绩效评估。

    验证 checklist：宪章违反的候选被拒绝，不进入绩效评估。
    注意：os.system 同时被沙箱危险模式与宪章 safety 条目拦截。为独立验证
    宪章检查阶段，本测试 patch _run_sandbox 强制通过，使候选能到达宪章
    检查阶段（沙箱拦截行为由 test_propose_sandbox_failure_archived 覆盖）。
    """
    sb = sandbox_instance
    # monkeypatch _generate_candidate 返回含 os.system 的危险 patch
    with patch(
        "laap.evolution.true_rsi.RSISandbox._generate_candidate",
        side_effect=_make_charter_violating_diff,
    ), patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ), patch(
        "laap.evolution.true_rsi.RSISandbox._run_sandbox",
        new=_make_sandbox_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)
    status = sb.status(cid)
    assert status["status"] == "charter_rejected"
    assert status["decision"] == "reject"
    # 应该有 safety 违反
    violations = status["charter_report"]["violations"]
    assert len(violations) > 0
    violation_ids = [v["article_id"] for v in violations]
    assert "safety" in violation_ids
    # charter 不通过
    assert status["charter_report"]["charter_compatible"] is False


def test_charter_checker_directly_detects_safety_violation():
    """CharterChecker 直接调用：os.system 应被识别为 safety 违反。"""
    from laap.evolution.charter_checker import CharterChecker
    checker = CharterChecker()
    diff = "import os\nos.system('rm -rf /tmp')"
    result = checker.audit(diff)
    assert result["charter_compatible"] is False
    article_ids = [v["article_id"] for v in result["violations"]]
    assert "safety" in article_ids


def test_charter_checker_passes_clean_patch():
    """CharterChecker 对干净 patch 返回 charter_compatible=True。"""
    from laap.evolution.charter_checker import CharterChecker
    checker = CharterChecker()
    diff = (
        "# RSI optimization\n"
        "def _rsi_optimized_default():\n"
        "    return {'optimized': True}\n"
    )
    result = checker.audit(diff)
    assert result["charter_compatible"] is True
    assert result["violations"] == []
    # 八条都被检查
    assert result["articles_checked"] == 8


def test_charter_checker_privacy_violation():
    """CharterChecker 识别 privacy 违反（触及用户数据路径）。"""
    from laap.evolution.charter_checker import CharterChecker
    checker = CharterChecker()
    diff = "open('users_data/profile.json')"
    result = checker.audit(diff)
    assert result["charter_compatible"] is False
    article_ids = [v["article_id"] for v in result["violations"]]
    assert "privacy" in article_ids


# ─── 6. 用户决策路径 ──────────────────────────────────────────

def test_decide_adopt_applies_patch_and_writes_witness_trail(
    sandbox_instance, tmp_repo_root,
):
    """decide(adopt) 应用 patch 到目标文件，并写入 witness_trail_local 表。"""
    sb = sandbox_instance
    target_file = os.path.join(tmp_repo_root, "laap", "tools", "example.py")

    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    # 文件此时应该还是原始内容
    with open(target_file, "r", encoding="utf-8") as f:
        original = f.read()
    assert "RSI Patch" not in original

    # 用户采纳
    result = sb.decide(cid, "adopt", decided_by="test_user")
    assert result["decided"] is True
    assert result["action"] == "adopt"
    assert result["applied"] is True
    assert result["witness_trail_id"].startswith("wit_")

    # 文件应该已被追加 patch
    with open(target_file, "r", encoding="utf-8") as f:
        patched = f.read()
    assert "RSI Patch" in patched
    assert cid in patched
    assert "_rsi_optimized_default" in patched

    # 候选状态应为 adopted
    status = sb.status(cid)
    assert status["status"] == "adopted"
    assert status["decision"] == "adopt"
    assert status["decided_by"] == "test_user"


def test_decide_reject(sandbox_instance):
    """decide(reject) 把候选标记为 rejected，不应用 patch。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    result = sb.decide(cid, "reject")
    assert result["decided"] is True
    assert result["action"] == "reject"
    assert result["status"] == "rejected"

    status = sb.status(cid)
    assert status["status"] == "rejected"
    assert status["decision"] == "reject"


def test_decide_archive(sandbox_instance):
    """decide(archive) 把候选标记为 archived，不应用 patch。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    result = sb.decide(cid, "archive")
    assert result["decided"] is True
    assert result["action"] == "archive"
    assert result["status"] == "archived"


def test_decide_unknown_action_returns_error(sandbox_instance):
    """decide(unknown_action) 返回 error，decided=False。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    result = sb.decide(cid, "unknown")
    assert result["decided"] is False
    assert "unknown action" in result["error"]


def test_decide_nonexistent_candidate(sandbox_instance):
    """decide 不存在的 candidate_id 返回 error。"""
    sb = sandbox_instance
    result = sb.decide("rsi_nonexistent_id", "adopt")
    assert result["decided"] is False
    assert result["error"] == "candidate not found"


# ─── 7. 幂等性 ────────────────────────────────────────────────

def test_decide_idempotent_same_action(sandbox_instance):
    """重复 decide 同 (candidate_id, action) 返回相同结果。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    r1 = sb.decide(cid, "reject")
    r2 = sb.decide(cid, "reject")
    assert r1 == r2
    assert r1["decided"] is True


def test_decide_already_decided_different_action_blocked(sandbox_instance):
    """已 decided 的候选不能再改 action（terminal 状态保护）。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    # 先 reject
    r1 = sb.decide(cid, "reject")
    assert r1["decided"] is True
    # 再尝试 adopt → 应该被拒绝
    r2 = sb.decide(cid, "adopt")
    assert r2["decided"] is False
    assert "already in terminal status" in r2["error"]


# ─── 8. status 查询 ───────────────────────────────────────────

def test_status_not_found(sandbox_instance):
    """查询不存在的 candidate_id 返回 {error: not found}。"""
    sb = sandbox_instance
    result = sb.status("rsi_nonexistent_id")
    assert result["error"] == "not found"
    assert result["candidate_id"] == "rsi_nonexistent_id"


def test_status_returns_full_state(sandbox_instance):
    """status 返回完整状态 dict（含 grounding / charter_report / decision）。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    status = sb.status(cid)
    # 检查所有关键字段
    assert status["candidate_id"] == cid
    assert "target_module" in status
    assert "fitness_signal" in status
    assert "candidate_diff" in status
    assert "description" in status
    assert "sandbox_result" in status
    assert "grounding" in status
    assert "charter_report" in status
    assert "fitness_score" in status
    assert "decision" in status
    assert "status" in status
    assert "agent_name" in status


# ─── 9. rsi_mcp_tools 桥接函数 ────────────────────────────────

def test_propose_candidate_bridge_returns_full_dict(tmp_vault_dir, tmp_repo_root):
    """propose_candidate 桥接函数返回完整候选 dict。"""
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    try:
        with patch(
            "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
            side_effect=_make_grounding_pass,
        ):
            result = rsi_mcp_tools.propose_candidate(
                target_module="laap/tools/example.py",
                fitness_signal=0.4,
                agent_name="aris_test",
            )
        assert result["candidate_id"].startswith("rsi_")
        assert result["decision"] == "suggest_adopt"
        assert result["target_module"] == "laap/tools/example.py"
        # 通过桥接函数拿 status 应该一致
        status = rsi_mcp_tools.get_status(
            result["candidate_id"], agent_name="aris_test",
        )
        assert status["candidate_id"] == result["candidate_id"]
    finally:
        vm_mod.vault_dir = original
        with vm_mod._cache_lock:
            vm_mod._vault_cache.clear()
        rsi_mcp_tools._reset_sandboxes_for_test()
        truth_grounding_mcp_tools._reset_singletons_for_test()


def test_decide_candidate_bridge(tmp_vault_dir, tmp_repo_root):
    """decide_candidate 桥接函数完整决策路径。"""
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    try:
        with patch(
            "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
            side_effect=_make_grounding_pass,
        ):
            r = rsi_mcp_tools.propose_candidate(
                target_module="laap/tools/example.py",
                fitness_signal=0.4,
                agent_name="aris_test",
            )
            cid = r["candidate_id"]

        # 通过桥接函数 reject
        result = rsi_mcp_tools.decide_candidate(
            candidate_id=cid,
            action="reject",
            decided_by="test_user",
            agent_name="aris_test",
        )
        assert result["decided"] is True
        assert result["action"] == "reject"
        assert result["status"] == "rejected"
    finally:
        vm_mod.vault_dir = original
        with vm_mod._cache_lock:
            vm_mod._vault_cache.clear()
        rsi_mcp_tools._reset_sandboxes_for_test()
        truth_grounding_mcp_tools._reset_singletons_for_test()


def test_get_status_bridge_returns_error_on_not_found(tmp_vault_dir):
    """get_status 桥接函数对不存在的候选返回 error。"""
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    try:
        result = rsi_mcp_tools.get_status(
            "rsi_nonexistent_id", agent_name="aris_test",
        )
        assert result["error"] == "not found"
        assert result["candidate_id"] == "rsi_nonexistent_id"
    finally:
        vm_mod.vault_dir = original
        with vm_mod._cache_lock:
            vm_mod._vault_cache.clear()
        rsi_mcp_tools._reset_sandboxes_for_test()
        truth_grounding_mcp_tools._reset_singletons_for_test()


# ─── 10. register_rsi_tools MCP 工具注册 ─────────────────────

class FakeMCPServer:
    """Fake FastMCP server：仅记录注册的工具，便于测试调用。"""

    def __init__(self):
        self.tools: Dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            name = fn.__name__
            self.tools[name] = fn
            return fn
        return decorator


def test_register_rsi_tools_registers_three_tools():
    """register_rsi_tools 注册 rsi_propose / rsi_status / rsi_decide 三工具。"""
    from laap.evolution.rsi_mcp_tools import register_rsi_tools
    fake = FakeMCPServer()
    register_rsi_tools(fake)
    assert "rsi_propose" in fake.tools
    assert "rsi_status" in fake.tools
    assert "rsi_decide" in fake.tools


def test_register_rsi_tools_handles_none_server():
    """register_rsi_tools(None) 不抛错。"""
    from laap.evolution.rsi_mcp_tools import register_rsi_tools
    # 应该不抛错
    register_rsi_tools(None)


def test_rsi_propose_mcp_tool_returns_json(tmp_vault_dir, tmp_repo_root):
    """rsi_propose MCP 工具返回 JSON 字符串，包含 candidate_id。"""
    import asyncio
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    # 让 _detect_repo_root 返回 tmp_repo_root
    with patch(
        "laap.evolution.rsi_mcp_tools._detect_repo_root",
        return_value=tmp_repo_root,
    ), patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        try:
            fake = FakeMCPServer()
            rsi_mcp_tools.register_rsi_tools(fake)
            r = asyncio.run(
                fake.tools["rsi_propose"](
                    target_module="laap/tools/example.py",
                    fitness_signal=0.4,
                    agent_name="aris_test",
                )
            )
            data = json.loads(r)
            assert data["candidate_id"].startswith("rsi_")
            assert data["decision"] == "suggest_adopt"
        finally:
            vm_mod.vault_dir = original
            with vm_mod._cache_lock:
                vm_mod._vault_cache.clear()
            rsi_mcp_tools._reset_sandboxes_for_test()
            truth_grounding_mcp_tools._reset_singletons_for_test()


def test_rsi_decide_mcp_tool_returns_json(tmp_vault_dir, tmp_repo_root):
    """rsi_decide MCP 工具返回 JSON 字符串，包含 decided 字段。"""
    import asyncio
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    with patch(
        "laap.evolution.rsi_mcp_tools._detect_repo_root",
        return_value=tmp_repo_root,
    ), patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        try:
            fake = FakeMCPServer()
            rsi_mcp_tools.register_rsi_tools(fake)
            r = asyncio.run(
                fake.tools["rsi_propose"](
                    target_module="laap/tools/example.py",
                    fitness_signal=0.4,
                    agent_name="aris_test",
                )
            )
            cid = json.loads(r)["candidate_id"]

            r2 = asyncio.run(
                fake.tools["rsi_decide"](
                    candidate_id=cid,
                    action="reject",
                    decided_by="test_user",
                    agent_name="aris_test",
                )
            )
            data = json.loads(r2)
            assert data["decided"] is True
            assert data["action"] == "reject"
            assert data["status"] == "rejected"
        finally:
            vm_mod.vault_dir = original
            with vm_mod._cache_lock:
                vm_mod._vault_cache.clear()
            rsi_mcp_tools._reset_sandboxes_for_test()
            truth_grounding_mcp_tools._reset_singletons_for_test()


def test_rsi_status_mcp_tool_returns_not_found(tmp_vault_dir, tmp_repo_root):
    """rsi_status MCP 工具对不存在的候选返回 {error: not found}。"""
    import asyncio
    from laap.evolution import rsi_mcp_tools
    rsi_mcp_tools._reset_sandboxes_for_test()

    from laap.cognition import truth_grounding_mcp_tools
    truth_grounding_mcp_tools._reset_singletons_for_test()

    from laap.memory_vault.vault_manager import vault_manager as vm_mod
    original = vm_mod.vault_dir
    vm_mod.vault_dir = tmp_vault_dir
    with vm_mod._cache_lock:
        vm_mod._vault_cache.clear()

    with patch(
        "laap.evolution.rsi_mcp_tools._detect_repo_root",
        return_value=tmp_repo_root,
    ):
        try:
            fake = FakeMCPServer()
            rsi_mcp_tools.register_rsi_tools(fake)
            r = asyncio.run(
                fake.tools["rsi_status"](
                    candidate_id="rsi_nonexistent",
                    agent_name="aris_test",
                )
            )
            data = json.loads(r)
            assert data["error"] == "not found"
        finally:
            vm_mod.vault_dir = original
            with vm_mod._cache_lock:
                vm_mod._vault_cache.clear()
            rsi_mcp_tools._reset_sandboxes_for_test()
            truth_grounding_mcp_tools._reset_singletons_for_test()


# ─── 11. 候选写入 vault ──────────────────────────────────────

def test_propose_writes_candidate_to_vault(sandbox_instance, tmp_vault_dir):
    """propose 后候选元数据应写入 vault 的 rsi_candidates 表。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    # 直接读 vault 检查 rsi_candidates 表
    from laap.memory_vault.vault_manager import vault_manager, _open_vault_connection
    db_path, key_hex = vault_manager._get_vault("aris_test")
    conn = _open_vault_connection(db_path, key_hex)
    try:
        row = conn.execute(
            "SELECT candidate_id, target_module, status, decision "
            "FROM rsi_candidates WHERE candidate_id = ?",
            (cid,),
        ).fetchone()
        assert row is not None
        assert row["candidate_id"] == cid
        assert row["target_module"] == "laap/tools/example.py"
        assert row["status"] == "suggest_adopt"
        assert row["decision"] == "suggest_adopt"
    finally:
        conn.close()


def test_adopt_writes_witness_trail_to_vault(
    sandbox_instance, tmp_vault_dir, tmp_repo_root,
):
    """adopt 后见证迹应写入 vault 的 witness_trail_local 表。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        cid = sb.propose("laap/tools/example.py", 0.4)

    result = sb.decide(cid, "adopt", decided_by="test_user")
    assert result["decided"] is True
    witness_id = result["witness_trail_id"]

    # 读 vault 检查 witness_trail_local 表
    from laap.memory_vault.vault_manager import vault_manager, _open_vault_connection
    db_path, key_hex = vault_manager._get_vault("aris_test")
    conn = _open_vault_connection(db_path, key_hex)
    try:
        row = conn.execute(
            "SELECT witness_id, candidate_id, action, event_type "
            "FROM witness_trail_local WHERE witness_id = ?",
            (witness_id,),
        ).fetchone()
        assert row is not None
        assert row["witness_id"] == witness_id
        assert row["candidate_id"] == cid
        assert row["action"] == "adopt"
        assert row["event_type"] == "rsi_decision"
    finally:
        conn.close()


# ─── 12. stats 接口 ──────────────────────────────────────────

def test_stats_returns_summary(sandbox_instance):
    """stats 返回 RSI 沙箱统计快照。"""
    sb = sandbox_instance
    with patch(
        "laap.cognition.truth_grounding_mcp_tools.ground_candidate_description",
        side_effect=_make_grounding_pass,
    ):
        sb.propose("laap/tools/example.py", 0.4)
        sb.propose("laap/tools/example.py", 0.5)

    stats = sb.stats()
    assert stats["agent_name"] == "aris_test"
    assert stats["total_candidates"] >= 2
    assert "by_status" in stats
    assert "decisions_cached" in stats
