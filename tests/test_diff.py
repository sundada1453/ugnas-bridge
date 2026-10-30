#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F3-2 四态 diff 单元测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sunpanel.diff import Card, DiscoveredApp, diff, summarize  # noqa: E402


def test_four_states():
    cards = [
        Card("ugnas-5244", 5244, title="openlist", icon="openlist", group_id="13"),
        Card("ugnas-8097", 8097, title="Emby", icon="emby", group_id="13"),
        Card("ugnas-7050", 7050, title="alist-old", icon="alist", group_id="13"),
        Card("ugnas-9208", 9208, title="mdc"),
        Card("ugnas-9820", 9820, title="cc-connect"),
        Card("ugnas-6080", 6080, title="vnc"),
    ]
    apps = [
        DiscoveredApp("openlist", 5244, icon="openlist", group_id="13"),
        DiscoveredApp("Emby", 8097, icon="emby", group_id="13"),
        DiscoveredApp("alist", 7050, icon="alist", group_id="13"),
        DiscoveredApp("sub2api", 8080, icon="", group_id="13"),
    ]
    rows = diff(apps, cards, manual_ports=[6080])
    s = summarize(rows)
    assert s == {"new": 1, "update": 1, "expired": 2, "same": 3}, s
    assert [r.state for r in rows] == ["new", "update", "expired", "expired", "same", "same", "same"]
    up = [r for r in rows if r.state == "update"][0]
    assert up.changes == ["title"], up.changes
    assert any(r.port == 6080 and r.state == "same" for r in rows)
    new = [r for r in rows if r.state == "new"][0]
    assert new.only_name == "ugnas-8080"
    print("test_four_states PASS", s)


def test_empty():
    assert summarize(diff([], [])) == {"new": 0, "update": 0, "expired": 0, "same": 0}
    print("test_empty PASS")


if __name__ == "__main__":
    test_four_states()
    test_empty()
