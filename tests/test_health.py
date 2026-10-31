#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康探测地址与状态口径单测（P2-7）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["UGNAS_BRIDGE_DB"] = "/tmp/dsb_health_test.db"
from store.db import init_db  # noqa: E402
from service.health_service import HealthService  # noqa: E402
from web.api.config import put_cfg, delete_cfg  # noqa: E402
from web.api.system import _health_configured  # noqa: E402

init_db()


def test_probe_host_falls_back_to_sunpanel():
    put_cfg("sunpanel", {"base": "http://100.111.245.21:13002", "token": "t"})
    delete_cfg("health")
    assert HealthService().probe_host() == "100.111.245.21"
    assert _health_configured() is True
    print("test_probe_host_falls_back_to_sunpanel PASS")


def test_explicit_health_host_wins():
    put_cfg("health", {"host": "192.168.5.10"})
    assert HealthService().probe_host() == "192.168.5.10"
    delete_cfg("health")
    delete_cfg("sunpanel")
    assert HealthService().probe_host() == ""
    assert _health_configured() is False
    print("test_explicit_health_host_wins PASS")


if __name__ == "__main__":
    test_probe_host_falls_back_to_sunpanel()
    test_explicit_health_host_wins()
