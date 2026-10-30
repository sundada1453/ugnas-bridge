#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F2-1 + F3-4 服务层单元测试（假客户端，不走网络）。"""
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
        self.cards = {"ugnas-7050": {"id": "c7050", "title": "alist-old"}}

    def get_card(self, on):
        return self.cards.get(on)

    def add_item(self, **kw):
        self.calls.append(("add", kw.get("onlyName"))); return {"id": "new"}

    def update_item(self, iid, **kw):
        self.calls.append(("update", iid, kw)); return True

    def create_group(self, name):
        self.calls.append(("group", name)); return {"id": "gtrash"}

    def delete_item(self, iid):
        self.calls.append(("delete", iid)); return True


def test_plan_and_apply():
    rows = [
        {"state": "new", "only_name": "ugnas-8080", "port": 8080, "new": {"title": "sub2api", "icon": ""}},
        {"state": "update", "only_name": "ugnas-7050", "port": 7050, "new": {"title": "alist", "icon": "alist"}},
        {"state": "expired", "only_name": "ugnas-9208", "port": 9208},
        {"state": "expired", "only_name": "ugnas-9820", "port": 9820},
        {"state": "same", "only_name": "ugnas-5244", "port": 5244},
        {"state": "new", "only_name": "ugnas-9999", "port": 9999, "new": {"title": "not-selected"}},
    ]
    svc = SyncService(FakeClient())
    plan = svc.plan(rows, selected={"ugnas-8080", "ugnas-7050", "ugnas-9208", "ugnas-9820"},
                    dispose={"ugnas-9208": "trash", "ugnas-9820": "delete"})
    assert plan.total_selected() == 4, plan.total_selected()
    acts = {o.only_name: o.action for o in plan.executable()}
    assert acts == {"ugnas-8080": "create", "ugnas-7050": "update",
                    "ugnas-9208": "trash", "ugnas-9820": "delete"}, acts
    res = svc.apply(plan, snapshot_cards=[{"id": "c7050", "title": "alist-old"}])
    assert res["ok"] == 4 and res["fail"] == 0, res
    assert os.path.exists(res["snapshot"])
    print("test_plan_and_apply PASS", plan.counts())


def test_dispose_default_skip():
    svc = SyncService(FakeClient())
    plan = svc.plan([{"state": "expired", "only_name": "ugnas-1", "port": 1}], selected={"ugnas-1"})
    assert plan.total_selected() == 0, "默认跳过不应执行"
    print("test_dispose_default_skip PASS")


if __name__ == "__main__":
    test_plan_and_apply()
    test_dispose_default_skip()
