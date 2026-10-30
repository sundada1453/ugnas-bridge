#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志：按大小轮转（bridge.log），避免长期运行涨满磁盘。"""
from __future__ import annotations
import logging, os
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str = "", max_bytes: int = 5 * 1024 * 1024, backups: int = 5) -> logging.Logger:
    log_dir = log_dir or os.environ.get("UGNAS_LOG_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"))
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("ugnas_bridge")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(os.path.join(log_dir, "bridge.log"), maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    return logger
