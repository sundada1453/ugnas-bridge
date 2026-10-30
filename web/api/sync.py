#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步路由（F3-2/F3-4）：预览四态、执行、回滚。"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from store.db import connect
from sunpanel.diff import Card, DiscoveredApp, diff, summarize
from sunpanel.client import SunPanelClient
from service.sync_service import SyncService
from web.api.config import get_cfg

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _load_apps():
    c = connect()
    try:
        rows = c.execute("SELECT name,ports,source FROM apps").fetchall()
    finally:
        c.close()
    apps, manual = [], set()
    for r in rows:
        ports = json.loads(r["ports"] or "[]")
        if r["source"] == "manual":
            manual.update(int(p) for p in ports)
            continue
        for p in ports:
            apps.append(DiscoveredApp(r["name"], int(p), source=r["source"]))
    return apps, manual


def _local_cards():
    c = connect()
    try:
        rows = c.execute("SELECT only_name,port,title,icon,group_id,url,lan_url FROM cards").fetchall()
    finally:
        c.close()
    return [Card(r["only_name"], int(r["port"]), title=r["title"] or "", icon=r["icon"] or "",
                 group_id=r["group_id"] or "", url=r["url"] or "", lan_url=r["lan_url"] or "") for r in rows]


def _save_cards(cards):
    c = connect()
    try:
        with c:
            for x in cards:
                c.execute("INSERT INTO cards(only_name,port,title,icon,group_id,url,lan_url) VALUES(?,?,?,?,?,?,?) "
                          "ON CONFLICT(only_name) DO UPDATE SET title=excluded.title, icon=excluded.icon, "
                          "group_id=excluded.group_id, url=excluded.url, lan_url=excluded.lan_url",
                          (x.only_name, x.port, x.title, x.icon, x.group_id, x.url, x.lan_url))
    finally:
        c.close()


def _load_cards():
    """优先内部公开接口枚举；失败回退本地 cards 表。业务层只认此抽象。"""
    sp = get_cfg("sunpanel") or {}
    if sp.get("base"):
        try:
            from sunpanel.internal import PanelInternal
            items = PanelInternal(sp["base"]).list_cards()
            if items:
                cards = []
                for it in items:
                    on = it.get("onlyName") or it.get("only_name")
                    if not on:
                        continue
                    port = 0
                    try:
                        port = int(str(it.get("url") or "").rstrip("/").split("/")[-1].split("?")[0])
                    except Exception:
                        port = 0
                    if not port and str(on).startswith("ugnas-"):
                        try:
                            port = int(str(on).split("-", 1)[1])
                        except Exception:
                            port = 0
                    cards.append(Card(on, port, title=it.get("title") or "", icon=it.get("iconUrl") or "",
                                      group_id=str(it.get("itemGroupID") or ""), url=it.get("url") or "",
                                      lan_url=it.get("lanUrl") or ""))
                if cards:
                    _save_cards(cards)
                    return cards
        except Exception:
            pass
    return _local_cards()


@router.post("/preview")
def preview():
    apps, manual = _load_apps()
    cards = _load_cards()
    rows = diff(apps, cards, manual_ports=manual)
    out = [{"state": r.state, "only_name": r.only_name, "port": r.port, "title": r.title,
            "changes": r.changes, "reason": r.reason, "old": r.old, "new": r.new} for r in rows]
    return {"rows": out, "summary": summarize(rows)}


@router.post("/apply")
async def apply(request: Request):
    body = await request.json()
    selected = body.get("selected") or []
    dispose = body.get("dispose") or {}
    sp = get_cfg("sunpanel")
    ug = get_cfg("ugreen") or {}
    if not sp:
        return JSONResponse({"ok": False, "error": "sunpanel not configured"}, status_code=400)
    admin = get_cfg("sunpanel_admin") or {}
    wants_delete = any(v == "delete" for v in dispose.values())
    if wants_delete and not admin.get("user"):
        return JSONResponse({"ok": False, "error": "删除需在设置中配置 Sun-Panel 管理员账号（默认仅支持移回收站）"}, status_code=400)
    apps, manual = _load_apps()
    cards = _load_cards()
    rows = diff(apps, cards, manual_ports=manual)
    bridge = os.environ.get("UGNAS_BRIDGE_BASE", "")
    key = os.environ.get("UGNAS_BRIDGE_KEY", "")
    svc = SyncService(SunPanelClient(sp["base"], sp["token"]), bridge_base=bridge, key=key)
    plan = svc.plan(rows, selected=selected, dispose=dispose)
    cmap = {c.only_name: {"url": c.url, "title": c.title} for c in cards}
    res = svc.apply(plan, cards=cmap)
    return {"ok": True, **res}


@router.post("/rollback")
async def rollback(request: Request):
    body = await request.json()
    path = body.get("snapshot") or ""
    if not path or not os.path.exists(path):
        return JSONResponse({"ok": False, "error": "snapshot not found"}, status_code=400)
    sp = get_cfg("sunpanel")
    if not sp:
        return JSONResponse({"ok": False, "error": "sunpanel not configured"}, status_code=400)
    svc = SyncService(SunPanelClient(sp["base"], sp["token"]))
    return {"ok": True, **svc.rollback(path)}
