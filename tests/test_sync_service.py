#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F3-4 同步服务单测（假客户端，不走网络）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UGNAS_BRIDGE_DB", "/tmp/dsb_sync_test.db")
from service.sync_service import SyncService  # noqa: E402
from store.db import init_db  # noqa: E402

init_db()


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_item(self, on, title, url, icon_url="", item_group_id=None):
        self.calls.append(("create", on, title, url, item_group_id)); return {"id": 1}

    def update_item(self, on, **kw):
        self.calls.append(("update", on, kw)); return True

    def create_group(self, title):
        self.calls.append(("group", title)); return {"itemGroupID": 999}


class FakePanel:
    def __init__(self, ids=None):
        self.ids = ids or {"ugnas-9820": 42}
        self.deleted = []

    def find_item_ids(self, names):
        return {n: self.ids[n] for n in names if n in self.ids}

    def delete_items(self, ids):
        self.deleted.extend(ids)
        return {"code": 0, "msg": "OK"}

    def delete_items_by_names(self, names):
        idmap = self.find_item_ids(names)
        missing = [n for n in names if n not in idmap]
        if idmap:
            self.delete_items(list(idmap.values()))
        return {"deleted": [n for n in names if n in idmap], "missing": missing}


def test_plan_and_apply_v1_snapshot():
    rows = [
        {"state": "new", "only_name": "ugnas-8080", "port": 8080, "new": {"title": "sub2api"}},
        {"state": "update", "only_name": "ugnas-7050", "port": 7050, "new": {"title": "alist"}},
        {"state": "expired", "only_name": "ugnas-9208", "port": 9208},
        {"state": "expired", "only_name": "ugnas-9820", "port": 9820},
        {"state": "same", "only_name": "ugnas-5244", "port": 5244},
        {"state": "new", "only_name": "ugnas-9999", "port": 9999, "new": {"title": "x"}},
    ]
    cli = FakeClient()
    svc = SyncService(cli, bridge_base="http://1.94.204.44:8770", key="K", panel=FakePanel())
    plan = svc.plan(rows, selected={"ugnas-8080", "ugnas-7050", "ugnas-9208", "ugnas-9820"},
                    dispose={"ugnas-9208": "trash", "ugnas-9820": "delete"})
    assert plan.total_selected() == 4
    res = svc.apply(plan, cards={"ugnas-7050": {"url": "https://old/7050", "title": "旧标题", "group_id": "3"},
                                 "ugnas-9208": {"url": "https://old/9208"},
                                 "ugnas-9820": {"url": "https://old/9820"}})
    assert res["ok"] == 4, res
    snap = json.load(open(res["snapshot"], encoding="utf-8"))
    assert set(snap.keys()) >= {"ts", "service_base", "changed"}
    rec = snap["changed"]["ugnas-7050"]
    assert rec["new_url"] == "http://1.94.204.44:8770/open/7050?k=K", rec
    assert rec["old_url"] == "https://old/7050" and rec["old_title"] == "旧标题", rec
    rb = svc.rollback(res["snapshot"])
    assert rb["ok"] == 4, rb
    assert ("update", "ugnas-7050", {"url": "https://old/7050", "title": "旧标题", "itemGroupID": 3}) in cli.calls, cli.calls
    print("test_plan_and_apply_v1_snapshot PASS", plan.counts())


def test_default_skip():
    svc = SyncService(FakeClient())
    plan = svc.plan([{"state": "expired", "only_name": "ugnas-1", "port": 1}], selected={"ugnas-1"})
    assert plan.total_selected() == 0
    print("test_default_skip PASS")


def test_delete_via_panel():
    """P0-1 回归：delete 必须走 PanelInternal 批量删除，而不是 SunPanelClient.delete_item。"""
    panel = FakePanel({"ugnas-9820": 42})
    svc = SyncService(FakeClient(), panel=panel)
    plan = svc.plan([{"state": "expired", "only_name": "ugnas-9820", "port": 9820}],
                    selected={"ugnas-9820"}, dispose={"ugnas-9820": "delete"})
    res = svc.apply(plan, cards={"ugnas-9820": {"url": "https://old/9820"}})
    assert res["ok"] == 1 and res["fail"] == 0, res
    assert panel.deleted == [42], panel.deleted
    print("test_delete_via_panel PASS")


def test_delete_without_admin_fails_clearly():
    svc = SyncService(FakeClient(), panel=None)
    plan = svc.plan([{"state": "expired", "only_name": "ugnas-9820", "port": 9820}],
                    selected={"ugnas-9820"}, dispose={"ugnas-9820": "delete"})
    res = svc.apply(plan, cards={})
    assert res["ok"] == 0 and res["fail"] == 1, res
    assert "管理员账号" in res["results"][0]["error"], res
    print("test_delete_without_admin_fails_clearly PASS")


def test_rollback_delete_recreates_card():
    panel = FakePanel({"ugnas-9820": 42})
    cli = FakeClient()
    svc = SyncService(cli, panel=panel)
    plan = svc.plan([{"state": "expired", "only_name": "ugnas-9820", "port": 9820}],
                    selected={"ugnas-9820"}, dispose={"ugnas-9820": "delete"})
    res = svc.apply(plan, cards={"ugnas-9820": {"url": "https://old/9820", "title": "旧卡", "group_id": "5"}})
    rb = svc.rollback(res["snapshot"])
    assert rb["ok"] == 1, rb
    assert ("create", "ugnas-9820", "旧卡", "https://old/9820", 5) in cli.calls, cli.calls
    print("test_rollback_delete_recreates_card PASS")


if __name__ == "__main__":
    test_plan_and_apply_v1_snapshot()
    test_default_skip()
    test_delete_via_panel()
    test_delete_without_admin_fails_clearly()
    test_rollback_delete_recreates_card()
