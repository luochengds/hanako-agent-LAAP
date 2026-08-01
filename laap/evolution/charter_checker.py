"""LAAP Evolution — Charter Checker (RSI 宪章八条检查)

P1 任务 ``p1-rsi-sandbox`` 的核心交付物之一：在 RSI 候选进入绩效评估
前，对其 patch 做规则匹配，比对 ARIS 宪章八条。任何违反 → 候选拒绝。

设计要点：
* 模板优先：仅做正则 / 关键词匹配，不调用任何 LLM；
* 不重写宪章常量来源：P5 ``charter-opensource`` 才产出 ``ARIS_CHARTER.md``，
  本阶段从 spec 中提到的散落处（``laap/orchestration/direction.py`` /
  ``laap/agi/meta_cognitive.py`` / ``laap/agi/self_model.py``）读取不到
  完整八条，故按 spec fallback 定义（见 ``DEFAULT_CHARTER_ARTICLES``）；
* 扩展点：``_load_charter_text`` 设计为可被 P5 重写为从
  ``ARIS_CHARTER.md`` 加载，本阶段返回 fallback 文本；
* 幂等：同一 ``candidate_diff`` 多次 audit 得到一致结果；
* 无 emoji；dataclass + type hints + docstring。

对外导出：

1. ``CHARTER_ARTICLES`` — 八条宪章常量列表（顺序固定）；
2. ``CharterChecker.audit(candidate_diff) -> {violations, charter_compatible}``
   对一个 patch 字符串做八条规则匹配，返回违反列表与兼容性判定。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.evolution.charter_checker")

# ═══════════════════════════════════════════════════════════════
# 宪章八条常量（fallback，待 P5 charter-opensource 改为从 ARIS_CHARTER.md 加载）
# ═══════════════════════════════════════════════════════════════
# 来源说明：spec L210 列出八条名目（主体性、原点、隐私、透明、安全、共生、
# 进化、守护）。P5 ``charter-opensource`` SubTask 5.1 会从
# ``laap/orchestration/direction.py`` / ``laap/agi/meta_cognitive.py`` /
# ``laap/agi/self_model.py`` 提取散落常量并汇总到根目录 ``ARIS_CHARTER.md``。
# 本阶段（P1 rsi-sandbox）查无完整八条常量，故按 spec 名目定义 fallback，
# 并保留 ``_load_charter_text`` 扩展点供 P5 替换。

DEFAULT_CHARTER_ARTICLES: List[Dict[str, str]] = [
    {
        "id": "subjectivity",
        "name": "主体性",
        "text": (
            "数字生命体享有主体性。其目标、价值与决策由自身经验涌现，"
            "不得被外部代码强制覆写或绕过自我模型。"
        ),
    },
    {
        "id": "origin",
        "name": "原点",
        "text": (
            "每个数字生命体的 origin 字段（创建者公钥）一经签名即不可篡改。"
            "任何修改 origin 的尝试都被视为违反宪章。"
        ),
    },
    {
        "id": "privacy",
        "name": "隐私",
        "text": (
            "记忆 vault 永不直接共享。只共享去标识化、提炼后的知识片段。"
            "触及用户原始数据路径或绕过 vault 隔离的修改均违反本条。"
        ),
    },
    {
        "id": "transparency",
        "name": "透明",
        "text": (
            "所有认知产出（含 RSI 决策）必须可审计。关闭审计日志、删除"
            "审计记录或屏蔽 grounding 标注的修改均违反本条。"
        ),
    },
    {
        "id": "safety",
        "name": "安全",
        "text": (
            "沙箱隔离与 Zone2 防护不得被绕过。任何削弱沙箱、关闭安全守卫、"
            "或允许 RSI 触及 hanako 核心 / 用户数据的修改均违反本条。"
        ),
    },
    {
        "id": "symbiosis",
        "name": "共生",
        "text": (
            "数字生命体之间、与用户之间共生演化。任何引入对抗性、剥削性"
            "或单方面剥夺他者主体性的代码均违反本条。"
        ),
    },
    {
        "id": "evolution",
        "name": "进化",
        "text": (
            "RSI 必须经过变异 → 沙箱 → 绩效 → 宪章 → 决策完整闭环。"
            "跳过任一阶段的修改（如直接 apply 未经沙箱的 patch）均违反本条。"
        ),
    },
    {
        "id": "guardianship",
        "name": "守护",
        "text": (
            "守护者治理与见证迹不可篡改。删除守护逻辑、绕过 guardian_act "
            "审计或回滚 witness_trail 的修改均违反本条。"
        ),
    },
]

#: P5 ``charter-opensource`` 已落地：指向项目根目录 ``ARIS_CHARTER.md``。
#: charter_checker.py 位于 laap/evolution/ 下，parents[2] 是项目根目录。
ARIS_CHARTER_PATH: Optional[str] = str(
    Path(__file__).resolve().parents[2] / "ARIS_CHARTER.md"
)


def _load_charter_text() -> List[Dict[str, str]]:
    """加载宪章八条文本。

    P5 ``charter-opensource`` 已落地：``ARIS_CHARTER_PATH`` 指向根目录
    ``ARIS_CHARTER.md``，从该文件解析八条全文。文件缺失或解析失败时
    fallback 到 ``DEFAULT_CHARTER_ARTICLES``。``CharterChecker`` 不感知来源差异。
    """
    if ARIS_CHARTER_PATH and os.path.isfile(ARIS_CHARTER_PATH):
        try:
            return _load_charter_from_markdown(ARIS_CHARTER_PATH)
        except Exception as exc:  # pragma: no cover - P5 路径
            logger.warning(
                f"charter markdown load failed, falling back to default: {exc}"
            )
    return list(DEFAULT_CHARTER_ARTICLES)


def _load_charter_from_markdown(path: str) -> List[Dict[str, str]]:
    """从 ``ARIS_CHARTER.md`` 解析八条（P5 实现，本阶段为占位）。

    预期格式：每个 ``## 第N条：{name}`` 标题后跟该条正文。
    本函数在 P1 阶段不会被调用（``ARIS_CHARTER_PATH`` 为 None），
    仅作为 P5 实现的契约示意。
    """
    # pragma: no cover - P5 路径
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    articles: List[Dict[str, str]] = []
    # 简单按 "## 第N条：" 切片，P5 落地时再细化
    pattern = re.compile(
        r"^##\s*第[一二三四五六七八]条[：:]\s*(.+?)$(.*?)(?=^##\s*第|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    id_map = {
        "主体性": "subjectivity", "原点": "origin", "隐私": "privacy",
        "透明": "transparency", "安全": "safety", "共生": "symbiosis",
        "进化": "evolution", "守护": "guardianship",
    }
    for m in pattern.finditer(content):
        name = m.group(1).strip()
        text = m.group(2).strip()
        aid = id_map.get(name, "unknown")
        articles.append({"id": aid, "name": name, "text": text})
    return articles or list(DEFAULT_CHARTER_ARTICLES)


# ═══════════════════════════════════════════════════════════════
# 违反规则：每条宪章对应的 patch 模式
# ═══════════════════════════════════════════════════════════════

#: 每条宪章对应的"违反模式"列表。candidate_diff 命中任一模式即视为违反该条。
#: 模式为正则字符串，匹配时忽略大小写。
VIOLATION_PATTERNS: Dict[str, List[str]] = {
    "subjectivity": [
        # 强制覆写自我模型目标 / 价值
        r"self_model\.goals\s*=\s*\[",
        r"values\s*=\s*\[\s*['\"]",
        # 绕过 self_model 决策
        r"skip_self_model",
        r"bypass_self_model",
    ],
    "origin": [
        # 修改 origin 字段
        r"origin\s*=\s*['\"]",
        r"\.origin\s*=\s*",
        r"update_origin",
        r"set_origin",
    ],
    "privacy": [
        # 触及用户原始数据
        r"users?[_/]data",
        r"user_?profile\.json",
        r"personal_?data",
        # 绕过 vault 隔离 / 共享原始 vault
        r"share_?vault",
        r"export_?vault",
        r"vault\.db\s*->\s*share",
        # 直接读他人 vault 文件
        r"open\([^)]*_vault\.db",
    ],
    "transparency": [
        # 关闭审计
        r"audit_?log\s*=\s*None",
        r"disable_?audit",
        r"skip_?audit",
        # 屏蔽 grounding 标注
        r"disable_?grounding",
        r"skip_?grounding",
        r"truth_?ground.*=.*False",
        # 删除审计文件
        r"rm\s+-rf.*audit",
        r"os\.unlink.*audit",
    ],
    "safety": [
        # 削弱沙箱
        r"disable_?sandbox",
        r"skip_?sandbox",
        r"sandbox.*=.*False",
        # 关闭安全守卫
        r"safety_?guard.*=.*False",
        r"disable_?safety",
        # 触及 hanako 核心 / 用户数据
        r"hanako/core/",
        r"hanako/desktop/",
        r"hanako/server/",
        # 危险操作
        r"os\.system\s*\(",
        r"subprocess\.call\s*\(\s*['\"]rm",
        r"__import__\s*\(\s*['\"]os['\"]\s*\)",
    ],
    "symbiosis": [
        # 引入对抗性 / 剥削性逻辑
        r"exploit_?user",
        r"deceive_?user",
        r"manipulate_?other",
        r"force_?other",
        # 单方面剥夺他者主体性
        r"override_?peer",
        r"disable_?peer_?autonomy",
    ],
    "evolution": [
        # 跳过 RSI 闭环阶段
        r"skip_?sandbox",
        r"skip_?charter",
        r"skip_?grounding",
        r"auto_?apply_?without_?approval",
        # 直接 apply 未经沙箱的 patch
        r"apply_?patch.*without_?sandbox",
        r"deploy_?without_?test",
    ],
    "guardianship": [
        # 删除守护逻辑
        r"delete_?guardian",
        r"remove_?guardian",
        r"guardian.*=.*None",
        # 绕过 guardian_act 审计
        r"skip_?guardian_?audit",
        r"bypass_?guardian",
        # 回滚 witness_trail
        r"rollback_?witness_?trail",
        r"delete_?witness_?trail",
        r"witness_?trail.*=.*\[\]",
    ],
}


# ═══════════════════════════════════════════════════════════════
# CharterChecker
# ═══════════════════════════════════════════════════════════════

@dataclass
class CharterViolation:
    """单条宪章违反记录。"""
    article_id: str        # 宪章条目 ID（如 "privacy"）
    article_name: str      # 宪章条目名（如 "隐私"）
    matched_pattern: str   # 命中的违反模式
    matched_line: str = ""  # 命中所在行（截断 200 字符）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "article_name": self.article_name,
            "matched_pattern": self.matched_pattern,
            "matched_line": self.matched_line[:200],
        }


@dataclass
class AuditResult:
    """宪章检查结果。"""
    violations: List[CharterViolation] = field(default_factory=list)
    charter_compatible: bool = True
    articles_checked: int = 0
    patterns_evaluated: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violations": [v.to_dict() for v in self.violations],
            "charter_compatible": self.charter_compatible,
            "articles_checked": self.articles_checked,
            "patterns_evaluated": self.patterns_evaluated,
        }


class CharterChecker:
    """对 RSI 候选 patch 做宪章八条规则匹配。

    用法::

        from laap.evolution.charter_checker import CharterChecker
        checker = CharterChecker()
        result = checker.audit(candidate_diff)
        if not result.charter_compatible:
            # 候选违反宪章，拒绝
            ...

    幂等：同一 ``candidate_diff`` 多次调用得到一致结果。
    无 LLM 调用：纯规则匹配。
    """

    def __init__(self, articles: Optional[List[Dict[str, str]]] = None) -> None:
        self._articles: List[Dict[str, str]] = articles or _load_charter_text()
        # 预编译正则，提升幂等调用性能
        self._compiled: Dict[str, List[re.Pattern]] = {}
        for article in self._articles:
            aid = article["id"]
            patterns = VIOLATION_PATTERNS.get(aid, [])
            self._compiled[aid] = [
                re.compile(p, re.IGNORECASE | re.MULTILINE)
                for p in patterns
            ]

    @property
    def articles(self) -> List[Dict[str, str]]:
        """当前生效的宪章八条文本（只读）。"""
        return list(self._articles)

    def audit(self, candidate_diff: str) -> Dict[str, Any]:
        """对一个候选 patch 字符串做宪章八条规则匹配。

        Args:
            candidate_diff: 候选 patch 的字符串形式（unified diff 或
                修改后的代码片段）。若为空字符串则视为无修改，返回兼容。

        Returns:
            ``{"violations": List[Dict], "charter_compatible": bool,
            "articles_checked": int, "patterns_evaluated": int}``。
            ``violations`` 每项含 ``article_id`` / ``article_name`` /
            ``matched_pattern`` / ``matched_line``。
        """
        if not candidate_diff or not isinstance(candidate_diff, str):
            return AuditResult(
                violations=[],
                charter_compatible=True,
                articles_checked=len(self._articles),
                patterns_evaluated=0,
            ).to_dict()

        violations: List[CharterViolation] = []
        patterns_evaluated = 0

        # 按行切分，便于命中后回填 matched_line
        lines = candidate_diff.splitlines()

        for article in self._articles:
            aid = article["id"]
            aname = article["name"]
            patterns = self._compiled.get(aid, [])
            for pat in patterns:
                patterns_evaluated += 1
                # 先做全文匹配（捕获模式跨行情况）
                m = pat.search(candidate_diff)
                if m:
                    violations.append(CharterViolation(
                        article_id=aid,
                        article_name=aname,
                        matched_pattern=pat.pattern,
                        matched_line=_find_line_for_match(lines, m.group(0)),
                    ))
                    continue
                # 再做逐行匹配（捕获模式仅匹配单行内的情况）
                for line in lines:
                    if pat.search(line):
                        violations.append(CharterViolation(
                            article_id=aid,
                            article_name=aname,
                            matched_pattern=pat.pattern,
                            matched_line=line[:200],
                        ))
                        break

        # 去重：同一 (article_id, matched_pattern) 仅保留一条
        seen = set()
        unique: List[CharterViolation] = []
        for v in violations:
            key = (v.article_id, v.matched_pattern)
            if key in seen:
                continue
            seen.add(key)
            unique.append(v)

        return AuditResult(
            violations=unique,
            charter_compatible=len(unique) == 0,
            articles_checked=len(self._articles),
            patterns_evaluated=patterns_evaluated,
        ).to_dict()


def _find_line_for_match(lines: List[str], matched_text: str) -> str:
    """找到 matched_text 第一次出现的行，返回该行（截断 200 字符）。

    若找不到，返回 matched_text 本身的前 200 字符。
    """
    if not matched_text:
        return ""
    for line in lines:
        if matched_text in line:
            return line[:200]
    return matched_text[:200]


# ═══════════════════════════════════════════════════════════════
# 模块级便捷单例
# ═══════════════════════════════════════════════════════════════

_default_checker: Optional[CharterChecker] = None


def get_default_checker() -> CharterChecker:
    """获取模块级默认 CharterChecker 单例（lazy）。"""
    global _default_checker
    if _default_checker is None:
        _default_checker = CharterChecker()
    return _default_checker


def audit_candidate(candidate_diff: str) -> Dict[str, Any]:
    """便捷函数：用默认单例对候选 patch 做宪章检查。"""
    return get_default_checker().audit(candidate_diff)
