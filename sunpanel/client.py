#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SunPanel OpenAPI 客户端（F3-1）

依据 v1 实测（面板 1.8.1，OpenAPI）：
- 成功 code:0；token 过期 code:1000（需重取）
- 卡片按 onlyName 读取；更新走 item/update（1.8.1 无 batchUpdate）
- 路径集中管理，便于版本适配
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests


class SunPanelError(RuntimeError):
    def __init__(self, code: int, msg: str, path: str = ""):
        super().__init__(f"SunPanel code={code} msg={msg!r} path={path}")
        self.code = code
        self.msg = msg


class SunPanelClient:
    def __init__(self, base: str, token: str, timeout: int = 20):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"token": token, "Content-Type": "application/json"})

    def _post(self, path: str, body: Optional[dict] = None) -> dict:
        r = self.s.post(f"{self.base}{path}", json=body or {}, timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            raise SunPanelError(-1, f"non-json http={r.status_code}", path)
        code = int(j.get("code", -1))
        if code != 0:
            raise SunPanelError(code, str(j.get("msg", "")), path)
        return j

    def get_card(self, only_name: str) -> Optional[dict]:
        try:
            j = self._post("/openapi/v1/item/getInfoByOnlyName", {"onlyName": only_name})
        except SunPanelError as e:
            if e.code == 1000:
                raise
            return None
        return j.get("data")

    def list_cards(self, group_id: Optional[str] = None) -> List[dict]:
        body: Dict[str, Any] = {}
        if group_id:
            body["itemGroupID"] = group_id
        j = self._post("/openapi/v1/item/getList", body)
        d = j.get("data")
        if isinstance(d, dict):
            return d.get("result") or d.get("list") or []
        return d or []

    def update_item(self, item_id: str, **fields) -> bool:
        body = {"id": item_id, **{k: v for k, v in fields.items() if v is not None}}
        self._post("/openapi/v1/item/update", body)
        return True

    def add_item(self, **fields) -> dict:
        return self._post("/openapi/v1/item/add", fields).get("data") or {}

    def list_groups(self) -> List[dict]:
        j = self._post("/openapi/v1/itemGroup/getList", {})
        d = j.get("data")
        return (d.get("result") or d.get("list") or []) if isinstance(d, dict) else (d or [])

    def create_group(self, name: str, icon: str = "") -> dict:
        return self._post("/openapi/v1/itemGroup/add", {"title": name, "icon": icon}).get("data") or {}
