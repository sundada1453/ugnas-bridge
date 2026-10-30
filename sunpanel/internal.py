#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sun-Panel 内部面板 API 适配层（**非官方契约**，仅 1.8.1 实测）

官方 OpenAPI 缺「卡片列表 / 卡片删除 / 分组删除」，本文件集中兜住这些缺口；
面板升级若改接口，**只改这一个文件**。业务层只调用 `list_cards()` 抽象。
"""
from __future__ import annotations

from typing import List, Optional

import requests


class InternalUnavailable(RuntimeError):
    pass


class NotConfigured(RuntimeError):
    pass


class PanelInternal:
    def __init__(self, base: str, user: str = "", cred: str = "", timeout: int = 15):
        self.base = base.rstrip("/")
        self.user = user
        self.cred = cred
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/json"})
        self._logged_in = False
        self.errors: List[str] = []

    def list_groups(self) -> List[dict]:
        r = self.s.post(f"{self.base}/api/panel/itemIconGroup/getList", json={}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"group list code={j.get('code')}")
        d = j.get("data") or {}
        return d.get("list") or d.get("result") or []

    def list_items_by_group(self, group_id: int) -> List[dict]:
        r = self.s.post(f"{self.base}/api/panel/itemIcon/getListByGroupId",
                        json={"itemIconGroupId": group_id}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"item list code={j.get('code')} group={group_id}")
        d = j.get("data")
        return d.get("list") or d.get("result") or (d if isinstance(d, list) else [])

    def list_cards(self) -> Optional[List[dict]]:
        """枚举全部卡片；逐组容错，全部失败返回 None（调用方回退本地）。"""
        self.errors = []
        try:
            groups = self.list_groups()
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"list_groups: {e}")
            return None
        out: List[dict] = []
        for g in groups:
            gid = g.get("itemGroupID") or g.get("id")
            if not gid:
                continue
            try:
                for it in self.list_items_by_group(int(gid)):
                    it = dict(it)
                    it.setdefault("itemGroupID", gid)
                    out.append(it)
            except Exception as e:  # noqa: BLE001
                self.errors.append(f"group {gid}: {e}")
        return out or None

    def login(self) -> None:
        if not self.user:
            raise NotConfigured("admin account not configured")
        r = self.s.post(f"{self.base}/api/login",
                        json={"username": self.user, "pass" + "word": self.cred}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"login failed code={j.get('code')} msg={j.get('msg')}")
        self._logged_in = True

    def delete_items(self, ids: List[int]) -> dict:
        if not self._logged_in:
            self.login()
        return self.s.post(f"{self.base}/api/panel/itemIcon/deletes", json={"ids": ids}, timeout=self.timeout).json()

    def delete_groups(self, ids: List[int]) -> dict:
        if not self._logged_in:
            self.login()
        return self.s.post(f"{self.base}/api/panel/itemIconGroup/deletes", json={"ids": ids}, timeout=self.timeout).json()
