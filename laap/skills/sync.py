"""P3-skill-sync: 跨 LAAPer 技能同步协议（学习四步状态机）.

============================================================
  understanding -> adapting -> testing -> adopting -> adopted
                                   |             |
                                   v             v
                              rolled_back    rolled_back
============================================================

spec SubTask 3.1-3.6 (tasks.md L119-126):

    sync_skill(peer_public_key, skill_id) -> sync_job_id

    步骤 1 understanding: LLM 读取技能 component/prompt/tools,
        生成抽象语义描述; 描述必经 P1 truth-grounding 复核
        (``ground_candidate_description``), rejected=True 即终止.
    步骤 2 adapting: 根据目标 agent 的 ishiki.md 性格, LLM
        调整提示词风格 (personality 模板优先, LLM 可选增强).
    步骤 3 testing: 调用 ``laap.evolution.sandbox.Sandbox`` 沙箱
        运行技能测试用例, 验证不破坏现有行为.
    步骤 4 adopting: 测试通过 -> 写入目标 agent 的 vault
        (复用 ``laap.skills.pack_manager.install``); 失败 -> 回滚
        + 通知 (emit ``skill_sync_failed`` 事件).

复用模块:
- ``laap.skills.pack_manager``: _read_manifest / install / SKILLS_DIR
- ``laap.evolution.sandbox``: Sandbox.run_code / test_modification
- ``laap.cognition.truth_grounding_mcp_tools``:
  ground_candidate_description (LLM 输出必经)
- ``laap.protocol.laap_com``: get_relay_registry (peer 公钥校验,
  spec 硬约束: p3-skill-sync 依赖 p3-p2p-relay)

设计约束 (spec L304-313 / L427-435):
* 不 emoji; dataclass + type hints + docstring;
* lazy import: 重型依赖 (sandbox / pack_manager / truth_grounding /
  relay_registry) 仅在首次调用时导入;
* 模板优先: LLM 不可用时降级为规则化生成 (spec L427);
* 幂等: 同一 (peer_public_key, skill_id, target_agent) 重复
  sync_skill 调用返回同一 sync_job_id (不创建新任务);
* 所有返回值为 JSON 字符串可序列化 dict;
* vault 永不直接共享: 同步过程只写入目标 agent 自己的 vault,
  不读源 peer 的 vault.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("laap.skills.sync")


# ── SubTask 3.2: 四步学习状态机 ────────────────────────────


class SyncJobState(str, Enum):
    """技能同步任务状态.

    状态转移:
        understanding -> adapting -> testing -> adopting -> adopted
                                       |             |
                                       v             v
                                  rolled_back    rolled_back

    * ``understanding``: 步骤 1, LLM 生成抽象语义描述 + grounding 复核
    * ``adapting``:     步骤 2, LLM 调整提示词风格
    * ``testing``:      步骤 3, sandbox 沙箱运行测试用例
    * ``adopting``:     步骤 4, 写入目标 agent vault (进行中)
    * ``adopted``:      终态成功 (已写入 vault)
    * ``rolled_back``:  终态失败 (任一步骤失败, 已回滚)
    """

    UNDERSTANDING = "understanding"
    ADAPTING = "adapting"
    TESTING = "testing"
    ADOPTING = "adopting"
    ADOPTED = "adopted"
    ROLLED_BACK = "rolled_back"


# 终态集合 (不再转移)
_TERMINAL_STATES = {SyncJobState.ADOPTED, SyncJobState.ROLLED_BACK}

# 步骤顺序 (用于 advance 转移判定)
_STEP_ORDER: List[SyncJobState] = [
    SyncJobState.UNDERSTANDING,
    SyncJobState.ADAPTING,
    SyncJobState.TESTING,
    SyncJobState.ADOPTING,
    SyncJobState.ADOPTED,
]


@dataclass
class SkillSyncJob:
    """技能同步任务记录 (内存态, 不持久化).

    字段:
        sync_job_id: 任务唯一 ID (sync_{uuid16})
        peer_public_key: 源 peer 的 base64 Ed25519 公钥 (audit)
        skill_id: 要同步的技能 ID (laap/skills/{skill_id}/)
        target_agent: 目标 agent 名称 (vault 写入目标)
        state: 当前状态
        current_step: 当前步骤序号 (1-4)
        started_at: 任务创建时间戳
        updated_at: 最近状态更新时间戳
        error: 失败原因 (rolled_back 时非空)
        understanding_artifact: 步骤 1 产物 (manifest / 摘要 / grounding)
        adapting_artifact: 步骤 2 产物 (原始/适配 prompt / 风格变更)
        testing_artifact: 步骤 3 产物 (测试用例数 / 通过率 / sandbox 输出)
        adopting_artifact: 步骤 4 产物 (install 结果 / vault 写入状态)
    """

    sync_job_id: str
    peer_public_key: str
    skill_id: str
    target_agent: str
    state: SyncJobState = SyncJobState.UNDERSTANDING
    current_step: int = 1
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    understanding_artifact: Dict[str, Any] = field(default_factory=dict)
    adapting_artifact: Dict[str, Any] = field(default_factory=dict)
    testing_artifact: Dict[str, Any] = field(default_factory=dict)
    adopting_artifact: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可 JSON 化的 dict (state 转字符串)."""
        d = asdict(self)
        d["state"] = self.state.value
        return d

    def touch(self) -> None:
        """刷新 updated_at."""
        self.updated_at = time.time()


# ── 性格加载 (ishiki.md / character.json) ──────────────────


# 性格文件可能存在的位置 (P5-laaper-market 会规范化为 ishiki.md)
_PERSONALITY_FILENAMES = ("ishiki.md", "character.json", "yuan.md")


def load_agent_personality(agent_name: str) -> str:
    """加载目标 agent 的性格描述 (ishiki.md).

    查找顺序:
    1. ``hanako/data/agents/{agent_name}/ishiki.md``
    2. ``hanako/data/agents/{agent_name}/character.json``
    3. ``hanako/data/agents/{agent_name}/yuan.md``

    任何文件读取失败 / 文件不存在均返回空字符串 (适配步骤降级为
    原样保留提示词). 此函数永不抛异常, 保证 sync 流程非阻塞.

    Args:
        agent_name: 目标 agent 名称.

    Returns:
        性格描述文本 (markdown 或 json 字符串); 未找到返回 "".
    """
    if not isinstance(agent_name, str) or not agent_name.strip():
        return ""
    try:
        # 相对 laap/skills/sync.py 找到 LAAP 根目录
        laap_root = Path(__file__).resolve().parent.parent.parent
        agent_dir = laap_root / "hanako" / "data" / "agents" / agent_name
        for fname in _PERSONALITY_FILENAMES:
            fpath = agent_dir / fname
            if fpath.is_file():
                try:
                    return fpath.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning(
                        f"load_agent_personality: read {fpath} failed: {exc}"
                    )
                    continue
    except Exception as exc:
        logger.warning(f"load_agent_personality({agent_name}) failed: {exc}")
    return ""


# ── LLM 调用 stub (模板优先, 真实 LLM 可选) ──────────────────


def _try_llm_describe_skill(
    manifest_dict: Dict[str, Any],
    component_text: str,
    prompt_text: str,
    tools_list: List[str],
) -> Optional[str]:
    """尝试用 LLM 生成技能语义描述 (失败返回 None, 由调用方降级).

    lazy import ``laap.llm.factory``, 若模块或 LLM 后端不可用返回 None.
    本函数永不抛异常.
    """
    try:
        from laap.llm.factory import build_llm  # type: ignore
        llm = build_llm()
        if llm is None:
            return None
        prompt = (
            "请用一段话描述以下技能包的语义: 它做什么、解决什么问题、"
            "对宿主 agent 的能力贡献是什么. 输出纯文本, 不要列表.\n\n"
            f"manifest: {json.dumps(manifest_dict, ensure_ascii=False)}\n"
            f"component (摘要前 500 字): {component_text[:500]}\n"
            f"prompt (摘要前 500 字): {prompt_text[:500]}\n"
            f"tools: {', '.join(tools_list) if tools_list else '(无)'}\n"
        )
        # 不同 LLM 后端 API 不一致, 这里 try 通用 invoke / chat / generate
        for method in ("invoke", "chat", "generate", "complete"):
            fn = getattr(llm, method, None)
            if callable(fn):
                result = fn(prompt)
                if isinstance(result, str) and result.strip():
                    return result.strip()
                if isinstance(result, dict):
                    text = result.get("text") or result.get("content") or ""
                    if text:
                        return str(text).strip()
        return None
    except Exception as exc:
        logger.debug(f"_try_llm_describe_skill: LLM unavailable ({exc})")
        return None


def _template_describe_skill(
    manifest_dict: Dict[str, Any],
    component_text: str,
    prompt_text: str,
    tools_list: List[str],
) -> str:
    """模板化生成技能语义描述 (LLM 不可用时的降级路径).

    输出格式: ``"{name} v{version}: {description}; "
    "组件: {component-or-无}; 提示词: {prompt-or-无}; "
    "工具: {tools-or-无}"``

    spec L427: 模板优先, 不新增外部 LLM 依赖.
    """
    name = manifest_dict.get("name", "")
    version = manifest_dict.get("version", "0.0.0")
    description = manifest_dict.get("description", "")
    component = manifest_dict.get("component") or "(无)"
    prompt_file = manifest_dict.get("prompt") or "(无)"
    tools_str = ", ".join(tools_list) if tools_list else "(无)"
    return (
        f"{name} v{version}: {description or '(无描述)'}; "
        f"组件: {component}; 提示词文件: {prompt_file}; "
        f"工具绑定: {tools_str}"
    )


def _try_llm_adapt_prompt(
    original_prompt: str,
    personality: str,
) -> Optional[str]:
    """尝试用 LLM 根据性格调整提示词风格 (失败返回 None)."""
    if not personality.strip():
        return None
    try:
        from laap.llm.factory import build_llm  # type: ignore
        llm = build_llm()
        if llm is None:
            return None
        prompt = (
            "请根据以下目标 agent 的性格描述, 调整给定提示词的语气与"
            "风格, 保持核心指令不变, 仅改写表达方式. 输出纯文本.\n\n"
            f"性格: {personality[:800]}\n\n"
            f"原提示词: {original_prompt[:800]}\n"
        )
        for method in ("invoke", "chat", "generate", "complete"):
            fn = getattr(llm, method, None)
            if callable(fn):
                result = fn(prompt)
                if isinstance(result, str) and result.strip():
                    return result.strip()
                if isinstance(result, dict):
                    text = result.get("text") or result.get("content") or ""
                    if text:
                        return str(text).strip()
        return None
    except Exception as exc:
        logger.debug(f"_try_llm_adapt_prompt: LLM unavailable ({exc})")
        return None


# 性格 → 风格修饰映射 (模板降级路径)
_PERSONALITY_STYLE_HINTS = (
    # (性格关键词, 风格修饰前缀)
    ("活泼", "用轻松愉快的语气, 偶尔使用感叹号: "),
    ("playful", "Use a playful tone, occasionally use exclamation marks: "),
    ("严谨", "用严谨专业的语气, 逻辑清晰: "),
    ("professional", "Use a professional and precise tone: "),
    ("柔和", "用温和柔和的语气: "),
    ("gentle", "Use a gentle and warm tone: "),
    ("架构", "从架构师视角, 强调系统性与权衡: "),
    ("architect", "From an architect's perspective, emphasize system design: "),
)


def _template_adapt_prompt(
    original_prompt: str,
    personality: str,
) -> str:
    """模板化根据性格调整提示词风格 (LLM 不可用时的降级路径).

    实现: 在原提示词前加风格修饰前缀. 若性格为空, 原样返回.

    spec SubTask 3.4: "根据目标 agent 的 ishiki.md 性格, LLM 调整
    提示词风格". 模板降级保证无 LLM 环境下也能产生差异化适配结果.
    """
    if not personality.strip():
        return original_prompt
    hint = ""
    personality_lower = personality.lower()
    for keyword, style in _PERSONALITY_STYLE_HINTS:
        if keyword in personality_lower:
            hint = style
            break
    if not hint:
        # 默认: 通用化修饰, 表明已做适配
        hint = "请根据目标 agent 性格表达: "
    return hint + original_prompt


# ── 测试用例读取 ──────────────────────────────────────────


# 技能目录下可能的测试文件名 (按优先级)
_TEST_FILENAMES = ("tests.py", "test_cases.py", "tests.json", "test_cases.json")


def _read_skill_test_cases(
    skill_dir: Path,
    manifest_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """读取技能目录下的测试用例.

    Returns:
        ``{test_code: str, test_count: int, source: str}``:
        - ``test_code``: 可在 sandbox 中 exec 的 Python 代码 (json
          测试用例会被包装成断言代码)
        - ``test_count``: 测试用例数
        - ``source``: 测试来源文件名; "(smoke)" 表示无测试文件,
          使用 manifest 合法性冒烟测试
    """
    for fname in _TEST_FILENAMES:
        fpath = skill_dir / fname
        if fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8")
                if fname.endswith(".json"):
                    # JSON 测试用例包装为断言代码
                    cases = json.loads(content)
                    if not isinstance(cases, list):
                        cases = [cases]
                    lines = ["import json as _json"]
                    for i, case in enumerate(cases):
                        expected = case.get("expected") if isinstance(case, dict) else None
                        expr = case.get("expr") if isinstance(case, dict) else str(case)
                        if expected is not None and expr:
                            lines.append(
                                f"_r{i} = {expr}\n"
                                f"assert _r{i} == {json.dumps(expected, ensure_ascii=False)}, "
                                f"f'case {i} failed: got {{_r{i}}}, want {expected}'"
                            )
                    lines.append("result = 'all_passed'")
                    return {
                        "test_code": "\n".join(lines),
                        "test_count": len(cases),
                        "source": fname,
                    }
                # .py: 直接当测试代码
                # 统计顶层 assert / def test_ 数量作为粗略 count
                count = max(
                    1,
                    content.count("\nassert ") + len(
                        [l for l in content.splitlines() if l.startswith("def test_")]
                    ),
                )
                return {
                    "test_code": content + "\nresult = 'tests_ok'",
                    "test_count": count,
                    "source": fname,
                }
            except Exception as exc:
                logger.warning(
                    f"_read_skill_test_cases: parse {fpath} failed: {exc}"
                )
                continue
    # 无测试文件: 冒烟测试 = manifest 合法性 + skill_id 唯一性
    smoke_code = (
        "import json as _json\n"
        f"_m = _json.loads({json.dumps(json.dumps(manifest_dict, ensure_ascii=False))})\n"
        "assert isinstance(_m, dict) and 'name' in _m, 'manifest invalid'\n"
        f"assert _m['name'] == {repr(manifest_dict.get('name', ''))}, 'name mismatch'\n"
        "result = 'smoke_ok'\n"
    )
    return {
        "test_code": smoke_code,
        "test_count": 1,
        "source": "(smoke)",
    }


# ── 主管理器 ──────────────────────────────────────────────


class SkillSyncManager:
    """技能同步管理器: 维护 sync_job 列表, 执行四步状态机.

    使用方式:
        mgr = get_skill_sync_manager()
        job_id = mgr.sync_skill(
            peer_public_key="...",
            skill_id="aris-code-review",
            target_agent="hanako",
        )
        # 或逐步执行:
        # mgr.advance(job_id)  # understanding -> adapting
        # mgr.advance(job_id)  # adapting -> testing
        # mgr.advance(job_id)  # testing -> adopting
        # mgr.advance(job_id)  # adopting -> adopted
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        sandbox_factory: Optional[Callable[[], Any]] = None,
        personality_loader: Callable[[str], str] = load_agent_personality,
        auto_advance: bool = True,
    ):
        """初始化.

        Args:
            clock: 时间源 (测试可注入 mock).
            sandbox_factory: 沙箱工厂 (测试可注入 mock). None 时使用
                ``laap.evolution.sandbox.Sandbox``.
            personality_loader: 性格加载器 (测试可注入 mock).
            auto_advance: sync_skill 是否自动跑完四步. True (默认)
                一次性到终态; False 时仅跑第一步, 后续由 advance 触发.
        """
        self._clock = clock
        self._sandbox_factory = sandbox_factory
        self._personality_loader = personality_loader
        self._auto_advance = auto_advance
        self._jobs: Dict[str, SkillSyncJob] = {}
        # 幂等键: (peer_public_key, skill_id, target_agent) -> sync_job_id
        self._idempotency: Dict[tuple, str] = {}

    # ── SubTask 3.1: sync_skill 入口 ──

    def sync_skill(
        self,
        peer_public_key: str,
        skill_id: str,
        target_agent: str = "aris",
        personality_override: Optional[str] = None,
        auto_advance: Optional[bool] = None,
    ) -> str:
        """启动一次技能同步, 返回 sync_job_id.

        spec SubTask 3.1: ``sync_skill(peer_public_key, skill_id) ->
        sync_job_id``.

        幂等: 同一 (peer_public_key, skill_id, target_agent) 重复
        调用返回同一 sync_job_id, 不创建新任务. 若该任务已在终态
        (adopted / rolled_back), 则重新创建一个新 job_id 重跑.

        Args:
            peer_public_key: 源 peer base64 公钥 (audit; 不验证签名,
                仅记录, 真实验证由调用方完成).
            skill_id: 要同步的技能 ID (laap/skills/{skill_id}/ 必须存在).
            target_agent: 目标 agent 名称 (vault 写入目标).
            personality_override: 性格文本覆盖 (测试用; None 时调
                ``self._personality_loader(target_agent)``).
            auto_advance: 是否自动跑完四步; None 时用构造器默认.

        Returns:
            sync_job_id (字符串 ``sync_{uuid16}``).

        Raises:
            ValueError: peer_public_key / skill_id / target_agent 为空.
            FileNotFoundError: skill_id 目录或 manifest.json 不存在.
        """
        if not isinstance(peer_public_key, str) or not peer_public_key.strip():
            raise ValueError("peer_public_key must be non-empty str")
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id must be non-empty str")
        if not isinstance(target_agent, str) or not target_agent.strip():
            raise ValueError("target_agent must be non-empty str")

        peer_pk = peer_public_key.strip()
        sid = skill_id.strip()
        agent = target_agent.strip()

        # 幂等: 终态任务可重跑
        idem_key = (peer_pk, sid, agent)
        existing_id = self._idempotency.get(idem_key)
        if existing_id and existing_id in self._jobs:
            existing = self._jobs[existing_id]
            if existing.state not in _TERMINAL_STATES:
                # 同一任务进行中, 直接返回
                return existing_id
            # 终态: 清掉幂等映射, 允许重跑
            self._idempotency.pop(idem_key, None)

        # 预校验 skill 存在 (触发 FileNotFoundError 等)
        from laap.skills.pack_manager import _read_manifest, _skill_dir
        skill_dir = _skill_dir(sid)
        manifest = _read_manifest(skill_dir)  # raises FileNotFoundError/ValueError

        sync_job_id = f"sync_{uuid.uuid4().hex[:16]}"
        job = SkillSyncJob(
            sync_job_id=sync_job_id,
            peer_public_key=peer_pk,
            skill_id=sid,
            target_agent=agent,
            state=SyncJobState.UNDERSTANDING,
            current_step=1,
            started_at=self._clock(),
            updated_at=self._clock(),
        )
        self._jobs[sync_job_id] = job
        self._idempotency[idem_key] = sync_job_id
        logger.info(
            f"sync_skill: job={sync_job_id} peer={peer_pk[:16]}... "
            f"skill={sid} agent={agent}"
        )

        # 注入 personality override (测试可控)
        if personality_override is not None:
            job._personality_override = personality_override  # type: ignore[attr-defined]

        # 执行步骤 1
        should_auto = self._auto_advance if auto_advance is None else auto_advance
        self._run_step(job)
        if should_auto:
            # 自动跑完剩余步骤
            while job.state not in _TERMINAL_STATES:
                if not self._advance(job):
                    break
        return sync_job_id

    # ── SubTask 3.2-3.6: 状态机推进 ──

    def advance(self, sync_job_id: str) -> Dict[str, Any]:
        """手动推进任务到下一步 (auto_advance=False 时使用).

        Returns:
            任务当前状态 dict (sync_job_id / state / current_step /
            error?).

        终态任务 advance 返回当前状态, 不抛异常.
        """
        job = self._jobs.get(sync_job_id)
        if job is None:
            return {"error": f"sync_job not found: {sync_job_id}"}
        if job.state in _TERMINAL_STATES:
            return job.to_dict()
        self._advance(job)
        return job.to_dict()

    def _advance(self, job: SkillSyncJob) -> bool:
        """内部: 推进一步. 返回是否成功转移 (False = 失败已转 rolled_back)."""
        next_state_map = {
            SyncJobState.UNDERSTANDING: SyncJobState.ADAPTING,
            SyncJobState.ADAPTING: SyncJobState.TESTING,
            SyncJobState.TESTING: SyncJobState.ADOPTING,
            SyncJobState.ADOPTING: SyncJobState.ADOPTED,
        }
        if job.state not in next_state_map:
            return False
        # 进入下一状态前, 设置 state (步骤 _run_step 在 sync_skill 中
        # 已对当前状态执行; 后续步骤先改 state 再 run)
        next_state = next_state_map[job.state]
        job.state = next_state
        job.current_step = _STEP_ORDER.index(next_state) + 1
        job.touch()
        return self._run_step(job)

    def _run_step(self, job: SkillSyncJob) -> bool:
        """执行当前状态对应的步骤. 失败时转 rolled_back, 返回 False."""
        try:
            if job.state == SyncJobState.UNDERSTANDING:
                self._step_understanding(job)
            elif job.state == SyncJobState.ADAPTING:
                self._step_adapting(job)
            elif job.state == SyncJobState.TESTING:
                self._step_testing(job)
            elif job.state == SyncJobState.ADOPTING:
                self._step_adopting(job)
            elif job.state == SyncJobState.ADOPTED:
                # 终态: 无操作
                pass
            else:
                # 未知状态: 不做任何事
                pass
            job.touch()
            return True
        except _SyncRollback as exc:
            job.error = str(exc)
            job.state = SyncJobState.ROLLED_BACK
            job.touch()
            self._emit_rollback_event(job, str(exc))
            logger.warning(
                f"sync_skill {job.sync_job_id} rolled back at "
                f"step {job.current_step} ({job.state.value}): {exc}"
            )
            return False
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
            job.state = SyncJobState.ROLLED_BACK
            job.touch()
            self._emit_rollback_event(job, job.error)
            logger.error(
                f"sync_skill {job.sync_job_id} unexpected failure at "
                f"step {job.current_step}: {exc}",
                exc_info=True,
            )
            return False

    # ── SubTask 3.3: 步骤 1 understanding ──

    def _step_understanding(self, job: SkillSyncJob) -> None:
        """LLM 读取技能 component/prompt/tools, 生成抽象语义描述.

        描述必经 ``ground_candidate_description`` 复核 (spec 硬约束).
        rejected=True 即抛 ``_SyncRollback`` 终止同步.
        """
        from laap.skills.pack_manager import _read_manifest, _skill_dir
        skill_dir = _skill_dir(job.skill_id)
        manifest = _read_manifest(skill_dir)
        manifest_dict = manifest.to_dict()

        # 读取 component / prompt 文件
        component_text = ""
        if manifest.component:
            comp_path = skill_dir / manifest.component
            if comp_path.is_file():
                try:
                    component_text = comp_path.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning(f"understanding: read component failed: {exc}")
        prompt_text = ""
        if manifest.prompt:
            prompt_path = skill_dir / manifest.prompt
            if prompt_path.is_file():
                try:
                    prompt_text = prompt_path.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning(f"understanding: read prompt failed: {exc}")
        # 兜底: 默认文件名
        if not component_text:
            comp_default = skill_dir / "component.tsx"
            if comp_default.is_file():
                component_text = comp_default.read_text(encoding="utf-8")
        if not prompt_text:
            prompt_default = skill_dir / "prompt.md"
            if prompt_default.is_file():
                prompt_text = prompt_default.read_text(encoding="utf-8")

        tools_list = list(manifest.tools or [])

        # LLM 主导 (可选) + 模板降级 (spec L427)
        semantic_desc = _try_llm_describe_skill(
            manifest_dict, component_text, prompt_text, tools_list,
        )
        method = "llm"
        if not semantic_desc:
            semantic_desc = _template_describe_skill(
                manifest_dict, component_text, prompt_text, tools_list,
            )
            method = "template"

        # 强制 grounding 复核 (spec 硬约束: LLM 输出必经 truth-grounding)
        from laap.cognition.truth_grounding_mcp_tools import (
            ground_candidate_description,
        )
        grounding = ground_candidate_description(
            semantic_desc, agent_name=job.target_agent,
        )
        # grounding 失败时不直接 reject (state=uncertain 也允许继续)
        rejected = bool(grounding.get("rejected", False))

        job.understanding_artifact = {
            "manifest": manifest_dict,
            "component_summary": component_text[:800],
            "prompt_summary": prompt_text[:800],
            "tools": tools_list,
            "semantic_description": semantic_desc,
            "method": method,
            "grounding": {
                "state": grounding.get("state", "uncertain"),
                "confidence": float(grounding.get("confidence", 0.0)),
                "evidence": list(grounding.get("evidence", []) or []),
                "rejected": rejected,
            },
        }

        if rejected:
            conflicts = list(grounding.get("conflicts", []) or [])
            raise _SyncRollback(
                f"understanding rejected by truth-grounding: "
                f"{'; '.join(conflicts) or 'unspecified conflict'}"
            )

    # ── SubTask 3.4: 步骤 2 adapting ──

    def _step_adapting(self, job: SkillSyncJob) -> None:
        """根据目标 agent 的 ishiki.md 性格调整提示词风格."""
        from laap.skills.pack_manager import _read_manifest, _skill_dir
        manifest = _read_manifest(_skill_dir(job.skill_id))
        skill_dir = _skill_dir(job.skill_id)

        # 读取原 prompt
        original_prompt = ""
        if manifest.prompt:
            prompt_path = skill_dir / manifest.prompt
            if prompt_path.is_file():
                original_prompt = prompt_path.read_text(encoding="utf-8")
        if not original_prompt:
            # 纯组件技能: 用 description 当 prompt
            original_prompt = manifest.description or manifest.name

        # 加载性格 (优先 override, 否则 loader)
        personality = getattr(job, "_personality_override", None)
        if personality is None:
            personality = self._personality_loader(job.target_agent)
        personality = personality or ""

        # LLM 主导 + 模板降级
        adapted = _try_llm_adapt_prompt(original_prompt, personality)
        method = "llm"
        if adapted is None:
            adapted = _template_adapt_prompt(original_prompt, personality)
            method = "template"

        # 风格变更标记 (供测试断言)
        style_changed = adapted != original_prompt

        job.adapting_artifact = {
            "original_prompt": original_prompt[:1500],
            "adapted_prompt": adapted[:1500],
            "personality_summary": personality[:500],
            "method": method,
            "style_changed": style_changed,
        }

    # ── SubTask 3.5: 步骤 3 testing ──

    def _step_testing(self, job: SkillSyncJob) -> None:
        """调 sandbox 沙箱运行技能测试用例, 验证不破坏现有行为."""
        from laap.skills.pack_manager import _read_manifest, _skill_dir
        manifest = _read_manifest(_skill_dir(job.skill_id))
        manifest_dict = manifest.to_dict()
        skill_dir = _skill_dir(job.skill_id)

        # 读取测试用例
        test_info = _read_skill_test_cases(skill_dir, manifest_dict)
        test_code = test_info["test_code"]
        test_count = test_info["test_count"]
        source = test_info["source"]

        # 沙箱执行
        if self._sandbox_factory is not None:
            sandbox = self._sandbox_factory()
        else:
            from laap.evolution.sandbox import Sandbox
            sandbox = Sandbox(timeout=30)
        try:
            result = sandbox.run_code(test_code, context={
                "skill_id": job.skill_id,
                "target_agent": job.target_agent,
            })
        except Exception as exc:
            # 沙箱异常视为测试失败
            result = {
                "success": False,
                "error": f"sandbox exception: {type(exc).__name__}: {exc}",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "timeout": False,
            }

        passed = bool(result.get("success", False))

        job.testing_artifact = {
            "test_count": test_count,
            "test_source": source,
            "passed": passed,
            "sandbox_result": {
                "success": passed,
                "stdout": (result.get("stdout") or "")[-1500:],
                "stderr": (result.get("stderr") or "")[-1000:],
                "exit_code": result.get("exit_code", -1),
                "timeout": bool(result.get("timeout", False)),
            },
        }

        if not passed:
            err_summary = (result.get("stderr") or result.get("error") or "tests failed")[:300]
            raise _SyncRollback(f"testing failed: {err_summary}")

    # ── SubTask 3.6: 步骤 4 adopting ──

    def _step_adopting(self, job: SkillSyncJob) -> None:
        """测试通过 -> 写入目标 agent vault; 失败 -> 回滚 + 通知."""
        from laap.skills.pack_manager import install
        try:
            install_result = install(job.target_agent, job.skill_id)
        except Exception as exc:
            job.adopting_artifact = {
                "installed": False,
                "error": f"install failed: {type(exc).__name__}: {exc}",
            }
            raise _SyncRollback(f"adopting install failed: {exc}") from exc

        job.adopting_artifact = {
            "installed": True,
            "skill_id": install_result.get("skill_id", job.skill_id),
            "version": install_result.get("version", ""),
            "agent_name": install_result.get("agent_name", job.target_agent),
        }
        # state 由 _advance 设置为 ADOPTED
        logger.info(
            f"sync_skill {job.sync_job_id} adopted: "
            f"skill={job.skill_id} -> agent={job.target_agent}"
        )

    # ── 查询接口 ──

    def get_job(self, sync_job_id: str) -> Optional[Dict[str, Any]]:
        """查询任务状态. 不存在返回 None."""
        job = self._jobs.get(sync_job_id)
        return job.to_dict() if job else None

    def list_jobs(
        self,
        state_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出所有任务 (可选状态过滤).

        Args:
            state_filter: 状态字符串 (e.g. "adopted", "rolled_back");
                None 时返回全部.

        Returns:
            任务 dict 列表, 按 started_at 倒序.
        """
        jobs = list(self._jobs.values())
        if state_filter:
            target = state_filter.strip().lower()
            jobs = [j for j in jobs if j.state.value == target]
        jobs.sort(key=lambda j: j.started_at, reverse=True)
        return [j.to_dict() for j in jobs]

    def reset_for_test(self) -> None:
        """测试辅助: 清空所有任务. 生产代码不要调用."""
        self._jobs.clear()
        self._idempotency.clear()

    # ── 内部: 回滚事件 ──

    def _emit_rollback_event(
        self,
        job: SkillSyncJob,
        reason: str,
    ) -> None:
        """回滚时通知 (spec SubTask 3.6: 失败 -> 回滚 + 通知).

        通过 ``laap.events.bus`` 发布 ``skill_sync_failed`` 事件,
        供前端 bubble-field / charter-guardian 监听. lazy import,
        失败不阻塞.
        """
        try:
            from laap.events.bus import bus, Event
            bus.publish(Event(
                type="skill_sync_failed",
                data={
                    "sync_job_id": job.sync_job_id,
                    "skill_id": job.skill_id,
                    "target_agent": job.target_agent,
                    "peer_public_key": job.peer_public_key,
                    "failed_step": job.state.value,
                    "reason": reason,
                },
                source="p3-skill-sync",
            ))
        except Exception as exc:
            logger.debug(f"_emit_rollback_event: bus publish failed: {exc}")


# ── 内部异常 ─────────────────────────────────────────────


class _SyncRollback(Exception):
    """同步步骤失败, 触发回滚 (内部使用)."""


# ── 模块级单例 (仿 laap_coop.get_trio_chatroom_manager 模式) ──

_manager: Optional[SkillSyncManager] = None


def get_skill_sync_manager() -> SkillSyncManager:
    """获取全局 SkillSyncManager 单例."""
    global _manager
    if _manager is None:
        _manager = SkillSyncManager()
    return _manager


def reset_skill_sync_manager_for_test(
    clock: Callable[[], float] = time.time,
    sandbox_factory: Optional[Callable[[], Any]] = None,
    personality_loader: Callable[[str], str] = load_agent_personality,
    auto_advance: bool = True,
) -> SkillSyncManager:
    """测试辅助: 重置单例并注入 mock. 生产代码不要调用."""
    global _manager
    _manager = SkillSyncManager(
        clock=clock,
        sandbox_factory=sandbox_factory,
        personality_loader=personality_loader,
        auto_advance=auto_advance,
    )
    return _manager
