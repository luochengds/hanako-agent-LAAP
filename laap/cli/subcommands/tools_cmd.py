"""Tool management"""

import logging
logger = logging.getLogger(__name__)

from laap.agent_core.agent import Agent, AgentConfig
def run(args):
    agent = Agent(AgentConfig(name="LAAP-CLI", enable_tools=True))
    tools = agent.tool_mgr.list_tools()
    if getattr(args, 'action', 'list') == "list":
        by_cat = {}
        for t in tools:
            by_cat.setdefault(t.category, []).append(t.name)
        logger.info(f"\nTools: {len(tools)} total")
        for cat, names in sorted(by_cat.items()):
            logger.info(f"  {cat}: {', '.join(names)}")