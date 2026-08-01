"""因果链分析引擎

LAAP Phase 2.1 核心模块，建立建议项之间的关联关系模型：

- CausalChainAnalyzer：因果链分析引擎
  * 从最终建议回溯到根因（trace_root_cause）
  * 从根因正向推导到所有影响（analyze_impact）
  * 聚类关联建议（cluster_related）
  * 为建议构建因果链（build_causal_chain）

- CausalSuggestionGenerator：因果建议生成器
  * 从技术债检测生成因果建议（from_tech_debt）
  * 从测试失败生成因果建议（from_test_failure）
  * 从代码复杂度生成因果建议（from_complexity）

因果链节点格式：
    {
        "node": "根因描述",        # 节点说明
        "confidence": 0.9,         # 该节点的置信度 0-1
        "source": "scanner",       # 数据来源标记
        "suggestion_id": "可选"    # 关联到具体建议的 ID
    }

因果链方向：链首为根因，链尾为最终建议。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from laap.sandbox._types import Suggestion
from laap.workspace.storage import SuggestionQueue


class CausalChainAnalyzer:
    """因果链分析引擎 - 建立建议项之间的关联关系模型。

    基于 Suggestion 的 causal_chain 字段，建立建议之间的因果关联：
    - 因果链是一条从根因到最终建议的路径
    - 链的第一个节点是根因，最后一个节点是当前建议
    - 同一根因的建议可以聚类分组

    用法：
        queue = SuggestionQueue(db_path="laap.db")
        analyzer = CausalChainAnalyzer(queue)
        suggestion = analyzer.build_causal_chain(suggestion)
        chain = analyzer.trace_root_cause(suggestion.suggestion_id)
        clusters = analyzer.cluster_related()
    """

    def __init__(self, suggestion_queue: SuggestionQueue):
        """
        Args:
            suggestion_queue: 建议队列，用于查询建议数据
        """
        self._queue = suggestion_queue

    def trace_root_cause(self, suggestion_id: str) -> List[Dict]:
        """从最终建议回溯到根因。

        根据建议 ID 查找其因果链，返回从当前建议回溯到根因的路径。
        内部存储的因果链方向为「根因 → 建议」，
        回溯时反转为「建议 → 根因」。

        Args:
            suggestion_id: 建议 ID

        Returns:
            因果链路径（从当前建议到根因的节点列表），
            如果建议不存在或无因果链则返回空列表
        """
        suggestion = self._find_suggestion(suggestion_id)
        if not suggestion or not suggestion.causal_chain:
            return []

        # 因果链默认从根因到当前建议，回溯时反转
        chain = list(suggestion.causal_chain)
        chain.reverse()
        return chain

    def analyze_impact(self, root_cause_id: str) -> List[Dict]:
        """从根因正向推导到所有影响。

        查找所有因果链中包含该根因的建议。
        支持两种匹配方式：
        1. 通过建议 ID 匹配（因果链节点中的 suggestion_id 字段）
        2. 通过根因聚类 key 匹配（基于根因文本生成的哈希）

        Args:
            root_cause_id: 根因建议 ID 或根因节点的聚类 key

        Returns:
            所有受影响的建议列表，每项包含：
            {
                "suggestion_id": 建议 ID,
                "title": 标题,
                "category": 类别,
                "priority": 优先级,
                "confidence": 置信度,
                "causal_chain": 因果链
            }
        """
        all_suggestions = self._queue.peek_all()
        impacted: List[Dict[str, Any]] = []

        for suggestion in all_suggestions:
            if not suggestion.causal_chain:
                continue

            # 遍历因果链节点，检查是否包含目标根因
            for node in suggestion.causal_chain:
                node_suggestion_id = node.get("suggestion_id", "")
                node_key = self._root_cause_key(node.get("node", ""))

                if (node_suggestion_id == root_cause_id or
                        node_key == root_cause_id):
                    impacted.append({
                        "suggestion_id": suggestion.suggestion_id,
                        "title": suggestion.title,
                        "category": suggestion.category,
                        "priority": suggestion.priority,
                        "confidence": suggestion.confidence,
                        "causal_chain": suggestion.causal_chain,
                    })
                    break

        return impacted

    def cluster_related(self) -> Dict[str, List[Suggestion]]:
        """聚类关联建议（同根因的建议分组）。

        根据因果链的根因节点（第一个节点）对建议进行分组。
        无因果链的建议按类别归入 "no_chain:{category}" 分组。

        Returns:
            {cluster_key: [suggestions]} 聚类结果
        """
        all_suggestions = self._queue.peek_all()
        clusters: Dict[str, List[Suggestion]] = {}

        for suggestion in all_suggestions:
            cluster_key = self._get_cluster_key(suggestion)

            if cluster_key not in clusters:
                clusters[cluster_key] = []
            clusters[cluster_key].append(suggestion)

        return clusters

    def build_causal_chain(self, suggestion: Suggestion) -> Suggestion:
        """为建议构建因果链。

        根据建议的 category 和 target_file 分析因果，
        填充 suggestion.causal_chain 字段并返回。

        不同类别的因果链模板：
        - tech_debt:  临时方案 → 连锁 bug → 当前债务
        - test_gap:   缺失测试 → 未覆盖路径 → 生产 bug 风险
        - bug:        根因分析 → 触发条件 → 当前 bug
        - refactor:   圈复杂度过高 → 维护困难 → 重构需求
        - dependency: 依赖过期/冲突 → 兼容性问题 → 构建/运行风险
        - security:   依赖漏洞 → 安全风险 → 潜在攻击面

        Args:
            suggestion: 待分析的建议

        Returns:
            填充了 causal_chain 的建议（原地修改并返回）
        """
        category = suggestion.category or "unknown"
        target = suggestion.target_file or "全局"

        # 按类别选择因果链构建器
        chain_builders = {
            "tech_debt": self._build_tech_debt_chain,
            "test_gap": self._build_test_gap_chain,
            "bug": self._build_bug_chain,
            "refactor": self._build_refactor_chain,
            "dependency": self._build_dependency_chain,
            "security": self._build_security_chain,
        }

        builder = chain_builders.get(category, self._build_default_chain)
        suggestion.causal_chain = builder(suggestion, target)

        # 根据因果链各节点置信度计算整体置信度（取平均值）
        if suggestion.causal_chain:
            avg_confidence = sum(
                node.get("confidence", 0.5) for node in suggestion.causal_chain
            ) / len(suggestion.causal_chain)
            suggestion.confidence = round(avg_confidence, 3)

        # 生成可解释性描述
        suggestion.explanation = self._generate_explanation(suggestion)

        # 仅在未设置 source_data 时填充默认值，保留上游来源标记
        if not suggestion.source_data:
            suggestion.source_data = "causal_analyzer"

        return suggestion

    def to_json(self, chain: List[Dict]) -> str:
        """输出因果链 JSON 供前端渲染。

        Args:
            chain: 因果链节点列表

        Returns:
            JSON 字符串，格式为 {"chain": [...], "length": N}
        """
        return json.dumps({
            "chain": chain,
            "length": len(chain),
        }, ensure_ascii=False, indent=2)

    # ===== 内部辅助方法 =====

    def _find_suggestion(self, suggestion_id: str) -> Optional[Suggestion]:
        """根据 ID 查找建议。

        遍历队列中的所有建议查找匹配项。
        """
        for suggestion in self._queue.peek_all():
            if suggestion.suggestion_id == suggestion_id:
                return suggestion
        return None

    def _get_cluster_key(self, suggestion: Suggestion) -> str:
        """获取建议的聚类 key（基于根因）。

        有因果链时使用根因节点的哈希，无因果链时按类别归组。
        """
        if suggestion.causal_chain:
            root_node = suggestion.causal_chain[0]
            return self._root_cause_key(root_node.get("node", "unknown"))
        return f"no_chain:{suggestion.category or 'unknown'}"

    def _root_cause_key(self, root_cause_text: str) -> str:
        """根据根因文本生成聚类 key。

        使用 MD5 哈希的前 12 位字符，避免 key 过长同时保证唯一性。
        """
        return hashlib.md5(root_cause_text.encode("utf-8")).hexdigest()[:12]

    def _generate_explanation(self, suggestion: Suggestion) -> str:
        """根据因果链生成可解释性描述。"""
        if not suggestion.causal_chain:
            return suggestion.description

        # 用箭头连接因果链各节点形成描述
        chain_desc = " → ".join(
            node.get("node", "") for node in suggestion.causal_chain
        )
        return f"因果链：{chain_desc}\n置信度：{suggestion.confidence:.0%}"

    def _build_tech_debt_chain(self, suggestion: Suggestion,
                                target: str) -> List[Dict[str, Any]]:
        """构建技术债因果链：临时方案 → 连锁 bug → 当前债务"""
        return [
            {
                "node": f"历史临时方案（{target} 中遗留的快速修复）",
                "confidence": 0.85,
                "source": "tech_debt_scanner",
            },
            {
                "node": "临时方案引入连锁 bug，增加维护成本",
                "confidence": 0.75,
                "source": "causal_analyzer",
            },
            {
                "node": f"当前技术债：{suggestion.title}",
                "confidence": 0.9,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_test_gap_chain(self, suggestion: Suggestion,
                               target: str) -> List[Dict[str, Any]]:
        """构建测试缺口因果链：缺失测试 → 未覆盖路径 → 生产 bug 风险"""
        return [
            {
                "node": f"缺失测试用例（{target} 未被测试覆盖）",
                "confidence": 0.8,
                "source": "test_scanner",
            },
            {
                "node": "关键路径未被测试覆盖，缺陷难以被发现",
                "confidence": 0.7,
                "source": "causal_analyzer",
            },
            {
                "node": f"生产 bug 风险：{suggestion.title}",
                "confidence": 0.85,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_bug_chain(self, suggestion: Suggestion,
                          target: str) -> List[Dict[str, Any]]:
        """构建 bug 因果链：根因 → 触发条件 → 当前 bug"""
        return [
            {
                "node": f"代码缺陷（{target} 中的逻辑或实现问题）",
                "confidence": 0.8,
                "source": "bug_scanner",
            },
            {
                "node": "特定输入或运行条件触发了缺陷",
                "confidence": 0.65,
                "source": "causal_analyzer",
            },
            {
                "node": f"当前 bug：{suggestion.title}",
                "confidence": 0.9,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_refactor_chain(self, suggestion: Suggestion,
                                target: str) -> List[Dict[str, Any]]:
        """构建重构因果链：圈复杂度过高 → 维护困难 → 重构需求"""
        return [
            {
                "node": f"圈复杂度过高（{target} 函数/模块过于复杂）",
                "confidence": 0.8,
                "source": "complexity_scanner",
            },
            {
                "node": "维护困难，新增功能易引入 bug",
                "confidence": 0.7,
                "source": "causal_analyzer",
            },
            {
                "node": f"重构需求：{suggestion.title}",
                "confidence": 0.85,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_dependency_chain(self, suggestion: Suggestion,
                                  target: str) -> List[Dict[str, Any]]:
        """构建依赖因果链：依赖过期/冲突 → 兼容性问题 → 构建/运行风险"""
        return [
            {
                "node": "依赖版本过期或存在冲突",
                "confidence": 0.8,
                "source": "dependency_scanner",
            },
            {
                "node": "兼容性问题导致部分功能异常",
                "confidence": 0.65,
                "source": "causal_analyzer",
            },
            {
                "node": f"构建/运行风险：{suggestion.title}",
                "confidence": 0.85,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_security_chain(self, suggestion: Suggestion,
                                target: str) -> List[Dict[str, Any]]:
        """构建安全因果链：依赖漏洞 → 安全风险 → 潜在攻击面"""
        return [
            {
                "node": "依赖包存在已知安全漏洞",
                "confidence": 0.9,
                "source": "security_scanner",
            },
            {
                "node": "安全风险：漏洞可能被利用",
                "confidence": 0.75,
                "source": "causal_analyzer",
            },
            {
                "node": f"潜在攻击面：{suggestion.title}",
                "confidence": 0.85,
                "source": "scanner",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]

    def _build_default_chain(self, suggestion: Suggestion,
                              target: str) -> List[Dict[str, Any]]:
        """构建默认因果链（未知类别）。"""
        return [
            {
                "node": f"潜在问题（{target}）",
                "confidence": 0.6,
                "source": "scanner",
            },
            {
                "node": f"当前建议：{suggestion.title}",
                "confidence": 0.7,
                "source": "causal_analyzer",
                "suggestion_id": suggestion.suggestion_id,
            },
        ]


class CausalSuggestionGenerator:
    """因果建议生成器 - 从检测结果生成带因果链的建议。

    与普通建议不同，因果建议自带因果链分析，
    可以追溯根因并评估影响范围。

    用法：
        queue = SuggestionQueue(db_path="laap.db")
        generator = CausalSuggestionGenerator(queue)
        suggestion = generator.from_tech_debt(debt_items)
        queue.push(suggestion)
    """

    def __init__(self, suggestion_queue: SuggestionQueue):
        """
        Args:
            suggestion_queue: 建议队列，用于持久化建议
        """
        self._queue = suggestion_queue
        self._analyzer = CausalChainAnalyzer(suggestion_queue)

    def from_tech_debt(self, debt_items: List[Dict[str, Any]]) -> Suggestion:
        """从技术债检测生成因果建议。

        因果链：临时方案 → 连锁 bug → 当前债务

        Args:
            debt_items: 技术债检测结果列表，每项为包含 path/markers
                        等信息的 dict

        Returns:
            带因果链的技术债建议
        """
        if not debt_items:
            return Suggestion()

        # 聚合技术债信息：统计总标记数，取第一个热点文件
        total_markers = sum(
            item.get("markers", 0) if isinstance(item, dict) else 0
            for item in debt_items
        )
        hotspot_path = ""
        if debt_items and isinstance(debt_items[0], dict):
            hotspot_path = debt_items[0].get("path", "")

        # 根据标记数量决定优先级
        if total_markers >= 20:
            priority = "critical"
        elif total_markers >= 10:
            priority = "high"
        else:
            priority = "medium"

        suggestion = Suggestion(
            title=f"技术债清理（{total_markers} 个标记待处理）",
            description=(f"检测到 {total_markers} 个技术债标记，"
                         f"热点文件：{hotspot_path or '未知'}"),
            priority=priority,
            relevance=min(0.9, 0.4 + total_markers * 0.03),
            category="tech_debt",
            target_file=hotspot_path or None,
            actions=[
                "处理热点文件中的 TODO/FIXME 标记",
                "评估临时方案是否需要重构",
                "制定技术债清理计划",
            ],
            source_data="tech_debt_scanner",
        )

        # 构建因果链并返回
        return self._analyzer.build_causal_chain(suggestion)

    def from_test_failure(self, test_results: List[Dict[str, Any]]) -> Suggestion:
        """从测试失败生成因果建议。

        因果链：缺失测试 → 未覆盖路径 → 生产 bug

        Args:
            test_results: 测试结果列表，每项为包含 name/status/error
                          等信息的 dict

        Returns:
            带因果链的测试缺口建议
        """
        if not test_results:
            return Suggestion()

        # 筛选失败的测试用例
        failed_tests = [
            t for t in test_results
            if isinstance(t, dict) and t.get("status") == "failed"
        ]
        failed_count = len(failed_tests)

        if failed_count == 0:
            # 没有失败，但可能覆盖率不足
            suggestion = Suggestion(
                title="补充测试用例提升覆盖率",
                description="当前测试覆盖率不足，建议补充关键路径测试。",
                priority="medium",
                relevance=0.7,
                category="test_gap",
                actions=["识别未覆盖的关键路径", "补充对应测试用例"],
                source_data="test_scanner",
            )
        else:
            # 取前 3 个失败测试名称用于描述
            failed_names = [t.get("name", "unknown") for t in failed_tests[:3]]
            suggestion = Suggestion(
                title=f"修复 {failed_count} 个失败的测试用例",
                description=f"失败的测试：{', '.join(failed_names)}",
                priority="critical" if failed_count > 3 else "high",
                relevance=0.85,
                category="test_gap",
                actions=[
                    "分析失败测试的根因",
                    "修复代码或更新测试",
                    "补充缺失的测试路径",
                ],
                source_data="test_scanner",
            )

        return self._analyzer.build_causal_chain(suggestion)

    def from_complexity(self, complexity_data: Dict[str, Any]) -> Suggestion:
        """从代码复杂度生成因果建议。

        因果链：圈复杂度过高 → 维护困难 → 引入 bug 风险

        Args:
            complexity_data: 复杂度数据 dict，包含 file/function/complexity
                              等字段

        Returns:
            带因果链的重构建议
        """
        if not complexity_data:
            return Suggestion()

        file_path = complexity_data.get("file", "")
        function_name = complexity_data.get("function", "")
        complexity = complexity_data.get("complexity", 0)

        # 根据圈复杂度决定优先级
        if complexity >= 20:
            priority = "critical"
        elif complexity >= 15:
            priority = "high"
        else:
            priority = "medium"

        suggestion = Suggestion(
            title=f"重构高复杂度函数 {function_name or '未知'}",
            description=(f"文件 {file_path} 中的函数 {function_name} "
                         f"圈复杂度为 {complexity}，"
                         f"{'严重超标' if complexity >= 20 else '偏高'}，"
                         f"建议拆分重构。"),
            priority=priority,
            relevance=min(0.95, 0.5 + complexity * 0.02),
            category="refactor",
            target_file=file_path or None,
            actions=[
                f"拆分 {function_name} 函数，降低单函数复杂度",
                "提取重复逻辑为独立函数",
                "补充对应单元测试",
            ],
            source_data="complexity_scanner",
        )

        return self._analyzer.build_causal_chain(suggestion)


__all__ = ["CausalChainAnalyzer", "CausalSuggestionGenerator"]
