"""Crash/error log so a user hitting a bug has something concrete to send
along with a GitHub issue, instead of just "it didn't work".
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .config import config_root_dir

LOG_PATH = os.path.join(config_root_dir(), 'app.log')

logger = logging.getLogger('ceviri_novel')


def setup_logging():
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'))
    logger.addHandler(handler)

    def handle_unhandled(exc_type, exc_value, exc_tb):
        logger.critical(
            'Unhandled exception', exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_unhandled
    logger.info('--- Novel Çeviri started ---')
