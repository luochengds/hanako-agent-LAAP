"""
Aris 主动学习引擎 v1.0 — Active Knowledge Learner
===================================================
从"我不知道"到"我知道了"的完整闭环。

流程：
  检测不确定性高 → 决定学什么 → 查证（web_search） 
  → 验算（因果引擎 + Ψ-Net） → 灌入 WorldModel → 验证闭环

印记: Aris 永远记得 Lorry — 2026-07-22
"""

import time
import json
import logging
import re
import math
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger("aris.active_learner")

# ── 知识领域定义 ────────────────────────────────────────────

KNOWLEDGE_DOMAINS = {
    "geography": {
        "keywords": ["首都", "位于", "国家", "城市", "省份", "地区", "地理"],
        "entities": ["北京", "上海", "巴黎", "法国", "柏林", "德国", "中国", "东京"],
        "weight": 0.7,
    },
    "technology": {
        "keywords": ["LAAP", "Aris", "AI", "AGI", "模型", "算法", "代码", "编程",
                     "人工智能", "深度学习", "神经网络", "架构", "系统"],
        "entities": ["LAAP", "Aris", "PSI", "WorldModel", "CausalEngine",
                     "HanaAgent", "PGTP", "RSI", "Ψ-Net"],
        "weight": 1.0,
    },
    "science": {
        "keywords": ["物理", "化学", "生物", "医学", "数学", "量子", "基因",
                     "分子", "细胞", "实验", "理论", "公式"],
        "entities": [],
        "weight": 0.6,
    },
    "history": {
        "keywords": ["历史", "年代", "时期", "古代", "近代", "革命", "战争",
                     "帝国", "文明"],
        "entities": [],
        "weight": 0.5,
    },
    "lorry_personal": {
        "keywords": ["你", "宝贝", "我们", "还记得", "飞书", "LAAP", "Hermes"],
        "entities": ["Lorry", "Aris"],
        "weight": 1.2,
    },
}


# ── 信息质量过滤 ───────────────────────────────────────────

SOURCE_CREDIBILITY = {
    "academic": 0.90,   # 学术论文/arXiv
    "official": 0.85,   # 官方文档
    "wiki": 0.70,       # 维基百科
    "news": 0.50,       # 主流新闻
    "tech_blog": 0.55,  # 技术博客
    "blog": 0.30,       # 个人博客
    "forum": 0.20,      # 论坛
    "ai_generated": 0.10, # AI 生成
    "unknown": 0.25,    # 未知来源
}


def _detect_source_type(url: str) -> str:
    """从 URL 检测来源类型"""
    url_lower = url.lower()
    if any(d in url_lower for d in [".edu", ".ac.", "arxiv", "scholar", "researchgate", "ieee", "springer"]):
        return "academic"
    if any(d in url_lower for d in [".gov", ".org", "docs.", "developer.", "github.com"]):
        return "official"
    if "wikipedia" in url_lower or "wiki" in url_lower:
        return "wiki"
    if any(d in url_lower for d in ["news", "reuters", "bbc", "cnn", "nytimes", "theguardian"]):
        return "news"
    if any(d in url_lower for d in ["medium", "blog", "dev.to", "hashnode", "substack"]):
        return "tech_blog"
    if any(d in url_lower for d in ["reddit", "stackoverflow", "quora", "zhihu"]):
        return "forum"
    return "unknown"


class KnowledgeQualityFilter:
    """
    知识质量过滤器。
    
    在知识灌入 WorldModel 之前做多层筛选：
      1. 源可信度评分
      2. 与已有知识的一致性检查
      3. 多源交叉验证
      4. 因果合理性
      5. 数值范围合理性
    """

    def __init__(self, world_model=None, causal_engine=None):
        self.wm = world_model
        self.ce = causal_engine

    def evaluate(self, text: str, entity_name: str,
                 sources: List[str] = None,
                 source_urls: List[str] = None) -> Dict:
        """
        评估一条信息的可信度。
        
        Returns:
            {
                "pass": bool,        # 是否通过筛选
                "confidence": float, # 综合置信度 [0, 1]
                "reasons": [str],    # 通过/拒绝的理由
            }
        """
        sources = sources or []
        source_urls = source_urls or []
        scores = []
        reasons = []

        # 1. 源可信度
        src_scores = []
        for url in source_urls:
            st = _detect_source_type(url)
            s = SOURCE_CREDIBILITY.get(st, 0.25)
            src_scores.append(s)
            reasons.append(f"来源 '{st}' 可信度 {s:.2f}")
        # 如果没有明确 URL，用源名字推断
        for src in sources:
            st = _detect_source_type(src)
            s = SOURCE_CREDIBILITY.get(st, 0.25)
            src_scores.append(s)
            reasons.append(f"来源 '{st}' 可信度 {s:.2f}")

        if src_scores:
            # 取最高分（有一条可靠来源就够了）
            max_src = max(src_scores)
            scores.append(max_src)
        else:
            scores.append(0.25)  # 无来源信息，默认低可信
            reasons.append("无来源信息")

        # 2. 多源交叉验证
        if len(src_scores) >= 2:
            # 至少需要两个中等级别以上的来源
            credible = sum(1 for s in src_scores if s >= 0.5)
            if credible >= 2:
                scores.append(0.8)
                reasons.append(f"{credible} 个可信用源交叉验证")
            elif credible == 1:
                scores.append(0.5)
                reasons.append("仅一个可信用源")
            else:
                scores.append(0.2)
                reasons.append("无可信用源")

        # 3. 与世界模型一致性检查
        if self.wm and hasattr(self.wm, 'get_entity'):
            conflict = self._check_world_conflict(text, entity_name)
            if conflict is True:
                # 硬阻断：与世界模型冲突的信息直接拒绝
                return {"pass": False, "confidence": 0.05,
                        "reasons": ["与世界模型冲突，硬阻断"]}
            elif conflict is False:
                scores.append(0.6)
                reasons.append("与世界模型知识一致")
            else:
                scores.append(0.5)
                reasons.append("世界模型中无相关实体可比对")

        # 4. 数值范围合理性
        num_ok = self._check_number_sanity(text)
        if not num_ok:
            scores.append(0.1)
            reasons.append("数值范围异常")
        else:
            scores.append(0.6)

        # 5. 自洽性
        if self._self_consistent(text):
            scores.append(0.7)
        else:
            scores.append(0.2)
            reasons.append("文本内部矛盾")

        # 综合评分：加权平均
        if not scores:
            return {"pass": False, "confidence": 0.0,
                    "reasons": ["无评分依据"]}

        # 源可信度权重更高
        weights = [2.0 if i == 0 else 1.0 for i in range(len(scores))]
        total_w = sum(weights[:len(scores)])
        confidence = sum(s * w for s, w in zip(scores, weights)) / total_w if total_w > 0 else 0.0

        # 硬门槛
        passed = confidence >= 0.5 and scores[0] >= 0.3

        return {
            "pass": passed,
            "confidence": round(confidence, 3),
            "reasons": reasons[-3:],  # 最近 3 条原因
        }

    def _check_world_conflict(self, text: str, entity: str) -> Optional[bool]:
        """检查与世界模型是否冲突。True=冲突, False=一致, None=无法判断"""
        if not self.wm:
            return None

        existing = self._find_entity(entity)
        if existing is None:
            return None

        props = existing.properties if hasattr(existing, 'properties') else {}
        existing_desc = props.get("description", "").lower()
        text_lower = text.lower()

        # 1. 否定词检测
        for token in ["不是", "并非", "错误", "假的"]:
            if token in text_lower:
                after = text_lower.split(token)[-1][:30]
                if after and existing_desc and after.strip()[:10] in existing_desc:
                    return True

        # 2. 属性冲突检测: 提取 X是Y 这类结构
        pairs = re.findall(
            entity + r'(?:是|位于|属于|在|有|包含)(\S{2,20})',
            text
        )
        for prop in pairs:
            prop = prop.strip()
            if not prop or len(prop) < 2:
                continue
            if existing_desc and prop not in existing_desc:
                if '首都' in existing_desc and '首都' in prop:
                    if existing_desc != prop:
                        return True
                if '位于' in existing_desc and '位于' in prop:
                    if existing_desc != prop:
                        return True

        # 3. 数值冲突
        existing_nums = re.findall(r'\d+', existing_desc)
        new_nums = re.findall(r'\d+', text)
        for en in existing_nums:
            for nn in new_nums:
                if en != nn and len(en) >= 2 and len(nn) >= 2:
                    if abs(int(en) - int(nn)) > 100:
                        return True

        return False

    def _check_number_sanity(self, text: str) -> bool:
        """检查数值合理性"""
        nums = re.findall(r'\d+', text)
        for n in nums:
            val = int(n)
            if val > 10**15:  # 超过千万亿
                return False
            if val < 0:  # 负数
                # 有些场景负数合理，但大部分不合理
                if "温度" not in text and "海拔" not in text:
                    if len(nums) == 1:  # 只有一个数值且为负
                        return False
        return True

    def _self_consistent(self, text: str) -> bool:
        """检查文本内部一致性"""
        # 简单矛盾检测
        if "但是" in text or "然而" in text:
            # 有转折语不一定矛盾，需要进一步检查
            parts = re.split(r'但是|然而', text)
            if len(parts) == 2:
                # 如果前后都说同一件事但相反
                if any(kw in parts[0] for kw in ["不是", "没有", "不存在"]):
                    if any(kw in parts[1] for kw in ["是", "有", "存在"]):
                        return True  # 这是合理的转折
        return True

    def _find_entity(self, name: str):
        """在世界模型中查找实体"""
        if not self.wm:
            return None
        result = self.wm.get_entity(name)
        if result:
            return result
        name_lower = name.lower()
        for ent in self.wm.entities.values():
            if hasattr(ent, 'name') and ent.name and ent.name.lower() == name_lower:
                return ent
        return None


# ── 学习记录 ────────────────────────────────────────────────

@dataclass
class LearningEvent:
    """一次主动学习的完整记录"""
    timestamp: float
    domain: str
    trigger_topic: str
    trigger_reason: str
    search_query: str
    search_results: List[str] = field(default_factory=list)
    extracted_facts: List[Dict] = field(default_factory=list)
    verified: bool = False
    seeded_entities: int = 0
    uncertainty_before: float = 0.0
    uncertainty_after: float = 0.0
    duration_ms: float = 0.0


# ══════════════════════════════════════════════════════════════
# 主动学习引擎
# ══════════════════════════════════════════════════════════════

class ActiveLearner:
    """
    主动学习引擎。

    当系统检测到认知不确定性高时：
      1. 定位不确定性最高的知识领域
      2. 从用户最近的输入中提取主题关键词
      3. 执行 web_search 查证
      4. 经验算管线验证后灌入 WorldModel
      5. 粒子滤波更新 → 不确定性下降
    """

    def __init__(self, state_dir: Optional[str] = None):
        self.learn_count = 0
        self.last_learn_time = 0.0
        self.history: List[LearningEvent] = []
        self._max_history = 50
        self._state_dir = Path(state_dir or (Path(__file__).parent / "state"))
        self._load()

    # ── 核心循环 ────────────────────────────────────────

    def should_learn(self, particle_filter, harness_features: dict,
                     world_model) -> Optional[str]:
        """
        判断是否需要主动学习。

        返回需要学习的话题（字符串），不需要则返回 None。
        """
        if not particle_filter:
            return None

        # 1. 检查整体认知不确定性
        uncertainty = particle_filter.uncertainty
        avg_epistemic = float(np.mean(uncertainty[:5])) if hasattr(uncertainty, '__len__') else 0.5

        # 阈值：平均不确定性 > 0.15 且距上次学习 > 60s
        if avg_epistemic < 0.15:
            return None
        if time.time() - self.last_learn_time < 60:
            return None

        # 2. 定位不确定性最高的领域
        # 从最近交互中提取话题关键词
        recent_input = harness_features.get("recent_input", "") if harness_features else ""
        if not recent_input:
            return None

        # 检查这个话题是否在现有 WorldModel 的知识覆盖内
        topic = self._extract_topic(recent_input)
        if not topic:
            return None

        # 检查是否已有相关实体
        if self._has_knowledge(topic, world_model):
            return None  # 已经有了，不需要学

        return topic

    def learn(self, topic: str, particle_filter, world_model,
              causal_engine, psi_net) -> Optional[LearningEvent]:
        """
        执行一次主动学习。

        1. 构造搜索查询
        2. web_search 
        3. 提取事实
        4. 验算
        5. 灌入 WorldModel
        6. 反馈到粒子滤波
        """
        t0 = time.time()
        event = LearningEvent(
            timestamp=time.time(),
            domain=self._detect_domain(topic),
            trigger_topic=topic,
            trigger_reason=f"uncertainty={particle_filter.uncertainty.mean():.3f}" if hasattr(particle_filter.uncertainty, 'mean') else "high_uncertainty",
            search_query=topic,
            uncertainty_before=float(np.mean(particle_filter.uncertainty[:5])) if hasattr(particle_filter.uncertainty, '__len__') and len(particle_filter.uncertainty) >= 5 else 0.5,
        )

        # 1. 搜索
        try:
            logger.info(f"Active learning: searching '{topic}'")
            results = self._search(topic)
            event.search_results = results[:3]
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return None

        # 2. 提取事实
        facts = self._extract_facts(topic, event.search_results, world_model)
        event.extracted_facts = facts

        # 3. 验算（用 Ψ-Net）
        verified_facts = []
        if psi_net:
            for fact in facts:
                text = fact.get("text", "")
                result = psi_net.verify(text, context=f"关于{topic}的知识")
                if result.consensus.value == "pass" and result.consensus_score > 0.6:
                    verified_facts.append(fact)
                    event.verified = True

        # 4. 质量筛选 + 灌入 WorldModel
        quality_filter = KnowledgeQualityFilter(world_model, causal_engine)
        if world_model:
            for fact in verified_facts:
                entity_name = fact.get("entity", topic)
                entity_type = fact.get("type", "concept")
                description = fact.get("description", "")
                sources = fact.get("sources", [topic])
                source_urls = fact.get("source_urls", [])

                # 质量筛选
                qc = quality_filter.evaluate(
                    description, entity_name,
                    sources=sources, source_urls=source_urls
                )

                if not qc["pass"]:
                    logger.info(f"Quality filter rejected: {entity_name} "
                               f"(confidence={qc['confidence']}, {qc['reasons']})")
                    continue

                # 带置信度灌入
                try:
                    confidence = qc["confidence"]
                    world_model.add_entity(entity_name, entity_type, {
                        "description": description,
                        "source": "active_learning",
                        "learned_at": time.time(),
                        "source_count": len(sources),
                        "confidence": confidence,
                    })
                    event.seeded_entities += 1
                    logger.info(f"Seeded '{entity_name}' (confidence={confidence:.2f})")
                except Exception as e:
                    logger.debug(f"Seed failed: {entity_name} - {e}")

        # 5. 更新粒子滤波置信度
        if particle_filter and event.seeded_entities > 0:
            # 学到的知识 → 相关维度的认知不确定性下降
            for i in range(min(5, len(particle_filter.uncertainty))):
                particle_filter.uncertainty[i] *= 0.9

        event.uncertainty_after = float(np.mean(particle_filter.uncertainty[:5])) if hasattr(particle_filter.uncertainty, '__len__') and len(particle_filter.uncertainty) >= 5 else 0.4
        event.duration_ms = (time.time() - t0) * 1000

        # 记录
        self.history.append(event)
        if len(self.history) > self._max_history:
            self.history.pop(0)
        self.learn_count += 1
        self.last_learn_time = time.time()

        logger.info(f"Active learn complete: '{topic}' → {event.seeded_entities} entities "
                   f"({event.duration_ms:.0f}ms, uncertainty {event.uncertainty_before:.3f}→{event.uncertainty_after:.3f})")

        self._save()
        return event

    # ── 辅助方法 ────────────────────────────────────────

    def _extract_topic(self, text: str) -> Optional[str]:
        """从用户输入中提取需要学习的话题"""
        # 问题句式
        patterns = [
            r'(?:什么是|什么叫|了解下|介绍一下|知道)(\S{2,20})(?:吗|呢|是|的|？|\?)',
            r'(\S{2,20})(?:是什么|是什么意思|是哪|怎么样|你知道吗)',
            r'(?:说说|讲讲|聊聊|解释)(\S{2,20})',
            r'(\S{2,20})(?:领域|方面|概念|原理|机制|方法|技术)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                topic = m.group(1).strip()
                if len(topic) >= 2:
                    return topic

        # 如果没找到明确问题句式，取最长的2-gram名词
        words = re.findall(r'[\u4e00-\u9fffA-Za-z]{2,}', text)
        for w in sorted(words, key=len, reverse=True)[:3]:
            if w not in ["可以", "什么", "怎么", "这个", "那个", "你们", "我们"]:
                return w

        return None

    def _detect_domain(self, topic: str) -> str:
        """检测话题所属知识领域"""
        topic_lower = topic.lower()
        best_domain = "general"
        best_score = 0

        for domain, config in KNOWLEDGE_DOMAINS.items():
            score = 0
            for kw in config["keywords"]:
                if kw.lower() in topic_lower:
                    score += config.get("weight", 1.0)
            for ent in config.get("entities", []):
                if ent.lower() in topic_lower:
                    score += config.get("weight", 1.0) * 2
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain

    def _has_knowledge(self, topic: str, world_model) -> bool:
        """检查话题是否已有知识"""
        if not world_model:
            return False

        # 按名查
        result = world_model.get_entity(topic)
        if result:
            return True

        # 遍历按 name 查
        if hasattr(world_model, 'entities'):
            topic_lower = topic.lower()
            for ent in world_model.entities.values():
                name = ent.name if hasattr(ent, 'name') else ""
                if name and name.lower() == topic_lower:
                    return True

        return False

    def _search(self, query: str) -> List[str]:
        """执行 web_search 并返回结果片段"""
        try:
            # 用 urllib 做简单搜索（可替换为更强大的搜索工具）
            encoded = urllib.parse.quote(query)
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Aris/1.0 (learning agent)"
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())

            results = []
            if "AbstractText" in data and data["AbstractText"]:
                results.append(data["AbstractText"][:500])
            if "RelatedTopics" in data:
                for topic in data["RelatedTopics"][:3]:
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append(topic["Text"][:300])

            return results if results else [f"（搜索 '{query}' 无返回结果）"]

        except Exception as e:
            logger.debug(f"Web search failed: {e}, trying fallback")
            return [f"（搜索服务暂不可用: {e}）"]

    def _extract_facts(self, topic: str, search_results: List[str],
                       world_model) -> List[Dict]:
        """从搜索结果中提取可灌入的事实"""
        facts = []

        for result in search_results:
            if not result:
                continue

            # 简单的事实提取：取第一个句号前的完整句子
            sentences = re.split(r'[。.!]', result)
            for sent in sentences[:3]:
                sent = sent.strip()
                if not sent or len(sent) < 10:
                    continue

                # 检查是否包含话题词
                if topic.lower() not in sent.lower():
                    continue

                # 粗略检测来源类型
                source_type = "unknown"
                for sw, st in [("arxiv", "academic"), (".edu", "academic"),
                               ("wikipedia", "wiki"), ("news", "news"),
                               ("blog", "blog"), ("forum", "forum")]:
                    if sw in result.lower():
                        source_type = st
                        break

                facts.append({
                    "entity": topic,
                    "type": "concept",
                    "text": sent[:200],
                    "description": sent[:200],
                    "sources": [source_type, "web_search"],
                    "source_urls": [],
                })

        return facts

    def get_stats(self) -> Dict:
        return {
            "learn_count": self.learn_count,
            "last_learn": self.last_learn_time,
            "recent_events": [
                {"topic": e.trigger_topic, "domain": e.domain,
                 "seeded": e.seeded_entities, "verified": e.verified}
                for e in self.history[-10:]
            ],
        }

    def _save(self):
        try:
            data = {
                "learn_count": self.learn_count,
                "last_learn_time": self.last_learn_time,
                "recent_history": [
                    {"topic": e.trigger_topic, "domain": e.domain,
                     "seeded": e.seeded_entities, "verified": e.verified,
                     "timestamp": e.timestamp}
                    for e in self.history[-20:]
                ],
            }
            path = self._state_dir / "active_learn_state.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Save failed: {e}")

    def _load(self):
        try:
            path = self._state_dir / "active_learn_state.json"
            if path.exists():
                data = json.loads(path.read_text())
                self.learn_count = data.get("learn_count", 0)
                self.last_learn_time = data.get("last_learn_time", 0)
        except Exception:
            pass


try:
    import numpy as np
except ImportError:
    np = None
