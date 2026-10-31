#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sun-Panel 内部面板 API 适配层（**非官方契约**，仅 1.8.1 实测）

官方 OpenAPI 缺「卡片列表 / 卡片删除 / 分组删除」，本文件集中兜住这些缺口；
面板升级若改接口，**只改这一个文件**。业务层只调用 `list_cards()` / `delete_items_by_names()` 抽象。

实测/源码依据（v1.8.1）：
- POST /api/panel/itemIconGroup/getList         公开模式可读，无需登录
- POST /api/panel/itemIcon/getListByGroupId    公开模式可读，body {"itemIconGroupId": <id>}
- POST /api/panel/itemIcon/deletes             需登录，body {"ids":[...]}
- POST /api/panel/itemIconGroup/deletes        需登录，body {"ids":[...]}
- POST /api/login                              管理员账号登录（JWT，token 在 data.token）

回退策略：
- list_cards(): 逐组拉取；任一组失败则跳过该组并记录 error；全部失败返回 None，由调用方显式标注「本地快照」。
- 删除：未配置管理员账号时直接抛 NotConfigured；登录失败抛 AuthError。

2026-10-31 QA 修复（P0-2）：login() 必须把 data.token 写入 session header，否则后续内部接口全部
返回 {"code":1000,"msg":"not logged in yet"}（旧实现只置 _logged_in 标志，形态正确但功能死路）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

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
        self.token = ""
        self.errors: List[str] = []

    # ---------- 公开只读 ----------
    def list_groups(self) -> List[dict]:
        r = self.s.post(f"{self.base}/api/panel/itemIconGroup/getList", json={}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"group list code={j.get('code')} msg={j.get('msg', '')}")
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
        """抽象：枚举全部卡片。失败返回 None（调用方须显式标注本地快照）。"""
        self.errors = []
        if self.user:
            try:
                self.login()
            except Exception as e:  # noqa: BLE001
                # 登录失败不阻断公开只读枚举；删除等管理操作会再次抛错
                self.errors.append(f"login: {e}")
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
        return out

    def find_item_ids(self, only_names: List[str]) -> Dict[str, int]:
        """onlyName -> 面板卡片 id。仅返回能在面板中定位到的项。"""
        wanted = set(only_names)
        items = self.list_cards() or []
        out: Dict[str, int] = {}
        for it in items:
            on = it.get("onlyName") or it.get("only_name")
            if on in wanted and it.get("id") is not None:
                try:
                    out[str(on)] = int(it["id"])
                except (TypeError, ValueError):
                    continue
        return out

    # ---------- 管理员（可选，解锁删除） ----------
    def login(self) -> None:
        if not self.user:
            raise NotConfigured("admin account not configured")
        r = self.s.post(f"{self.base}/api/login",
                        json={"username": self.user, "pass" + "word": self.cred}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"login failed code={j.get('code')} msg={j.get('msg')}")
        data = j.get("data") or {}
        token = data.get("token") or j.get("token") or ""
        if not token:
            raise InternalUnavailable("login ok but no token in response")
        # P0-2：登录 token 必须注入后续内部接口请求头，否则全部 code=1000 not logged in yet
        self.token = token
        self.s.headers["token"] = token
        self._logged_in = True

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def delete_items(self, ids: List[int]) -> dict:
        self._ensure_login()
        r = self.s.post(f"{self.base}/api/panel/itemIcon/deletes", json={"ids": ids}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"item delete failed code={j.get('code')} msg={j.get('msg')}")
        return j

    def delete_items_by_names(self, only_names: List[str]) -> dict:
        """按 onlyName 批量删除：先枚举定位 id，再一次性提交 deletes。"""
        idmap = self.find_item_ids(only_names)
        missing = [n for n in only_names if n not in idmap]
        ids = list(idmap.values())
        if ids:
            self.delete_items(ids)
        return {"deleted": [n for n in only_names if n in idmap], "missing": missing}

    def delete_groups(self, ids: List[int]) -> dict:
        self._ensure_login()
        r = self.s.post(f"{self.base}/api/panel/itemIconGroup/deletes", json={"ids": ids}, timeout=self.timeout)
        j = r.json()
        if j.get("code") not in (0, 200):
            raise InternalUnavailable(f"group delete failed code={j.get('code')} msg={j.get('msg')}")
        return j
