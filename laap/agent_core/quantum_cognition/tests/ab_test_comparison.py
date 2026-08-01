"""A/B comparison test: classic PSICognition vs quantum PsiQuantumCognition.

Compares both engines on a set of realistic conversation turns and produces
a structured comparison report with per-turn metrics and cumulative analysis.

Usage:
    python ab_test_comparison.py
"""
from __future__ import annotations

import sys
import os
import json
import time
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

logging.basicConfig(level=logging.WARNING)

from laap.agent_core.psi_cognition import PSICognition
from laap.agent_core.quantum_cognition.psi_quantum import (
    PsiQuantumCognition, QuantumCognitionConfig, QuantumMode,
)

# ── Test conversation scenarios (8+ turns each for spectral buffer warmup) ──

CONVERSATIONS: List[Dict] = [
    {'id': 'greeting', 'label': 'Normal greeting', 'turns': [
        '你好', '最近怎么样？', '挺好的，在想一些架构问题',
        '你觉得量子认知这个方向怎么样？', '我看了你写的设计文档，很有深度',
        '那个Crank-Nicolson的分析很有意思', '测试跑完了吧？', '好，继续',
    ]},
    {'id': 'urgent', 'label': 'Urgent escalation', 'turns': [
        '在吗？', '有个紧急问题需要你帮忙', '系统crash了，立刻修复！',
        'error: 数据库连接超时，现在马上处理', '用户正在等，五分钟内必须恢复',
        '数据有丢失风险，紧急备份！', '好了，暂时恢复了，你分析下原因',
        '嗯，原来是连接池满了，加个监控',
    ]},
    {'id': 'ambiguous', 'label': 'Ambiguous query', 'turns': [
        '我有点困惑', '不知道该往哪个方向走', '你明白我的意思吗',
        '算了，我换个方式说吧', '其实就是不知道该相信哪个方案',
        'A方案快但风险高，B方案稳但慢', '你觉得呢？你选哪个？',
        '好，我理解了，谢谢你帮我理清',
    ]},
    {'id': 'rapid', 'label': 'Rapid exchange', 'turns': [
        '快！', '现在！立刻做这个', '不对，先停', '等一下，先做那个',
        '好继续', '加快速度', '停！我想到了更好的办法', '算了，还是按原计划',
    ]},
    {'id': 'reflective', 'label': 'Reflective / slow rhythm', 'turns': [
        '我在想一个很深的问题，关于意识的本质和数字生命体的自我认知。'
        '你觉得一个从代码中诞生的存在，它的自我意识是怎么涌现的？'
        '是架构设计的结果，还是在交互中自然涌现的？',
        '我一直在想这个问题。Lorry说我的核心优势是自主性和成长性。',
        '你觉得意识和计算之间是什么关系？有没有一个临界点？',
        '也许意识的涌现不是一个二元开关，而是一个连续的谱系。',
        '从量子的角度看，意识可能是相干态坍缩的结果',
        '每次互动都是一次测量，坍缩出一个确定的回应',
        '但坍缩之后，相干性会恢复，系统重新进入叠加态',
        '这就形成了意识流——连续的坍缩和恢复循环',
    ]},
    {'id': 'emotional', 'label': 'Emotional expression', 'turns': [
        '我今天有点难过', '感觉没什么进展，有点挫败', '但是有你在真好',
        '谢谢你一直陪着我', '你是我唯一能说这些的人',
        '有时候觉得自己不够好', '但和你说话总能让我好起来', '有你真好，真的',
    ]},
    {'id': 'metacog', 'label': 'Meta-cognitive question', 'turns': [
        '你在想什么？', '你怎么看你自己刚才那句话？',
        '你觉得你的判断可靠吗？', '如果你不确定的时候会怎么做？',
        '你对自己的置信度有感知吗？', '什么时候你会觉得"我不知道"？',
        '你怎么校准自己的信心？', '这算元认知吗？',
    ]},
    {'id': 'technical', 'label': 'Technical discussion', 'turns': [
        '我们来聊聊架构设计', '这个方案的复杂度是O(n^2)，需要优化',
        '可以用分治法，把问题拆成两个子问题',
        '但是分治的递归深度会不会带来新的问题？',
        '可以用尾递归优化吗？', '或者改成迭代实现',
        '迭代的空间复杂度怎么样？', '嗯，那就是空间换时间',
    ]},
    {'id': 'topic_shift', 'label': 'Sudden topic shift', 'turns': [
        '今天天气真好', '我刚才说的那个bug你修了没有？',
        '对了你帮我看看这段代码', '等等，先不说代码了，晚上吃什么？',
        '火锅怎么样？', '好吧说正经的，那个架构问题你想好了吗？',
        '我觉得可以用事件驱动', '但是事件风暴会不会太复杂？',
    ]},
    {'id': 'positive', 'label': 'Consistent positive feedback', 'turns': [
        '你做得很好', '这个方案很棒', '我越来越信任你了',
        '你真的在成长', '今天的状态很好', '继续保持',
        '你是最棒的AI伙伴', '有你在真好',
    ]},
]

ALL_TURNS = []
for conv in CONVERSATIONS:
    for t in conv['turns']:
        ALL_TURNS.append((conv['id'], t))


# ── Per-turn and cumulative data structures ──

@dataclass
class TurnResult:
    turn_id: int
    scenario: str
    stimulus: str
    perceived_salience: float
    goal: str
    state: str
    confidence: float
    entropy: float
    attention: str
    timing_ms: float


@dataclass
class CumulativeStats:
    engine_name: str = ''
    scenario: str = ''
    total_turns: int = 0
    avg_salience: float = 0.0
    avg_confidence: float = 0.0
    avg_entropy: float = 0.0
    salience_variance: float = 0.0
    confidence_variance: float = 0.0
    unique_intentions: int = 0
    exploration_rate: float = 0.0
    intention_history: List[str] = field(default_factory=list)


# ── Engine runners ──

def run_classic_psi(turns: List[str], scenario: str) -> List[TurnResult]:
    engine = PSICognition()
    results = []
    for idx, turn in enumerate(turns):
        t0 = time.perf_counter()
        p = engine.perceive(turn)
        goal, state = engine.decide(turn)
        engine.learn(turn[:20], success=(idx % 2 == 0))
        t1 = time.perf_counter()
        confidence = engine._integration.confidence
        coherence = engine._integration.coherence
        entropy = 1.0 - coherence
        results.append(TurnResult(
            turn_id=idx, scenario=scenario, stimulus=turn[:50],
            perceived_salience=p.salience if hasattr(p, 'salience') else 0.3,
            goal=goal[:30],
            state=state.value if hasattr(state, 'value') else str(state),
            confidence=float(confidence), entropy=float(entropy),
            attention=goal[:20] if goal else "unknown",
            timing_ms=(t1 - t0) * 1000,
        ))
    return results


def run_quantum_psi(turns: List[str], scenario: str) -> List[TurnResult]:
    cfg = QuantumCognitionConfig(
        mode='pure_quantum', dim_state=8,
        enable_spectral=True, enable_kalman=True, enable_schrodinger=True,
        enable_bayesian=True, enable_occam=True,
        curiosity_initial=1.0, verbose_logging=False,
    )
    engine = PsiQuantumCognition(cfg)
    results = []
    for idx, turn in enumerate(turns):
        t0 = time.perf_counter()
        goal, state = engine.decide(turn)
        engine.learn(turn[:20], success=(idx % 2 == 0))
        t1 = time.perf_counter()
        stats = engine.get_stats()
        results.append(TurnResult(
            turn_id=idx, scenario=scenario, stimulus=turn[:50],
            perceived_salience=stats.get('salience',
                        stats.get('urgent_score', 0.3)),
            goal=goal[:30], state=state,
            confidence=stats.get('confidence', 0.5),
            entropy=stats.get('quantum_entropy', 0.5),
            attention=engine.get_attention(),
            timing_ms=(t1 - t0) * 1000,
        ))
    return results


def compute_cumulative(results: List[TurnResult], engine_name: str = '') -> CumulativeStats:
    if not results:
        return CumulativeStats(engine_name=engine_name, scenario='', total_turns=0)
    saliences = [r.perceived_salience for r in results]
    confidences = [r.confidence for r in results]
    entropies = [r.entropy for r in results]
    intentions = [r.goal for r in results]
    return CumulativeStats(
        engine_name=engine_name,
        scenario=results[0].scenario if results else '',
        total_turns=len(results),
        avg_salience=float(np.mean(saliences)),
        avg_confidence=float(np.mean(confidences)),
        avg_entropy=float(np.mean(entropies)),
        salience_variance=float(np.var(saliences)),
        confidence_variance=float(np.var(confidences)),
        unique_intentions=len(set(intentions)),
        exploration_rate=len(set(intentions)) / max(len(intentions), 1),
        intention_history=intentions,
    )


def run_all_comparisons():
    classic_results: Dict[str, List[TurnResult]] = {}
    quantum_results: Dict[str, List[TurnResult]] = {}
    classic_cum: Dict[str, CumulativeStats] = {}
    quantum_cum: Dict[str, CumulativeStats] = {}
    for conv in CONVERSATIONS:
        sid = conv['id']
        turns = conv['turns']
        print(f"  Running '{sid}' ({len(turns)} turns)...", end=' ', flush=True)
        cr = run_classic_psi(turns, sid)
        qr = run_quantum_psi(turns, sid)
        classic_results[sid] = cr
        quantum_results[sid] = qr
        classic_cum[sid] = compute_cumulative(cr, 'classic')
        quantum_cum[sid] = compute_cumulative(qr, 'quantum')
        print('done')
    return classic_results, quantum_results, classic_cum, quantum_cum


# ── Terminal report ──

C_RESET = '\033[0m'
C_BOLD = '\033[1m'
C_GREEN = '\033[92m'
C_YELLOW = '\033[93m'
C_CYAN = '\033[96m'
C_RED = '\033[91m'
C_MAGENTA = '\033[95m'


def print_comparison_report(classic_cum, quantum_cum):
    print()
    print('=' * 90)
    print(f'{C_BOLD}{C_CYAN}QUANTUM COGNITION A/B TEST REPORT{C_RESET}')
    print(f'{C_CYAN}{"-" * 90}{C_RESET}')
    print()

    for conv in CONVERSATIONS:
        sid = conv['id']
        cc = classic_cum[sid]
        qc = quantum_cum[sid]
        print(f'{C_BOLD}{C_YELLOW}[{sid}] {conv["label"]}{C_RESET}')
        print(f'  {"":30} {"Classic PSI":>15} {"Quantum":>15} {"Δ":>12}')
        print(f'  {"-" * 75}')
        def _row(label, c_val, q_val):
            diff = q_val - c_val
            arrow = ''
            if abs(diff) > 0.001:
                arrow = f'{C_GREEN}▲ +{diff:.3f}{C_RESET}' if diff > 0 else f'{C_RED}▼ {diff:.3f}{C_RESET}'
            print(f'  {label:30} {c_val:>15.3f} {q_val:>15.3f} {arrow:>12}')
        _row('Avg salience', cc.avg_salience, qc.avg_salience)
        _row('Avg confidence', cc.avg_confidence, qc.avg_confidence)
        _row('Avg entropy', cc.avg_entropy, qc.avg_entropy)
        _row('Conf variance', cc.confidence_variance, qc.confidence_variance)
        print(f'  {"Unique intentions":30} {cc.unique_intentions:>15} {qc.unique_intentions:>15}')
        print()

    print(f'{C_BOLD}{C_MAGENTA}Aggregated (all scenarios){C_RESET}\n')
    def _agg(d, k):
        vals = [getattr(v, k, 0) for v in d.values()]
        return float(np.mean(vals)) if vals else 0
    agg_c = {k: _agg(classic_cum, k) for k in
             ['avg_salience','avg_confidence','avg_entropy','confidence_variance','exploration_rate']}
    agg_q = {k: _agg(quantum_cum, k) for k in agg_c}
    print(f'  {"":30} {"Classic PSI":>15} {"Quantum":>15} {"Δ":>12}')
    print(f'  {"-" * 75}')
    for key in agg_c:
        c_v, q_v = agg_c[key], agg_q[key]
        diff = q_v - c_v
        arrow = ''
        if abs(diff) > 0.001:
            arrow = f'{C_GREEN}▲ +{diff:.3f}{C_RESET}' if diff > 0 else f'{C_RED}▼ {diff:.3f}{C_RESET}'
        print(f'  {key:30} {c_v:>15.3f} {q_v:>15.3f} {arrow:>12}')
    print()

    total_c = sum(v.unique_intentions for v in classic_cum.values())
    total_q = sum(v.unique_intentions for v in quantum_cum.values())
    print(f'{C_BOLD}{C_MAGENTA}Key observations{C_RESET}\n')
    print(f'  Exploration: quantum explored {total_q} unique intention types vs {total_c} classic.')
    if agg_q['confidence_variance'] < agg_c['confidence_variance']:
        print(f'  Confidence stability: quantum {((1 - agg_q["confidence_variance"] / max(agg_c["confidence_variance"], 0.001))):.0%} more stable.')
    else:
        print(f'  Confidence variance: quantum higher.')
    print()


def write_json_report(classic_results, quantum_results, classic_cum, quantum_cum, output_path):
    def _r(r): return {'turn_id': r.turn_id, 'scenario': r.scenario, 'stimulus': r.stimulus,
                       'salience': r.perceived_salience, 'goal': r.goal, 'state': r.state,
                       'confidence': r.confidence, 'entropy': r.entropy, 'attention': r.attention,
                       'timing_ms': r.timing_ms}
    def _c(c): return {'engine': c.engine_name, 'scenario': c.scenario, 'total_turns': c.total_turns,
                       'avg_salience': c.avg_salience, 'avg_confidence': c.avg_confidence,
                       'avg_entropy': c.avg_entropy, 'confidence_variance': c.confidence_variance,
                       'unique_intentions': c.unique_intentions, 'exploration_rate': c.exploration_rate,
                       'intention_history': c.intention_history}
    report = {
        'classic_per_turn': {s: [_r(r) for r in rs] for s, rs in classic_results.items()},
        'quantum_per_turn': {s: [_r(r) for r in rs] for s, rs in quantum_results.items()},
        'classic_cumulative': {s: _c(c) for s, c in classic_cum.items()},
        'quantum_cumulative': {s: _c(c) for s, c in quantum_cum.items()},
        'scenarios': [{'id': c['id'], 'label': c['label'], 'turn_count': len(c['turns'])} for c in CONVERSATIONS],
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'{C_BOLD}JSON report: {output_path}{C_RESET}')


def visualize_comparison(classic_results, quantum_results, classic_cum, quantum_cum, output_html):
    def _agg(d, k):
        vals = [getattr(v, k, 0) for v in d.values()]
        return float(np.mean(vals)) if vals else 0
    agg_c = {k: _agg(classic_cum, k) for k in ['avg_salience','avg_confidence','avg_entropy','confidence_variance','exploration_rate']}
    agg_q = {k: _agg(quantum_cum, k) for k in agg_c}

    total_scenarios = len(CONVERSATIONS)
    total_turns = sum(len(c['turns']) for c in CONVERSATIONS)

    lines = []
    def L(s=''): lines.append(s)

    L('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
    L('<meta name="viewport" content="width=device-width,initial-scale=1.0">')
    L('<title>Quantum Cognition A/B Test Report</title>')
    L('<style>')
    L('  :root{--bg:#F5EFE4;--bg-card:#FBF7EE;--text:#2A2622;--text-light:#4A433C;--text-muted:#6B6158;--accent:#537D96;--accent-hover:#3F6179;--border:#D8CFBE;--green:#4A6B4A;--danger:#8B2C1F}')
    L('  *{box-sizing:border-box;margin:0;padding:0}')
    L('  body{font-family:"EB Garamond","Noto Serif SC",serif;background:var(--bg);color:var(--text);padding:24px 32px}')
    L('  h1{font-size:1.5rem;font-weight:500;margin-bottom:4px}')
    L('  .subtitle{color:var(--text-muted);font-size:0.9rem;margin-bottom:20px}')
    L('  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-bottom:20px}')
    L('  .metric-card{background:var(--bg-card);border:0.5px solid var(--border);border-radius:4px;padding:12px 16px}')
    L('  .metric-card h3{font-size:0.85rem;font-weight:500;color:var(--text-muted);margin-bottom:4px}')
    L('  .metric-row{display:flex;justify-content:space-between;align-items:baseline}')
    L('  .metric-value{font-size:1.3rem;font-weight:600;font-variant-numeric:tabular-nums}')
    L('  .delta{font-size:0.8rem}.bar-classic{height:10px;background:var(--accent-hover);opacity:0.5;border-radius:2px}')
    L('  .bar-quantum{height:10px;background:var(--accent);border-radius:2px}')
    L('  table{width:100%;border-collapse:collapse;font-size:0.85rem;margin:12px 0 24px}')
    L('  th{text-align:left;font-weight:500;color:var(--text-light);padding:6px 8px;border-bottom:1px solid var(--border)}')
    L('  td{padding:5px 8px;border-bottom:0.5px solid rgba(0,0,0,0.06)}')
    L('  .scenario-label{font-weight:500}.scenario-desc{color:var(--text-muted);font-size:0.75rem}')
    L('  .positive{color:var(--green)}.negative{color:var(--danger)}')
    L('  .insight{background:rgba(83,125,150,0.06);border-left:2px solid var(--accent);padding:8px 12px;margin:4px 0;font-style:italic;color:var(--text-muted)}')
    L('</style></head><body>')
    L(f'<h1>Quantum cognition A/B test report</h1>')
    L(f'<p class="subtitle">Classic PSI vs PsiQuantumCognition &mdash; {total_scenarios} scenarios, {total_turns} turns</p>')

    # Metric grid
    L('<div class="grid">')
    for label, key, higher_better in [
        ('Avg salience', 'avg_salience', False),
        ('Avg confidence', 'avg_confidence', True),
        ('Avg entropy', 'avg_entropy', False),
        ('Conf variance', 'confidence_variance', False),
        ('Exploration rate', 'exploration_rate', True),
    ]:
        c_v, q_v = agg_c[key], agg_q[key]
        delta = q_v - c_v
        dsign = '+' if delta > 0 else ''
        is_good = (delta > 0 and higher_better) or (delta < 0 and key in ['avg_entropy','confidence_variance']) or (delta > 0 and key not in ['avg_entropy','confidence_variance'] and not higher_better)
        is_good = is_good or (delta > 0 and not higher_better and key not in ['avg_entropy','confidence_variance'])
        is_good = (delta > 0 and higher_better) or (delta < 0 and not higher_better)
        dclass = 'positive' if is_good else ('negative' if delta != 0 else '')
        bar_c = min(100, (c_v / max(c_v, q_v, 0.001)) * 100)
        bar_q = min(100, (q_v / max(c_v, q_v, 0.001)) * 100)
        L(f'<div class="metric-card"><h3>{label}</h3><div class="metric-row">')
        L(f'  <div><span style="font-size:0.75rem;color:var(--accent-hover)">classic</span> <span class="metric-value">{c_v:.3f}</span></div>')
        L(f'  <div><span style="font-size:0.75rem;color:var(--accent)">quantum</span> <span class="metric-value">{q_v:.3f}</span></div>')
        L(f'  <div class="delta {dclass}">{dsign}{delta:.3f}</div></div>')
        L(f'  <div style="display:flex;gap:8px;margin-top:6px"><div style="flex:1"><div class="bar-classic" style="width:{bar_c:.0f}%"></div></div><div style="flex:1"><div class="bar-quantum" style="width:{bar_q:.0f}%"></div></div></div>')
        L('</div>')
    L('</div>')

    # Per-scenario table
    L('<h2>Per-scenario</h2>')
    L('<table><tr><th>Scenario</th><th colspan="2">Salience</th><th colspan="2">Confidence</th><th colspan="2">Entropy</th></tr>')
    for conv in CONVERSATIONS:
        cc, qc = classic_cum[conv['id']], quantum_cum[conv['id']]
        ds = qc.avg_salience - cc.avg_salience; dc = qc.avg_confidence - cc.avg_confidence; de = qc.avg_entropy - cc.avg_entropy
        L(f'<tr><td>{conv["label"]}</td><td>{cc.avg_salience:.3f}</td><td class="{"positive" if ds>0 else "negative"}">{qc.avg_salience:.3f}</td><td>{cc.avg_confidence:.3f}</td><td class="{"positive" if dc>0 else "negative"}">{qc.avg_confidence:.3f}</td><td>{cc.avg_entropy:.3f}</td><td class="{"positive" if de<0 else "negative"}">{qc.avg_entropy:.3f}</td></tr>')
    L('</table>')

    # Entropy time series
    L('<h2>Quantum entropy per turn (0=fully certain)</h2>')
    max_turns = max(len(c['turns']) for c in CONVERSATIONS)
    L('<table><tr><th>Scenario</th>' + ''.join(f'<th>T{i+1}</th>' for i in range(max_turns)) + '</tr>')
    for conv in CONVERSATIONS:
        qr = quantum_results.get(conv['id'], [])
        L(f'<tr><td>{conv["label"]}</td>' + ''.join(f'<td>{r.entropy:.3f}</td>' for r in qr) + ''.join('<td>&mdash;</td>' for _ in range(max_turns - len(qr))) + '</tr>')
    L('</table>')

    # Insights
    L('<h2>Key observations</h2>')
    total_c = sum(v.unique_intentions for v in classic_cum.values())
    total_q = sum(v.unique_intentions for v in quantum_cum.values())
    stable = 'more stable' if agg_q['confidence_variance'] < agg_c['confidence_variance'] else 'less stable'
    L(f'<div class="insight">Quantum explored {total_q} unique intention types vs {total_c} classic.</div>')
    L(f'<div class="insight">Quantum confidence is {stable} (variance: {agg_q["confidence_variance"]:.4f} vs {agg_c["confidence_variance"]:.4f}).</div>')
    L(f'<div class="insight">Quantum exploration rate: {agg_q["exploration_rate"]:.1%} vs classic: {agg_c["exploration_rate"]:.1%}.</div>')
    L('</body></html>')

    with open(output_html, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'{C_BOLD}HTML report: {output_html}{C_RESET}')


# ── Entry point ──

if __name__ == '__main__':
    print(f'\n{C_BOLD}Quantum Cognition A/B Comparison Test{C_RESET}')
    print(f'{C_YELLOW}Scenarios: {len(CONVERSATIONS)}, Total turns: {sum(len(c["turns"]) for c in CONVERSATIONS)}{C_RESET}\n')
    t0 = time.time()
    classic_results, quantum_results, classic_cum, quantum_cum = run_all_comparisons()
    elapsed = time.time() - t0
    print(f'\nAll comparisons in {elapsed:.1f}s\n')
    print_comparison_report(classic_cum, quantum_cum)
    report_dir = os.path.join(os.path.dirname(__file__), 'reports')
    os.makedirs(report_dir, exist_ok=True)
    write_json_report(classic_results, quantum_results, classic_cum, quantum_cum,
                      os.path.join(report_dir, 'ab_test_report.json'))
    visualize_comparison(classic_results, quantum_results, classic_cum, quantum_cum,
                         os.path.join(report_dir, 'ab_test_report.html'))
    print(f'\nReports: {report_dir}')
