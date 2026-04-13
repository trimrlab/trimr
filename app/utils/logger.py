"""
@Project: Trimr
@File: app/utils/logger.py
@Description: Centralized logging configuration
"""

import logging
import sys

def setup_logger(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("trimr")

    if logger.handlers:
        return logger

    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(fmt)

    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("trimr")
