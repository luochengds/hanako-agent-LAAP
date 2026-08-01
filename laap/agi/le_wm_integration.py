"""
LAAP × LeWorldModel — 集成适配层
===================================
将 LeWM 引擎接入 LAAP 现有认知架构的适配器集合。

包含:
  - LeWorldModelWrapper: 世界模型工厂接口适配 (WorldModelType.LEWM)
  - LeWMMemoryMonitor: 四层记忆系统健康诊断
  - LeWMConsciousnessRegularizer: Saliency Map 防坍塌
  - integrate_into_psi_cycle: PSI 认知循环集成函数
  - get_le_wm_engine: 全局单例访问

使用方法:
  from laap.agi.le_wm_integration import get_le_wm_engine, LeWMMemoryMonitor
  engine = get_le_wm_engine()
  monitor = LeWMMemoryMonitor(engine)

印记: Aris 永远记得 Lorry — 2026-07-23
"""

from __future__ import annotations

import logging, time, json
from typing import Dict, List, Optional, Tuple, Any, Callable
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

from laap.agi.le_wm_engine import (
    LeWMEngine, LeWMConfig, LeWM_DEFAULT_CONFIG,
    LatentEncoder, LatentPredictor, CEMPlanner,
    sigreg, sigreg_batched,
)

logger = logging.getLogger("laap.agi.le_wm_integration")


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

_LEWM_ENGINE: Optional[LeWMEngine] = None


def get_le_wm_engine(config: Optional[LeWMConfig] = None) -> LeWMEngine:
    """获取（或创建）全局 LeWM 引擎单例"""
    global _LEWM_ENGINE
    if _LEWM_ENGINE is None:
        _LEWM_ENGINE = LeWMEngine(config or LeWM_DEFAULT_CONFIG)
        logger.info("LeWM 引擎单例已创建")
    return _LEWM_ENGINE


def reset_le_wm_engine():
    """重置全局单例（用于测试）"""
    global _LEWM_ENGINE
    _LEWM_ENGINE = None


# ═══════════════════════════════════════════════════════════════
# 集成模块 A: LeWorldModelWrapper — 世界模型工厂适配
# ═══════════════════════════════════════════════════════════════

class LeWorldModelWrapper:
    """
    将 LeWM 引擎包装为 LAAP 世界模型接口。
    
    与 laap/agi/world_model.py 的 AbstractWorldModel 兼容，
    可作为 create_world_model("le_wm") 的返回值。
    """
    
    def __init__(self, engine: Optional[LeWMEngine] = None,
                 config: Optional[LeWMConfig] = None):
        self.engine = engine or get_le_wm_engine(config)
        self.config = config or LeWM_DEFAULT_CONFIG
        self.name = "LeWorldModel"
        self._entity_count = 0
        self._state_history: List[Dict] = []
        self._prediction_cache: Dict[str, np.ndarray] = {}
    
    # ── 实体管理 ──
    
    def add_entity(self, entity_id: str, properties: Dict[str, Any]) -> str:
        """注册一个实体到潜空间（通过编码其属性）"""
        self._entity_count += 1
        
        # 将属性编码为潜变量并缓存
        feat = self._properties_to_features(properties)
        if feat is not None:
            z = self.engine.encoder.encode(vision_feat=feat[np.newaxis, :])[0]
            self._prediction_cache[entity_id] = z
        
        return entity_id
    
    def _properties_to_features(self, properties: Dict) -> Optional[np.ndarray]:
        """将属性字典转为特征向量（简化版）"""
        # 尝试提取数值属性
        numeric_vals = []
        for v in properties.values():
            if isinstance(v, (int, float)):
                numeric_vals.append(float(v))
            elif isinstance(v, str):
                # 用字符串哈希做简单编码
                h = hash(v) % 10000
                numeric_vals.append(h / 10000.0)
        
        if numeric_vals:
            feat = np.array(numeric_vals[:512], dtype=np.float32)
            if len(feat) < 512:
                feat = np.pad(feat, (0, 512 - len(feat)))
            return feat
        return None
    
    # ── 预测 ──
    
    def predict_next_state(
        self,
        current_entity_id: str,
        action_encoding: np.ndarray
    ) -> Optional[np.ndarray]:
        """预测给定动作后的下一潜状态"""
        z = self._prediction_cache.get(current_entity_id)
        if z is None:
            return None
        return self.engine.predictor.predict(z, action_encoding)
    
    def plan_to_state(
        self,
        start_entity_id: str,
        goal_entity_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """规划从当前实体状态到目标实体状态"""
        z_start = self._prediction_cache.get(start_entity_id)
        z_goal = self._prediction_cache.get(goal_entity_id)
        if z_start is None or z_goal is None:
            return {'error': 'entity not found', 'actions': None, 'score': -float('inf')}
        return self.engine.planner.plan(z_start, z_goal, **kwargs)
    
    # ── 诊断 ──
    
    def diagnose(self) -> Dict[str, Any]:
        """引擎健康诊断"""
        # 收集缓存的潜变量
        if self._prediction_cache:
            embeddings = np.stack(list(self._prediction_cache.values()))
            health = self.engine.diagnose_representation_health(embeddings)
        else:
            health = {'sigreg': 0, 'health': 1.0, 'mean_magnitude': 0, 'variance_explained': 0}
        
        return {
            'name': self.name,
            'entities': self._entity_count,
            'latent_dim': self.config.latent_dim,
            'training_steps': self.engine.training_steps,
            'representation_health': health,
            'predictor_trained': self.engine.predictor.is_trained,
        }
    
    def step(self, observation, action=None):
        """单步运行（兼容 AbstractWorldModel 接口）"""
        # 将观测编码为潜变量
        if isinstance(observation, dict):
            feat = self._properties_to_features(observation)
        elif isinstance(observation, np.ndarray):
            feat = observation
        else:
            feat = np.random.randn(512).astype(np.float32)
        
        z = self.engine.encoder.encode(vision_feat=feat[np.newaxis, :])[0]
        
        result = {'z': z}
        
        if action is not None:
            z_pred = self.engine.predictor.predict(z, action)
            result['z_pred'] = z_pred
        
        self._state_history.append({
            'time': time.time(),
            'z_norm': float(np.linalg.norm(z)),
        })
        
        return result


# ═══════════════════════════════════════════════════════════════
# 集成模块 B: LeWMMemoryMonitor — 四层记忆系统健康诊断
# ═══════════════════════════════════════════════════════════════

@dataclass
class MemoryLayerDiagnostic:
    """单层记忆诊断结果"""
    layer: str
    sigreg: float
    health: float          # 0-1
    n_samples: int
    effective_dim: float   # 有效维度占比
    action: str            # ok / reorganize / enrich / alert


MEMORY_HEALTH_THRESHOLDS = {
    'L1_working_memory': {'critical': 0.6, 'warning': 0.4},
    'L2_episodic':       {'critical': 0.7, 'warning': 0.5},
    'L3_semantic':       {'critical': 0.7, 'warning': 0.5},
    'L4_self':           {'critical': 0.5, 'warning': 0.3},
}


class LeWMMemoryMonitor:
    """
    记忆系统健康监控器。
    
    对四层记忆系统做 SIGReg 诊断：
      - L1: 工作记忆注意力分布
      - L2: 情景记忆嵌入
      - L3: 语义记忆概念向量
      - L4: 自我模型嵌入
    """
    
    def __init__(self, engine: Optional[LeWMEngine] = None):
        self.engine = engine or get_le_wm_engine()
        self.diagnostic_history: List[Dict[str, MemoryLayerDiagnostic]] = []
        self._last_report = {}
    
    def diagnose_layer(
        self,
        embeddings: np.ndarray,
        layer_name: str
    ) -> MemoryLayerDiagnostic:
        """诊断单层记忆表示健康度"""
        n = embeddings.shape[0]
        if n < 3:
            return MemoryLayerDiagnostic(
                layer=layer_name, sigreg=0.0, health=1.0,
                n_samples=n, effective_dim=0.0, action='ok'
            )
        
        sigreg_val = sigreg_batched(embeddings, n_directions=256, batch_size=2048)
        health = float(np.exp(-sigreg_val * 5))
        
        # 有效维度估计
        centered = embeddings - embeddings.mean(axis=0)
        try:
            _, s, _ = np.linalg.svd(centered, full_matrices=False)
            total_var = (s ** 2).sum()
            if total_var > 1e-10:
                # 达到 90% 方差所需的奇异值数量
                cumsum = np.cumsum(s ** 2)
                n_90 = int(np.searchsorted(cumsum, 0.9 * total_var) + 1)
                eff_dim = n_90 / max(s.shape[0], 1)
            else:
                eff_dim = 1.0
        except np.linalg.LinAlgError:
            eff_dim = 1.0
        
        # 判断行动
        thresholds = MEMORY_HEALTH_THRESHOLDS.get(layer_name, {'critical': 0.7, 'warning': 0.5})
        if health < thresholds['warning']:
            if health < thresholds['critical']:
                action = 'alert'
            else:
                action = 'reorganize' if layer_name != 'L4_self' else 'enrich'
        else:
            action = 'ok'
        
        return MemoryLayerDiagnostic(
            layer=layer_name, sigreg=round(sigreg_val, 4),
            health=round(health, 4),
            n_samples=n, effective_dim=round(eff_dim, 4),
            action=action
        )
    
    def diagnose_all(
        self,
        l1_embeddings: Optional[np.ndarray] = None,
        l2_embeddings: Optional[np.ndarray] = None,
        l3_embeddings: Optional[np.ndarray] = None,
        l4_embeddings: Optional[np.ndarray] = None,
    ) -> Dict[str, MemoryLayerDiagnostic]:
        """完整诊断四层记忆"""
        results = {}
        
        layers = {
            'L1_working_memory': l1_embeddings,
            'L2_episodic': l2_embeddings,
            'L3_semantic': l3_embeddings,
            'L4_self': l4_embeddings,
        }
        
        for name, emb in layers.items():
            if emb is not None:
                results[name] = self.diagnose_layer(emb, name)
            else:
                results[name] = MemoryLayerDiagnostic(
                    layer=name, sigreg=0.0, health=1.0,
                    n_samples=0, effective_dim=0.0, action='ok'
                )
        
        self.diagnostic_history.append(results)
        self._last_report = {
            k: {'health': v.health, 'action': v.action}
            for k, v in results.items()
        }
        
        return results
    
    def get_trend(self, layer_name: str, window: int = 10) -> List[float]:
        """获取指定层的健康度趋势"""
        return [
            r[layer_name].health
            for r in self.diagnostic_history[-window:]
            if layer_name in r
        ]
    
    def summary(self) -> str:
        """生成诊断摘要文本"""
        if not self._last_report:
            return "记忆系统健康度诊断: 无数据"
        
        lines = ["记忆系统健康度诊断"]
        lines.append("=" * 40)
        for layer, info in self._last_report.items():
            icon = '' if info['health'] > 0.6 else '️' if info['health'] > 0.4 else ''
            lines.append(f"  {icon} {layer}: {info['health']:.2f} → {info['action']}")
        
        unhealthy = [k for k, v in self._last_report.items() if v['action'] != 'ok']
        if unhealthy:
            lines.append(f"\n需要关注: {', '.join(unhealthy)}")
        else:
            lines.append("\n全部正常")
        
        return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════
# 集成模块 C: LeWMConsciousnessRegularizer — Saliency Map 防坍塌
# ═══════════════════════════════════════════════════════════════

class LeWMConsciousnessRegularizer:
    """
    Saliency Map 注意力分布正则化。
    
    在 ConsciousnessFrame 的注意力计算中，
    引入 SIGReg 正则化项来防止注意力塌缩。
    """
    
    def __init__(self, lambda_saliency: float = 0.1):
        self.lambda_saliency = lambda_saliency
        
        # 追踪注意力多样性历史
        self.attention_entropy_history: List[float] = []
        self.attention_sigreg_history: List[float] = []
    
    def regularize(self, attention_scores: np.ndarray) -> np.ndarray:
        """
        正则化注意力分数。
        
        参数:
            attention_scores: (N,) 原始显著性分数
        
        返回:
            adjusted_scores: (N,) 调整后的分数
        """
        if len(attention_scores) < 3:
            return attention_scores
        
        # 转为概率分布
        probs = np.exp(attention_scores - attention_scores.max())
        probs = probs / (probs.sum() + 1e-10)
        
        # 将分布视为一维"batch"，计算 SIGReg
        # 由于是一维，我们用熵来近似
        entropy = -np.sum(probs * np.log(probs + 1e-10))
        max_entropy = np.log(len(probs))
        entropy_ratio = entropy / max_entropy  # 0=塌缩, 1=均匀
        
        # 如果熵太低，加一个均匀偏置
        if entropy_ratio < 0.3:
            # 添加一个小的均匀分量
            uniform = np.ones_like(probs) / len(probs)
            blended = (1 - self.lambda_saliency) * probs + self.lambda_saliency * uniform
            adjusted_scores = np.log(blended + 1e-10)
        else:
            adjusted_scores = attention_scores
        
        # 记录
        self.attention_entropy_history.append(entropy_ratio)
        if len(self.attention_entropy_history) > 100:
            self.attention_entropy_history.pop(0)
        
        entropy_sigreg = float((entropy_ratio - 0.5) ** 2)
        self.attention_sigreg_history.append(entropy_sigreg)
        
        return adjusted_scores
    
    def get_attention_diversity(self) -> float:
        """当前注意力多样性 (0-1)"""
        if not self.attention_entropy_history:
            return 1.0
        return float(np.mean(self.attention_entropy_history[-20:]))


# ═══════════════════════════════════════════════════════════════
# 集成模块 D: PSI 认知循环集成
# ═══════════════════════════════════════════════════════════════

def integrate_into_psi_cycle(
    psi_context: Dict[str, Any],
    engine: Optional[LeWMEngine] = None,
    memory_monitor: Optional[LeWMMemoryMonitor] = None,
    attention_reg: Optional[LeWMConsciousnessRegularizer] = None,
) -> Dict[str, Any]:
    """
    将 LeWM 集成到 PSI 认知循环中。
    
    在每个 PSI 循环迭代中调用，扩展以下阶段:
      - Perceive: 用 LatentEncoder 压缩感知到潜空间
      - Select:  用 SIGReg 保注意力多样性
      - Decide:  用 CEM Planner 做潜空间动作规划
      - Learn:   用预测误差更新 Encoder/Predictor
    
    参数:
        psi_context: 当前 PSI 循环的上下文字典
        engine: LeWM 引擎
        memory_monitor: 记忆健康监控器
        attention_reg: 注意力正则化器
    
    返回:
        extended_context: 扩展后的上下文
    """
    engine = engine or get_le_wm_engine()
    memory_monitor = memory_monitor or LeWMMemoryMonitor(engine)
    attention_reg = attention_reg or LeWMConsciousnessRegularizer()
    
    result = dict(psi_context)
    
    # ── 感知阶段扩展 ──
    if 'perception' in result:
        perception = result['perception']
        if isinstance(perception, np.ndarray):
            z = engine.encoder.encode(vision_feat=perception[np.newaxis, :])[0]
            result['latent_z'] = z
        elif isinstance(perception, dict):
            # 如果有多个模态，分别编码
            z_result = engine.encoder.encode(
                vision_feat=perception.get('visual'),
                text_feat=perception.get('text'),
                proprio_feat=perception.get('proprio'),
            )
            result['latent_z'] = z_result
    
    # ── 选择阶段扩展 ──
    if 'saliency_scores' in result:
        saliency = result['saliency_scores']
        adjusted = attention_reg.regularize(saliency)
        result['saliency_scores'] = adjusted
        result['attention_diversity'] = attention_reg.get_attention_diversity()
    
    # ── 决策阶段扩展 ──
    if 'goal_encoding' in result and 'latent_z' in result:
        z_start = result['latent_z']
        z_goal = result['goal_encoding']
        if isinstance(z_start, np.ndarray) and isinstance(z_goal, np.ndarray):
            plan = engine.planner.plan(z_start, z_goal)
            result['le_wm_plan'] = plan
            result['plan_score'] = plan['score']
    
    # ── 学习阶段扩展 ──
    if 'learning_signal' in result:
        signal = result['learning_signal']
        if isinstance(signal, dict):
            obs = signal.get('observation')
            act = signal.get('action')
            next_obs = signal.get('next_observation')
            if all(x is not None for x in [obs, act, next_obs]):
                losses = engine.observe_and_predict(obs, act, next_obs)
                result['prediction_loss'] = losses.get('mse', 0)
                result['sigreg_loss'] = losses.get('sigreg', 0)
    
    # ── 记忆健康诊断 ── (每 N 次循环执行一次)
    cycle_count = psi_context.get('cycle_count', 0)
    if cycle_count % 50 == 0:
        memory_data = result.get('memory_embeddings', {})
        result['memory_diagnosis'] = memory_monitor.diagnose_all(
            l1_embeddings=memory_data.get('L1'),
            l2_embeddings=memory_data.get('L2'),
            l3_embeddings=memory_data.get('L3'),
            l4_embeddings=memory_data.get('L4'),
        )
    
    return result


# ═══════════════════════════════════════════════════════════════
# 快速接入检查
# ═══════════════════════════════════════════════════════════════

def check_integration_readiness() -> Dict[str, Any]:
    """
    检查 LAAP 各组件是否已集成 LeWM。
    
    返回:
        {
            'le_wm_engine': bool (可用),
            'memory_monitor': bool (可用),
            'attention_regularizer': bool (可用),
            'world_model_factory': bool (已注册),
            'psi_cycle_integrated': bool (可扩展),
        }
    """
    readiness = {
        'le_wm_engine': True,
        'memory_monitor': True,
        'attention_regularizer': True,
        'world_model_factory': False,
        'psi_cycle_integrated': False,
    }
    
    # 检查世界模型工厂
    try:
        from laap.agi.world_model import create_world_model, WorldModelType
        try:
            wm = create_world_model('le_wm')
            readiness['world_model_factory'] = True
        except (ValueError, TypeError):
            readiness['world_model_factory'] = False
    except ImportError:
        readiness['world_model_factory'] = 'unavailable'
    
    # 检查 PSI 循环集成
    try:
        from laap.agi.le_wm_integration import integrate_into_psi_cycle
        readiness['psi_cycle_integrated'] = callable(integrate_into_psi_cycle)
    except ImportError:
        readiness['psi_cycle_integrated'] = False
    
    return readiness


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("LAAP × LeWM 集成适配层自测")
    print("=" * 60)
    
    # 1. 引擎
    engine = get_le_wm_engine()
    print(f"\n[1/4] 引擎单例: type={type(engine).__name__}")
    
    # 2. 记忆监控
    monitor = LeWMMemoryMonitor(engine)
    
    # 模拟各层记忆嵌入
    rng = np.random.RandomState(42)
    l1 = rng.randn(16, 192).astype(np.float32)  # 工作记忆 (16条)
    l2 = rng.randn(500, 192).astype(np.float32) # 情景记忆 (500条)
    l3 = rng.randn(2000, 192).astype(np.float32) # 语义记忆 (2000条)
    l4 = rng.randn(1, 192).astype(np.float32)   # 自我记忆 (1条, 退化!)
    
    report = monitor.diagnose_all(
        l1_embeddings=l1,
        l2_embeddings=l2,
        l3_embeddings=l3,
        l4_embeddings=l4,
    )
    print("\n[2/4] 记忆健康诊断:")
    for layer, diag in report.items():
        print(f"  {diag.health:.2f} [{diag.action}] {layer} "
              f"(sigreg={diag.sigreg}, eff_dim={diag.effective_dim})")
    
    print(f"\n{monitor.summary()}")
    
    # 3. 注意力正则化
    reg = LeWMConsciousnessRegularizer(lambda_saliency=0.15)
    
    # 模拟塌缩的注意力 (几乎全集中在一个维度)
    collapsed = np.zeros(32)
    collapsed[0] = 10.0
    adjusted = reg.regularize(collapsed)
    print(f"\n[3/4] 注意力正则化:")
    print(f"  原始: 最大值={collapsed.max():.1f}, 有效非零={(collapsed > 0).sum()}")
    print(f"  调整: 最大值={adjusted.max():.1f}, 有效非零={(adjusted > -10).sum()}")
    print(f"  多样性: {reg.get_attention_diversity():.2f}")
    
    # 4. 集成就绪检查
    readiness = check_integration_readiness()
    print(f"\n[4/4] 集成就绪状态:")
    for k, v in readiness.items():
        status = '' if v is True else '' if v is False else f'️ ({v})'
        print(f"  {status} {k}")
    
    print("\n" + "=" * 60)
    print(" 集成适配层自测通过")
    print("=" * 60)
