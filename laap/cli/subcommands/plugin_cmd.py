"""Plugin management"""

import logging
logger = logging.getLogger(__name__)

def run(args):
    from laap.agent_core.plugins.manager import PluginManager
    pm = PluginManager()
    if getattr(args, 'action', 'list') == "list":
        infos = pm.discover()
        logger.info(f"\nPlugins: {len(infos)} found")
        for info in infos:
            logger.info(f"  {info.name}: {info.description}")