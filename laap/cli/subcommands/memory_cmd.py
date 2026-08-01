"""Memory management"""

import logging
logger = logging.getLogger(__name__)

def run(args):
    from laap.agent_core.memory_manager import MemoryManager
    mm = MemoryManager()
    stats = mm.get_stats()
    logger.info(f"Memory: {stats}")