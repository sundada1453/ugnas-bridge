#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SunPanel OpenAPI v1 客户端（F3-1，按官方文档 1.8.1 定稿）

官方契约（doc.sun-panel.top/zh_cn/openapi/v1）：
- POST /openapi/v1/version
- POST /openapi/v1/item/create            (url 必填；onlyName/title/iconUrl/lanUrl/itemGroupID)
- POST /openapi/v1/item/getInfoByOnlyName (onlyName)
- POST /openapi/v1/item/update            (onlyName 必填，其余按需)
- POST /openapi/v1/itemGroup/create       (title 必填)
- POST /openapi/v1/itemGroup/getInfo      (itemGroupID | onlyName)
- POST /openapi/v1/itemGroup/getList      (无参)
注意：官方 OpenAPI 没有卡片列表、卡片删除、分组修改/删除接口（实测已确认）。
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

    def version(self) -> dict:
        return self._post("/openapi/v1/version", {}).get("data") or {}

    def get_card(self, only_name: str) -> Optional[dict]:
        try:
            return self._post("/openapi/v1/item/getInfoByOnlyName", {"onlyName": only_name}).get("data")
        except SunPanelError as e:
            if e.code in (1000,):
                raise
            return None

    def create_item(self, only_name: str, title: str, url: str, icon_url: str = "",
                    lan_url: str = "", item_group_id: Optional[int] = None,
                    item_group_only_name: Optional[str] = None) -> dict:
        body: Dict[str, Any] = {"onlyName": only_name, "title": title, "url": url,
                                "iconUrl": icon_url, "lanUrl": lan_url}
        if item_group_id:
            body["itemGroupID"] = item_group_id
        elif item_group_only_name:
            body["itemGroupOnlyName"] = item_group_only_name
        return self._post("/openapi/v1/item/create", body).get("data") or {}

    def update_item(self, only_name: str, **fields) -> bool:
        body = {"onlyName": only_name, **{k: v for k, v in fields.items() if v is not None}}
        self._post("/openapi/v1/item/update", body)
        return True

    def list_groups(self) -> List[dict]:
        d = self._post("/openapi/v1/itemGroup/getList", {}).get("data")
        return (d or {}).get("list") or []

    def get_group(self, item_group_id: Optional[int] = None, only_name: Optional[str] = None) -> Optional[dict]:
        body: Dict[str, Any] = {}
        if item_group_id:
            body["itemGroupID"] = item_group_id
        if only_name:
            body["onlyName"] = only_name
        try:
            return self._post("/openapi/v1/itemGroup/getInfo", body).get("data")
        except SunPanelError as e:
            if e.code == 1203:
                return None
            raise

    def create_group(self, title: str, only_name: Optional[str] = None) -> dict:
        body: Dict[str, Any] = {"title": title}
        if only_name:
            body["onlyName"] = only_name
        return self._post("/openapi/v1/itemGroup/create", body).get("data") or {}
