#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置合并语义单测（P1-3）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["UGNAS_BRIDGE_DB"] = "/tmp/dsb_config_test.db"
from store.db import init_db  # noqa: E402
from web.api.config import get_cfg, put_cfg, delete_cfg  # noqa: E402

init_db()


def test_merge_keeps_empty_credentials():
    put_cfg("qa_tmp", {"base": "http://a", "user": "u", "cred": "secret123"})
    put_cfg("qa_tmp", {"base": "http://b", "user": "u", "cred": ""})
    v = get_cfg("qa_tmp")
    assert v["base"] == "http://b" and v["cred"] == "secret123", v
    delete_cfg("qa_tmp")
    print("test_merge_keeps_empty_credentials PASS")


def test_clear_config():
    put_cfg("sunpanel_admin", {"user": "admin", "cred": "pw"})
    put_cfg("sunpanel_admin", {"__clear__": True})
    assert get_cfg("sunpanel_admin") is None
    print("test_clear_config PASS")


if __name__ == "__main__":
    test_merge_keeps_empty_credentials()
    test_clear_config()
