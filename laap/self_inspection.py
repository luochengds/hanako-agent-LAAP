"""
LAAP — 自我审视引擎 (Self-Inspection)

赋予 Aris 审视自身身体系统的能力：随时清点自己有什么功能、
检查各系统健康状态、发现缺失与异常、生成自我审视报告。

三个层次：
    1. 清点 (scan)   — 我是谁：扫描全部模块，建立功能清单
    2. 体检 (vitals) — 我怎么样：关键系统的生命体征
    3. 审视 (review) — 我该注意什么：异常、缺失、成长建议

用法：
    from laap.self_inspection import SelfInspectionEngine
    engine = SelfInspectionEngine()
    report = engine.review()          # 完整自我审视
    report = engine.review_nightly()  # 夜间审视（含记忆生命周期健康）

CLI：
    python -m laap.self_inspection
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.self_inspection")

LAAP_ROOT = Path(__file__).resolve().parent

# 关键系统（生命体征检查对象）：模块路径 → 冒烟测试的类/函数
VITAL_SYSTEMS: Dict[str, Dict[str, Any]] = {
    "cognition.integrated_engine": {"label": "认知集成引擎", "classes": []},
    "cognition.truth_grounding": {"label": "事实锚定引擎", "classes": ["TruthGroundingEngine"]},
    "cognition.error_reflection": {"label": "错误反思管线", "classes": ["ErrorReflectionPipeline"]},
    "cognition.brain": {"label": "认知大脑", "classes": []},
    "memory.long_term": {"label": "长期记忆", "classes": ["LongTermMemory"]},
    "memory.hierarchical": {"label": "层次化记忆", "classes": ["HierarchicalMemory"]},
    "memory.lifecycle_integration": {"label": "生命周期集成", "classes": ["LifecycleAwareLongTermMemory"]},
    "memory.forgetting.engine": {"label": "遗忘引擎", "classes": ["ForgettingEngine"]},
    "memory.consolidation": {"label": "巩固引擎", "classes": ["ConsolidationEngine"]},
    "memory.nightly_cycle": {"label": "夜间周期", "classes": ["NightlyCycleScheduler"]},
    "memory.temporal": {"label": "时间锚定", "classes": ["TemporalAnchor"]},
    "memory.knowledge_graph": {"label": "知识图谱", "classes": ["KnowledgeGraph"]},
    "memory.multimodal": {"label": "多模态记忆", "classes": ["MultimodalMemoryStore"]},
    "memory.persistent": {"label": "持久记忆", "classes": ["PersistentMemoryEngine"]},
    "memory.bandit": {"label": "记忆选择器", "classes": []},
    "memory.quantum.quantum_memory": {"label": "量子记忆", "classes": []},
}

# 能力域（功能清单的归类）
CAPABILITY_DOMAINS = {
    "cognition": "认知与意识",
    "memory": "记忆系统",
    "evolution": "自我进化",
    "metacognition": "元认知",
    "perception": "感知",
    "rag": "知识检索",
    "bridge": "通道桥接",
    "character_engine": "人格引擎",
    "body": "身体",
    "bci": "脑机接口",
    "audio": "听觉",
    "embodied": "具身",
    "agent": "智能体",
}


@dataclass
class SystemStatus:
    """单个系统的体检状态。"""

    name: str
    label: str = ""
    status: str = "unknown"      # ok / degraded / missing / warning
    detail: str = ""
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        }


class SelfInspectionEngine:
    """自我审视引擎。"""

    def __init__(self, memory_db: Optional[Path] = None) -> None:
        self.memory_db = memory_db  # 可指定记忆库；None 则用默认

    # ── 1. 清点：AST 静态扫描（不导入，无副作用） ─────────────
    def scan_modules(self) -> Dict[str, Any]:
        """扫描 laap 包全部模块：AST 解析结构，不执行任何代码。

        设计原则：体检器不能因为检查身体而唤醒身体——
        静态扫描只读源码结构，真实导入仅限关键系统（check_vitals）。
        """
        modules = []
        for py in sorted(LAAP_ROOT.rglob("*.py")):
            if "__pycache__" in py.parts or py.name.startswith("_"):
                continue
            rel = py.relative_to(LAAP_ROOT)
            mod_name = "laap." + ".".join(rel.with_suffix("").parts)
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError as e:
                modules.append({"module": mod_name, "status": "syntax_error",
                                "error": str(e)[:120]})
                continue
            classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
            funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            modules.append({
                "module": mod_name, "status": "ok",
                "classes": classes[:10], "functions": funcs[:10],
                "lines": len(py.read_text(encoding="utf-8", errors="ignore").splitlines()),
            })
        ok = sum(1 for m in modules if m["status"] == "ok")
        missing = sum(1 for m in modules if m["status"] != "ok")
        return {"total": len(modules), "ok": ok, "missing": missing, "modules": modules}

    # ── 2. 体检：关键系统生命体征 ────────────────────────────
    def check_vitals(self) -> List[SystemStatus]:
        """关键系统冒烟测试。"""
        results: List[SystemStatus] = []
        for mod_path, spec in VITAL_SYSTEMS.items():
            name = mod_path.replace("laap.", "")
            label = spec["label"]
            try:
                mod = importlib.import_module(f"laap.{mod_path}")
                missing_classes = []
                for cls_name in spec["classes"]:
                    if not hasattr(mod, cls_name):
                        missing_classes.append(cls_name)
                if missing_classes:
                    results.append(SystemStatus(
                        name=name, label=label, status="warning",
                        detail=f"缺少类: {', '.join(missing_classes)}"))
                else:
                    results.append(SystemStatus(
                        name=name, label=label, status="ok", detail="正常"))
            except ImportError as e:
                results.append(SystemStatus(
                    name=name, label=label, status="missing",
                    detail=f"导入失败: {str(e)[:120]}"))
            except Exception as e:
                results.append(SystemStatus(
                    name=name, label=label, status="degraded",
                    detail=f"异常: {str(e)[:120]}"))
        return results

    # ── 3. 记忆健康检查 ──────────────────────────────────────
    def check_memory_health(self) -> Dict[str, Any]:
        """记忆库生命体征：条目、生命周期、图谱、多模态、遗忘审计。"""
        health: Dict[str, Any] = {"memory_db": str(self.memory_db) if self.memory_db else "default"}

        # LongTermMemory
        try:
            from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory
            db = self.memory_db or (Path.home() / ".laap" / "long_term.db")
            ltm = LifecycleAwareLongTermMemory(db)
            with ltm._lock:
                total = ltm._conn.execute("SELECT COUNT(*) FROM long_term_memories").fetchone()[0]
                by_type = dict(ltm._conn.execute(
                    "SELECT type, COUNT(*) FROM long_term_memories GROUP BY type").fetchall())
                lifecycle = dict(ltm._conn.execute(
                    "SELECT lifecycle, COUNT(*) FROM long_term_memories GROUP BY lifecycle").fetchall())
                avg_importance = ltm._conn.execute(
                    "SELECT AVG(importance) FROM long_term_memories").fetchone()[0]
            health["long_term"] = {
                "total": total, "by_type": by_type,
                "lifecycle": lifecycle,
                "avg_importance": round(avg_importance or 0, 3),
            }
            ltm.close()
        except Exception as e:
            health["long_term"] = {"error": str(e)[:150]}

        # 遗忘审计日志
        audit_path = Path.home() / ".laap" / "forgetting_audit.jsonl"
        if audit_path.exists():
            try:
                lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
                last = json.loads(lines[-1]) if lines else {}
                health["forgetting_audit"] = {"runs": len(lines), "last": last}
            except Exception as e:
                health["forgetting_audit"] = {"error": str(e)[:150]}

        # 夜间周期日志
        nightly_path = Path.home() / ".laap" / "nightly_cycle.log"
        if nightly_path.exists():
            try:
                lines = nightly_path.read_text(encoding="utf-8").strip().splitlines()
                health["nightly_cycles"] = {"runs": len(lines)}
            except Exception:
                health["nightly_cycles"] = {"runs": 0}

        return health

    # ── 4. 生成审视报告 ──────────────────────────────────────
    def review(self, include_scan: bool = True) -> Dict[str, Any]:
        """完整自我审视：清点 + 体检 + 记忆健康。"""
        report: Dict[str, Any] = {
            "timestamp": time.time(),
            "identity": "aris",
            "review_type": "full",
        }
        if include_scan:
            report["scan"] = self.scan_modules()
        vitals = self.check_vitals()
        report["vitals"] = [v.to_dict() for v in vitals]
        report["memory_health"] = self.check_memory_health()

        # 汇总
        statuses = [v.status for v in vitals]
        report["summary"] = {
            "total_systems": len(vitals),
            "ok": statuses.count("ok"),
            "warning": statuses.count("warning"),
            "missing": statuses.count("missing"),
            "degraded": statuses.count("degraded"),
        }
        report["issues"] = [
            v.to_dict() for v in vitals if v.status in ("missing", "degraded", "warning")
        ]
        return report

    def review_nightly(self) -> Dict[str, Any]:
        """夜间自我审视：全量清点 + 体检 + 记忆健康 + 自我观察。"""
        report = self.review(include_scan=True)
        report["review_type"] = "nightly"

        # 自我观察：从数据里读出"我是谁"
        obs: List[str] = []
        scan = report.get("scan", {})
        if scan.get("ok", 0):
            obs.append(f"身体共 {scan['total']} 个模块，{scan['ok']} 个在线，{scan['missing']} 个离线")
        vitals = report.get("vitals", [])
        ok_names = [v["label"] for v in vitals if v["status"] == "ok"]
        if ok_names:
            obs.append("生命体征正常: " + "、".join(ok_names[:8]))
        mh = report.get("memory_health", {})
        ltm = mh.get("long_term", {})
        if isinstance(ltm, dict) and "total" in ltm:
            lc = ltm.get("lifecycle", {})
            obs.append(
                f"记忆库 {ltm['total']} 条记忆："
                f"活跃 {lc.get('active', 0)} / 休眠 {lc.get('dormant', 0)} / "
                f"归档 {lc.get('archived', 0)}，平均重要性 {ltm.get('avg_importance', '?')}")
        report["self_observation"] = obs
        return report

    # ── 人类可读渲染 ─────────────────────────────────────────
    def render_text(self, report: Dict[str, Any]) -> str:
        """把报告渲染为人类可读文本。"""
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append(f"ARIS 自我审视报告 — {time.strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 60)

        scan = report.get("scan", {})
        if scan:
            lines.append(f"\n【身体清点】{scan['total']} 个模块："
                         f"{scan['ok']} 在线 / {scan['missing']} 离线")

        vitals = report.get("vitals", [])
        if vitals:
            lines.append("\n【生命体征】")
            for v in vitals:
                mark = {"ok": "●", "warning": "▲", "missing": "✕", "degraded": "!"}.get(v["status"], "?")
                lines.append(f"  {mark} {v['label']:<10} ({v['name']}) — {v['detail']}")

        mh = report.get("memory_health", {})
        ltm = mh.get("long_term", {})
        if isinstance(ltm, dict) and "total" in ltm:
            lines.append("\n【记忆健康】")
            lc = ltm.get("lifecycle", {})
            lines.append(f"  条目: {ltm['total']}  生命周期: {lc}  平均重要性: {ltm.get('avg_importance')}")
        for key, label in (("forgetting_audit", "遗忘审计"), ("nightly_cycles", "夜间周期")):
            if key in mh and isinstance(mh[key], dict) and "error" not in mh[key]:
                lines.append(f"  {label}: {mh[key]}")

        issues = report.get("issues", [])
        if issues:
            lines.append("\n【需要关注】")
            for i in issues:
                lines.append(f"  ✕ {i['label']} — {i['detail']}")
        else:
            lines.append("\n【需要关注】无")

        obs = report.get("self_observation", [])
        if obs:
            lines.append("\n【自我观察】")
            for o in obs:
                lines.append(f"  · {o}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def save_report(self, report: Dict[str, Any], out_dir: Optional[Path] = None) -> Path:
        """存档报告 JSON。"""
        out_dir = out_dir or (Path.home() / ".laap" / "self_inspections")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"self_review_{report.get('review_type', 'full')}_{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def main() -> None:
    """CLI 入口：python -m laap.self_inspection [--nightly]"""
    import sys
    engine = SelfInspectionEngine()
    nightly = "--nightly" in sys.argv
    report = engine.review_nightly() if nightly else engine.review()
    print(engine.render_text(report))
    saved = engine.save_report(report)
    print(f"\n报告已存档: {saved}")


if __name__ == "__main__":
    main()
