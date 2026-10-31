#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sun-Panel 内部适配层单测（假 Session，不走网络）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sunpanel.internal import PanelInternal  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return FakeResp(self.responses.pop(0))


def test_login_persists_token_header():
    """P0-2 回归：login() 必须把 data.token 写入后续请求头。"""
    pi = PanelInternal("http://panel.test", user="admin", cred="pw")
    pi.s = FakeSession([
        {"code": 0, "data": {"token": "tok-abc"}},
        {"code": 0, "data": {"list": [{"id": 7, "onlyName": "ugnas-9820"}]}},
        {"code": 0, "data": {"list": [{"id": 42, "onlyName": "ugnas-9820"}]}},
    ])
    pi.login()
    assert pi.token == "tok-abc"
    assert pi.s.headers.get("token") == "tok-abc", pi.s.headers
    print("test_login_persists_token_header PASS")


def test_delete_items_by_names():
    pi = PanelInternal("http://panel.test", user="admin", cred="pw")
    pi.s = FakeSession([
        {"code": 0, "data": {"token": "tok-abc"}},
        {"code": 0, "data": {"list": [{"id": 1, "onlyName": "ugnas-1"}]}},
        {"code": 0, "data": {"list": [{"id": 42, "onlyName": "ugnas-9820"}]}},
        {"code": 0, "msg": "OK"},
    ])
    out = pi.delete_items_by_names(["ugnas-9820", "ugnas-missing"])
    assert out["deleted"] == ["ugnas-9820"] and out["missing"] == ["ugnas-missing"], out
    assert pi.s.calls[-1][0].endswith("/api/panel/itemIcon/deletes"), pi.s.calls[-1]
    assert pi.s.calls[-1][1] == {"ids": [42]}, pi.s.calls[-1]
    print("test_delete_items_by_names PASS")


if __name__ == "__main__":
    test_login_persists_token_header()
    test_delete_items_by_names()
