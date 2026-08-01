"""激活Superpowers"""

import logging
logger = logging.getLogger(__name__)

import os

BASE = os.path.dirname(os.path.abspath(__file__))

def activate(agent=None):
    from laap.integrations.superpowers.integrator import SuperpowersIntegrator
    si = SuperpowersIntegrator()
    si.install()
    if agent:
        agent.superpowers = si
    skills = si.registry.get_all()
    logger.info(f"\nSuperpowers activated: {len(skills)} skills")
    for s in skills:
        t = s["trigger"].replace("_", " ").title()
        logger.info(f"   [{t}] {s['name']}: {s['desc']}")
    return si

def get_workflow(task):
    from laap.integrations.superpowers.registry import SuperpowerSkillRegistry
    r = SuperpowerSkillRegistry(base_path=BASE)
    wf = []
    t = task.lower()
    if any(k in t for k in ["write","create","implement","build","code","开发","编写","创建"]):
        for name in ["brainstorming","writing-plans","test-driven-development","subagent-driven-development","requesting-code-review"]:
            s = r.get(name)
            if s: wf.append(s)
    if any(k in t for k in ["debug","fix","bug","error","调试","修复","问题"]):
        for name in ["systematic-debugging","verification-before-completion"]:
            s = r.get(name)
            if s: wf.append(s)
    return wf
