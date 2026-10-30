#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sunpanel.icon import resolve  # noqa: E402


def test_dashboard_first():
    url, src = resolve("OpenList", 5244, cdn_exists=lambda s: s == "openlist")
    assert src == "dashboard" and url.endswith("/openlist.svg"), (url, src)
    print("test_dashboard_first PASS")


def test_favicon_fallback():
    url, src = resolve("unknown-app", 9999, cdn_exists=lambda s: False,
                       favicon_fetch=lambda p: b"PNGDATA", cache_dir="/tmp/iconcache")
    assert src == "favicon" and url.startswith("file://"), (url, src)
    assert os.path.exists("/tmp/iconcache/app-9999.png")
    print("test_favicon_fallback PASS")


def test_manual_last():
    url, src = resolve("x", 1, cdn_exists=lambda s: False, favicon_fetch=lambda p: None)
    assert (url, src) == ("", "manual")
    print("test_manual_last PASS")


if __name__ == "__main__":
    test_dashboard_first(); test_favicon_fallback(); test_manual_last()
