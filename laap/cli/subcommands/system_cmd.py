"""System management"""

import logging
logger = logging.getLogger(__name__)

import time
def run(args):
    logger.info(f"LAAP System\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}\nVersion: 1.0.0")