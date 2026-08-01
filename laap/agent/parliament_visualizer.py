"""
LAAP — 议会辩论可视化模块 (Parliament Debate Visualization)

为议会系统提供可视化的辩论过程记录和展示功能。

核心功能：
  1. 实时记录辩论过程
  2. 生成结构化的辩论记录
  3. 生成 HTML 可视化报告
  4. 支持多种可视化模式（时间线、投票分布、意见图谱）
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import time
import json
import uuid
from datetime import datetime
from .parliament import Parliament, Deliberation, Opinion, MemberProfile


@dataclass
class DebateStep:
    """
    辩论步骤 — 记录辩论过程中的每个发言回合
    
    包含：发言者、时间、内容、立场、情绪等信息
    """
    id: str = ""
    member_id: str = ""
    member_name: str = ""
    member_role: str = ""
    round: int = 0                    # 发言轮次
    timestamp: float = 0.0            # 发言时间
    stance: str = ""                  # 立场
    argument: str = ""                # 发言内容
    confidence: float = 0.5           # 置信度
    response_to: Optional[str] = None # 回应的上一个发言ID
    supporting: List[str] = field(default_factory=list)   # 支持哪些观点
    challenging: List[str] = field(default_factory=list)  # 挑战哪些观点
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "member": self.member_name,
            "role": self.member_role,
            "round": self.round,
            "stance": self.stance,
            "confidence": round(self.confidence, 2),
            "argument": self.argument[:100],
            "timestamp": self.timestamp,
        }


@dataclass
class DebateVisualizationRecord:
    """
    辩论可视化记录 — 完整的辩论过程记录，用于生成可视化报告
    
    包含：议题信息、所有发言、投票结果、可视化配置
    """
    id: str = ""
    topic: str = ""
    context: str = ""
    steps: List[DebateStep] = field(default_factory=list)
    final_decision: str = ""
    decision_confidence: float = 0.0
    consensus: str = ""
    dissent_count: int = 0
    duration_ms: float = 0.0
    timestamp: float = 0.0
    member_stats: Dict[str, dict] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "topic": self.topic,
            "steps": len(self.steps),
            "decision": self.final_decision,
            "confidence": round(self.decision_confidence, 2),
            "duration_ms": round(self.duration_ms, 1),
            "dissent": self.dissent_count,
        }


class ParliamentVisualizer:
    """
    议会辩论可视化器 — 负责记录和可视化辩论过程
    
    支持的可视化模式：
    1. TIMELINE - 时间线视图（展示发言顺序）
    2. VOTING - 投票分布图
    3. OPINION_MAP - 意见关系图谱
    4. HEAT_MAP - 参与热度图
    """

    def __init__(self, parliament: Parliament):
        self.parliament = parliament
        self.records: List[DebateVisualizationRecord] = []
        self._max_records = 100
        
    def record_debate(self, deliberation: Deliberation) -> DebateVisualizationRecord:
        """
        将审议过程转换为可视化记录
        
        Args:
            deliberation: 议会审议记录
            
        Returns:
            可视化记录对象
        """
        record = DebateVisualizationRecord(
            id=deliberation.id,
            topic=deliberation.topic,
            context=deliberation.context,
            final_decision=deliberation.final_decision,
            decision_confidence=deliberation.decision_confidence,
            consensus=deliberation.consensus or "",
            dissent_count=len(deliberation.dissenting_views),
            duration_ms=deliberation.duration_ms,
            timestamp=deliberation.timestamp,
            member_stats=self.parliament.get_member_stats(),
        )
        
        # 将意见转换为辩论步骤
        round_num = 1
        for opinion in deliberation.opinions:
            member = self.parliament.members.get(opinion.member_id)
            if not member:
                continue
                
            step = DebateStep(
                id=str(uuid.uuid4())[:8],
                member_id=opinion.member_id,
                member_name=member.name,
                member_role=member.role.value,
                round=round_num,
                timestamp=deliberation.timestamp + round_num * 100,
                stance=opinion.stance,
                argument=opinion.argument,
                confidence=opinion.confidence,
            )
            record.steps.append(step)
            round_num += 1
        
        # 添加议长综合步骤
        if deliberation.consensus:
            step = DebateStep(
                id=str(uuid.uuid4())[:8],
                member_id="speaker",
                member_name="议长",
                member_role="speaker",
                round=round_num,
                timestamp=deliberation.timestamp + round_num * 100,
                stance="综合",
                argument=deliberation.consensus,
                confidence=deliberation.decision_confidence,
            )
            record.steps.append(step)
        
        # 添加最终决议步骤
        step = DebateStep(
            id=str(uuid.uuid4())[:8],
            member_id="decision",
            member_name="决议",
            member_role="decision",
            round=round_num + 1,
            timestamp=deliberation.timestamp + (round_num + 1) * 100,
            stance="决议",
            argument=deliberation.final_decision,
            confidence=deliberation.decision_confidence,
        )
        record.steps.append(step)
        
        self.records.append(record)
        if len(self.records) > self._max_records:
            self.records = self.records[-self._max_records:]
            
        return record

    def generate_html_report(self, record_id: str = None, 
                             output_path: str = None) -> str:
        """
        生成辩论过程的 HTML 可视化报告
        
        Args:
            record_id: 指定记录ID（None表示最新记录）
            output_path: 输出文件路径（None表示返回HTML字符串）
            
        Returns:
            HTML字符串或保存路径
        """
        # 获取记录
        if record_id:
            record = next((r for r in self.records if r.id == record_id), None)
        else:
            record = self.records[-1] if self.records else None
            
        if not record:
            return "<html><body><h1>未找到辩论记录</h1></body></html>"
        
        # 生成HTML
        html = self._generate_timeline_html(record)
        html += self._generate_voting_chart(record)
        html += self._generate_opinion_map(record)
        
        full_html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>议会辩论记录 - {record.topic}</title>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        {self._generate_header(record)}
        {html}
    </div>
    <script>{self._get_javascript()}</script>
</body>
</html>
"""
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_html)
            return output_path
        return full_html
    
    def _generate_header(self, record: DebateVisualizationRecord) -> str:
        """生成报告头部"""
        time_str = datetime.fromtimestamp(record.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        return f"""
<div class="header">
    <h1>议会辩论记录</h1>
    <div class="meta">
        <span class="badge">ID: {record.id[:8]}</span>
        <span class="badge">{time_str}</span>
        <span class="badge duration">耗时: {record.duration_ms:.0f}ms</span>
    </div>
    <h2>{record.topic}</h2>
    {f'<p class="context">{record.context}</p>' if record.context else ''}
</div>
"""
    
    def _generate_timeline_html(self, record: DebateVisualizationRecord) -> str:
        """生成时间线视图"""
        steps_html = ""
        for step in record.steps:
            role_color = self._get_role_color(step.member_role)
            stance_color = self._get_stance_color(step.stance)
            
            steps_html += f"""
<div class="timeline-item">
    <div class="timeline-dot" style="background-color: {role_color}"></div>
    <div class="timeline-content">
        <div class="timeline-header">
            <span class="member-name" style="color: {role_color}">{step.member_name}</span>
            <span class="role-badge" style="background-color: {role_color}">{step.member_role}</span>
            <span class="round">第{step.round}轮</span>
        </div>
        <div class="timeline-body">
            <span class="stance-badge" style="background-color: {stance_color}">{step.stance}</span>
            <p class="argument">{step.argument}</p>
        </div>
        <div class="timeline-footer">
            <span class="confidence">置信度: {step.confidence:.0%}</span>
        </div>
    </div>
</div>
"""
        
        return f"""
<div class="section">
    <h3>📅 辩论时间线</h3>
    <div class="timeline">
        {steps_html}
    </div>
</div>
"""
    
    def _generate_voting_chart(self, record: DebateVisualizationRecord) -> str:
        """生成投票分布图"""
        # 统计各立场
        stance_counts = {}
        for step in record.steps:
            if step.member_role not in ["speaker", "decision"]:
                stance_counts[step.stance] = stance_counts.get(step.stance, 0) + 1
        
        total = sum(stance_counts.values()) or 1
        
        bars_html = ""
        for stance, count in sorted(stance_counts.items(), key=lambda x: -x[1]):
            percentage = (count / total) * 100
            color = self._get_stance_color(stance)
            bars_html += f"""
<div class="vote-bar-container">
    <span class="vote-label">{stance}</span>
    <div class="vote-bar-bg">
        <div class="vote-bar" style="width: {percentage}%; background-color: {color}"></div>
    </div>
    <span class="vote-count">{count} ({percentage:.0%})</span>
</div>
"""
        
        return f"""
<div class="section">
    <h3>🗳️ 投票分布</h3>
    <div class="voting-chart">
        {bars_html}
        <div class="final-decision">
            <span class="decision-label">最终决议:</span>
            <span class="decision-value" style="color: {self._get_stance_color(record.final_decision)}">
                {record.final_decision}
            </span>
            <span class="decision-confidence">置信度: {record.decision_confidence:.0%}</span>
        </div>
    </div>
</div>
"""
    
    def _generate_opinion_map(self, record: DebateVisualizationRecord) -> str:
        """生成意见关系图谱"""
        nodes = []
        edges = []
        
        # 添加节点
        for step in record.steps:
            if step.member_role in ["speaker", "decision"]:
                continue
            nodes.append({
                "id": step.id,
                "name": step.member_name,
                "role": step.member_role,
                "stance": step.stance,
                "confidence": step.confidence,
            })
        
        # 添加关系（简单处理：按发言顺序连接）
        for i in range(len(nodes) - 1):
            edges.append({
                "from": nodes[i]["id"],
                "to": nodes[i + 1]["id"],
                "label": "→",
            })
        
        # 生成节点HTML
        nodes_html = ""
        for node in nodes:
            color = self._get_role_color(node["role"])
            nodes_html += f"""
<div class="opinion-node" style="border-color: {color}">
    <div class="node-header" style="background-color: {color}">
        {node['name']}
    </div>
    <div class="node-body">
        <span class="node-stance">{node['stance']}</span>
        <span class="node-confidence">{node['confidence']:.0%}</span>
    </div>
</div>
"""
        
        return f"""
<div class="section">
    <h3>🧠 意见图谱</h3>
    <div class="opinion-map">
        <div class="opinion-nodes">
            {nodes_html}
        </div>
        <div class="opinion-summary">
            <p>参与议员: {len(nodes)} 位</p>
            <p>反对意见: {record.dissent_count} 条</p>
            <p>共识率: {((len(nodes) - record.dissent_count) / max(1, len(nodes))) * 100:.0%}</p>
        </div>
    </div>
</div>
"""
    
    def _get_role_color(self, role: str) -> str:
        """获取角色对应的颜色"""
        colors = {
            "rational": "#4A90D9",      # 蓝色 - 理性分析员
            "creative": "#E91E63",       # 粉色 - 创意专家
            "safety": "#F44336",         # 红色 - 安全卫士
            "pragmatist": "#9C27B0",     # 紫色 - 实用主义者
            "experience": "#FF9800",     # 橙色 - 经验顾问
            "empath": "#00BCD4",         # 青色 - 共情者
            "skeptic": "#795548",        # 棕色 - 怀疑论者
            "meta": "#607D8B",           # 灰色 - 元认知观察员
            "speaker": "#4CAF50",        # 绿色 - 议长
            "decision": "#2196F3",       # 深蓝 - 决议
        }
        return colors.get(role, "#9E9E9E")
    
    def _get_stance_color(self, stance: str) -> str:
        """获取立场对应的颜色"""
        if "支持" in stance:
            return "#4CAF50"      # 绿色
        elif "反对" in stance or "否决" in stance:
            return "#F44336"      # 红色
        elif "条件" in stance:
            return "#FF9800"      # 橙色
        elif "中立" in stance:
            return "#9E9E9E"      # 灰色
        elif "探索" in stance:
            return "#E91E63"      # 粉色
        elif "谨慎" in stance:
            return "#FFC107"      # 黄色
        elif "质疑" in stance:
            return "#795548"      # 棕色
        elif "监控" in stance:
            return "#607D8B"      # 灰色
        elif "综合" in stance:
            return "#9C27B0"      # 紫色
        elif "决议" in stance:
            return "#2196F3"      # 深蓝
        else:
            return "#607D8B"
    
    def _get_css(self) -> str:
        """获取样式表"""
        return """
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    padding: 20px;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
}

.header {
    background: white;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}

.header h1 {
    color: #333;
    margin-bottom: 12px;
    font-size: 24px;
}

.header h2 {
    color: #555;
    margin-top: 16px;
    font-size: 20px;
}

.header .meta {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.badge {
    background: #f0f0f0;
    color: #666;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
}

.badge.duration {
    background: #E3F2FD;
    color: #1976D2;
}

.context {
    color: #666;
    margin-top: 8px;
    font-size: 14px;
    line-height: 1.6;
}

.section {
    background: white;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}

.section h3 {
    color: #333;
    margin-bottom: 20px;
    font-size: 18px;
    border-bottom: 2px solid #f0f0f0;
    padding-bottom: 10px;
}

/* Timeline Styles */
.timeline {
    position: relative;
    padding-left: 30px;
}

.timeline::before {
    content: '';
    position: absolute;
    left: 8px;
    top: 0;
    bottom: 0;
    width: 2px;
    background: #f0f0f0;
}

.timeline-item {
    position: relative;
    margin-bottom: 20px;
}

.timeline-dot {
    position: absolute;
    left: -26px;
    top: 6px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 3px solid white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.timeline-content {
    background: #fafafa;
    border-radius: 12px;
    padding: 16px;
    transition: transform 0.2s, box-shadow 0.2s;
}

.timeline-content:hover {
    transform: translateX(5px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.timeline-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
    flex-wrap: wrap;
}

.member-name {
    font-weight: 600;
    font-size: 16px;
}

.role-badge {
    color: white;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    text-transform: uppercase;
}

.round {
    color: #999;
    font-size: 12px;
    margin-left: auto;
}

.timeline-body {
    margin-bottom: 8px;
}

.stance-badge {
    color: white;
    padding: 3px 12px;
    border-radius: 15px;
    font-size: 12px;
    margin-right: 10px;
}

.argument {
    color: #555;
    font-size: 14px;
    line-height: 1.5;
}

.timeline-footer {
    display: flex;
    justify-content: flex-end;
}

.confidence {
    color: #666;
    font-size: 12px;
    background: #E8F5E9;
    padding: 4px 10px;
    border-radius: 10px;
}

/* Voting Chart Styles */
.voting-chart {
    padding: 10px;
}

.vote-bar-container {
    display: flex;
    align-items: center;
    gap: 15px;
    margin-bottom: 12px;
}

.vote-label {
    width: 80px;
    font-size: 14px;
    color: #555;
    font-weight: 500;
}

.vote-bar-bg {
    flex: 1;
    height: 24px;
    background: #f0f0f0;
    border-radius: 12px;
    overflow: hidden;
}

.vote-bar {
    height: 100%;
    border-radius: 12px;
    transition: width 0.5s ease;
}

.vote-count {
    width: 80px;
    text-align: right;
    font-size: 14px;
    color: #666;
}

.final-decision {
    margin-top: 20px;
    padding: 16px;
    background: #f8f9fa;
    border-radius: 12px;
    display: flex;
    align-items: center;
    gap: 15px;
    flex-wrap: wrap;
}

.decision-label {
    font-weight: 600;
    color: #333;
}

.decision-value {
    font-weight: 700;
    font-size: 18px;
}

.decision-confidence {
    color: #666;
    font-size: 14px;
}

/* Opinion Map Styles */
.opinion-map {
    display: grid;
    grid-template-columns: 1fr 200px;
    gap: 20px;
}

.opinion-nodes {
    display: flex;
    flex-wrap: wrap;
    gap: 15px;
}

.opinion-node {
    width: 150px;
    border-radius: 12px;
    border: 3px solid;
    overflow: hidden;
    transition: transform 0.2s;
}

.opinion-node:hover {
    transform: translateY(-5px);
}

.node-header {
    color: white;
    padding: 10px;
    text-align: center;
    font-weight: 600;
}

.node-body {
    padding: 12px;
    background: white;
    text-align: center;
}

.node-stance {
    display: block;
    font-size: 13px;
    color: #555;
    margin-bottom: 5px;
}

.node-confidence {
    font-size: 16px;
    font-weight: 600;
    color: #4CAF50;
}

.opinion-summary {
    background: #f8f9fa;
    border-radius: 12px;
    padding: 16px;
}

.opinion-summary p {
    color: #555;
    margin-bottom: 8px;
    font-size: 14px;
}

.opinion-summary p:last-child {
    margin-bottom: 0;
}

@media (max-width: 768px) {
    .opinion-map {
        grid-template-columns: 1fr;
    }
    
    .timeline-header {
        flex-direction: column;
        align-items: flex-start;
    }
    
    .round {
        margin-left: 0;
    }
}
"""
    
    def _get_javascript(self) -> str:
        """获取JavaScript脚本"""
        return """
document.addEventListener('DOMContentLoaded', function() {
    // 为时间线项添加动画
    const timelineItems = document.querySelectorAll('.timeline-item');
    timelineItems.forEach((item, index) => {
        item.style.opacity = '0';
        item.style.transform = 'translateX(-20px)';
        setTimeout(() => {
            item.style.transition = 'opacity 0.5s, transform 0.5s';
            item.style.opacity = '1';
            item.style.transform = 'translateX(0)';
        }, index * 100);
    });
    
    // 为投票条添加动画
    const voteBars = document.querySelectorAll('.vote-bar');
    voteBars.forEach((bar, index) => {
        bar.style.width = '0%';
        setTimeout(() => {
            const targetWidth = bar.getAttribute('style').match(/width:\\s*([\\d.]+)%/)[1];
            bar.style.transition = 'width 0.8s ease';
            bar.style.width = targetWidth + '%';
        }, index * 150 + 500);
    });
    
    // 点击节点显示详情
    const nodes = document.querySelectorAll('.opinion-node');
    nodes.forEach(node => {
        node.addEventListener('click', function() {
            this.classList.toggle('expanded');
        });
    });
});
"""

    def export_to_json(self, record_id: str = None) -> str:
        """
        导出辩论记录为JSON格式
        
        Args:
            record_id: 指定记录ID（None表示最新记录）
            
        Returns:
            JSON字符串
        """
        if record_id:
            record = next((r for r in self.records if r.id == record_id), None)
        else:
            record = self.records[-1] if self.records else None
            
        if not record:
            return json.dumps({"error": "未找到记录"}, ensure_ascii=False)
            
        data = {
            "id": record.id,
            "topic": record.topic,
            "context": record.context,
            "timestamp": record.timestamp,
            "duration_ms": record.duration_ms,
            "final_decision": record.final_decision,
            "decision_confidence": record.decision_confidence,
            "consensus": record.consensus,
            "dissent_count": record.dissent_count,
            "steps": [step.to_dict() for step in record.steps],
            "member_stats": record.member_stats,
        }
        
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def get_recent_records(self, n: int = 5) -> List[DebateVisualizationRecord]:
        """获取最近N条辩论记录"""
        return self.records[-n:]
    
    def clear_records(self):
        """清除所有记录"""
        self.records = []
        logger.info("已清除所有辩论可视化记录")
class ParliamentWithVisualization(Parliament):
    """
    带可视化功能的议会类
    
    在原有的议会功能基础上增加辩论过程可视化能力
    """
    
    def __init__(self, agent_id: str = ""):
        super().__init__(agent_id)
        self.visualizer = ParliamentVisualizer(self)
    
    def deliberate(self, topic: str, context: str = "",
                   roles: List[str] = None,
                   fast_mode: bool = False) -> Deliberation:
        """
        执行审议并记录可视化数据
        
        Returns:
            Deliberation: 审议记录
        """
        deliberation = super().deliberate(topic, context, roles, fast_mode)
        
        # 自动记录到可视化器
        self.visualizer.record_debate(deliberation)
        
        return deliberation
    
    def visualize_debate(self, output_path: str = None) -> str:
        """
        生成最新辩论的可视化报告
        
        Args:
            output_path: 输出文件路径（None表示返回HTML字符串）
            
        Returns:
            HTML字符串或保存路径
        """
        return self.visualizer.generate_html_report(output_path=output_path)
    
    def export_debate_json(self) -> str:
        """导出最新辩论记录为JSON"""
        return self.visualizer.export_to_json()
    
    def get_debate_history(self, n: int = 5) -> List[Dict]:
        """获取最近N次辩论记录摘要"""
        records = self.visualizer.get_recent_records(n)
        return [r.to_dict() for r in records]
