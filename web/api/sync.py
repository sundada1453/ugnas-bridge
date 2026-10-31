#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步路由（F3-2/F3-4）：预览四态、执行、回滚。

2026-10-31 QA 修复：
- P0-3：_load_cards() 返回 (cards, meta)。面板枚举成功 → source=panel；失败 → source=local（stale=true），
  preview 必须在响应里标注数据源，apply 则直接 409 拒绝，禁止用过期快照做写入判定（防重复建卡）。
- P0-1：apply 构造 PanelInternal 传入 SyncService，删除走管理员内部接口。
- 响应包络改用 success 字段，避免与计数 ok 冲突（旧实现 {"ok": True, **{"ok": 0}} 被覆盖成 0）。
- v2.0.1：四态三层兜底（apps + 宿主 TCP probe + health）；v1 cards_state 保护；只管理 ugnas-<port> 卡。
"""
from __future__ import annotations

import json
import os
import re

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


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _legacy_ports():
    """v1 遗产保护：读取 state/cards_state.json（v1 快照）的 ugnas-<port> 卡。

    用户明确要求不碰 v1 遗产 26 卡；这些卡即使当前发现集没有对应端口，也不得判过期。
    仅对已存在的卡生效（diff 的 manual 池），不会创建新卡。
    """
    path = os.environ.get("UGNAS_LEGACY_STATE", os.path.join(ROOT, "state", "cards_state.json"))
    try:
        data = json.load(open(path, encoding="utf-8"))
        out = set()
        for name in (data.get("changed") or {}):
            m = re.match(r"^ugnas-(\d+)$", str(name))
            if m:
                out.add(int(m.group(1)))
        return out
    except Exception:
        return set()


def _local_cards():
    c = connect()
    try:
        rows = c.execute("SELECT only_name,port,title,icon,group_id,url,lan_url FROM cards").fetchall()
    finally:
        c.close()
    return [Card(r["only_name"], int(r["port"]), title=r["title"] or "", icon=r["icon"] or "",
                 group_id=r["group_id"] or "", url=r["url"] or "", lan_url=r["lan_url"] or "") for r in rows]


def _live_ports():
    """四态判定兜底：宿主 TCP 探测 + health 已确认 up 的端口。

    layer1 容器发现端口由 _load_apps 负责；本函数提供 layer2/3。
    返回 (ports, meta)；探测失败不影响已有 apps 结果。
    """
    ports = set()
    meta = {}
    try:
        from discover.host_probe import host_listening_ports
        hp = host_listening_ports()
        meta["host_probe"] = {"ok": hp.get("ok", False), "count": len(hp.get("ports") or []),
                              "container": hp.get("container", ""), "error": hp.get("error", "")}
        if hp.get("ok"):
            ports.update(int(p) for p in (hp.get("ports") or []))
    except Exception as e:  # noqa: BLE001
        meta["host_probe"] = {"ok": False, "count": 0, "error": str(e)[:160]}
    try:
        c = connect()
        try:
            rows = c.execute("SELECT port FROM health WHERE up=1").fetchall()
        finally:
            c.close()
        health_ports = {int(r["port"]) for r in rows}
        ports.update(health_ports)
        meta["health_ports"] = len(health_ports)
    except Exception as e:  # noqa: BLE001
        meta["health_ports"] = 0
        meta["health_error"] = str(e)[:160]
    return ports, meta


def _save_cards(cards):
    """把面板实时枚举结果整体替换本地 cards 表（供离线视图/回滚参考）。"""
    c = connect()
    try:
        with c:
            c.execute("DELETE FROM cards")
            for x in cards:
                c.execute("INSERT INTO cards(only_name,port,title,icon,group_id,url,lan_url) VALUES(?,?,?,?,?,?,?)",
                          (x.only_name, x.port, x.title, x.icon, x.group_id, x.url, x.lan_url))
    finally:
        c.close()


def _panel():
    sp = get_cfg("sunpanel") or {}
    admin = get_cfg("sunpanel_admin") or {}
    if not sp.get("base"):
        return None, sp, admin
    from sunpanel.internal import PanelInternal
    return PanelInternal(sp["base"], user=admin.get("user", ""), cred=admin.get("cred", "")), sp, admin


def _load_cards(require_live: bool = False):
    """内部抽象：返回 (cards, meta)。meta.source ∈ {panel, local}，local 表示快照可能过期。"""
    pi, sp, admin = _panel()
    errors = []
    if pi is None:
        errors.append("Sun-Panel 未配置")
        if require_live:
            raise RuntimeError("；".join(errors))
        cards = _local_cards()
        return cards, {"source": "local", "stale": True, "count": len(cards), "errors": errors,
                       "admin_configured": bool(admin.get("user"))}
    try:
        items = pi.list_cards()
        if items is None:
            raise RuntimeError("面板卡片枚举失败: " + "；".join(pi.errors or ["unknown"]))
        cards = []
        skipped_no_name = 0
        skipped_unmanaged = 0
        for it in items:
            on = it.get("onlyName") or it.get("only_name")
            if not on:
                skipped_no_name += 1
                continue
            # 只管理 bridge 自己的 ugnas-<port> 卡；用户原生卡/分组卡不参与四态与删除
            if not re.match(r"^ugnas-\d+$", str(on)):
                skipped_unmanaged += 1
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
        _save_cards(cards)
        return cards, {"source": "panel", "stale": False, "count": len(cards),
                       "skipped_no_name": skipped_no_name,
                       "skipped_unmanaged": skipped_unmanaged,
                       "errors": pi.errors,
                       "admin_configured": bool(admin.get("user"))}
    except Exception as e:  # noqa: BLE001
        errors.append(str(e)[:240])
        if require_live:
            raise RuntimeError("；".join(errors))
        cards = _local_cards()
        return cards, {"source": "local", "stale": True, "count": len(cards), "errors": errors,
                       "admin_configured": bool(admin.get("user"))}


@router.post("/preview")
def preview():
    sp = get_cfg("sunpanel") or {}
    if not sp.get("base"):
        return JSONResponse({"success": False, "error": "Sun-Panel 未配置，请先在设置页配置面板地址与 OpenAPI Token"},
                            status_code=400)
    apps, manual = _load_apps()
    cards, meta = _load_cards(require_live=False)
    live_ports, live_meta = _live_ports()
    legacy_ports = _legacy_ports()
    rows = diff(apps, cards, manual_ports=set(manual) | live_ports | legacy_ports)
    out = [{"state": r.state, "only_name": r.only_name, "port": r.port, "title": r.title,
            "changes": r.changes, "reason": r.reason, "old": r.old, "new": r.new} for r in rows]
    meta["live_ports"] = {"count": len(live_ports), **live_meta}
    meta["legacy_protected"] = len(legacy_ports)
    return {"success": True, "rows": out, "summary": summarize(rows), "data_source": meta}


@router.post("/apply")
async def apply(request: Request):
    body = await request.json()
    selected = body.get("selected") or []
    dispose = body.get("dispose") or {}
    group_id = body.get("group_id")
    sp = get_cfg("sunpanel")
    if not sp:
        return JSONResponse({"success": False, "error": "Sun-Panel 未配置"}, status_code=400)
    admin = get_cfg("sunpanel_admin") or {}
    wants_delete = any(v == "delete" for v in dispose.values())
    if wants_delete and not admin.get("user"):
        return JSONResponse({"success": False,
                             "error": "删除需在设置中配置 Sun-Panel 管理员账号（默认仅支持移回收站）"},
                            status_code=400)
    apps, manual = _load_apps()
    try:
        cards, meta = _load_cards(require_live=True)
    except RuntimeError as e:
        return JSONResponse({"success": False,
                             "error": "面板卡片枚举失败，已阻止执行（避免重复建卡）：" + str(e)},
                            status_code=409)
    live_ports, _live_meta = _live_ports()
    legacy_ports = _legacy_ports()
    rows = diff(apps, cards, manual_ports=set(manual) | live_ports | legacy_ports)
    bridge = os.environ.get("UGNAS_BRIDGE_BASE", "")
    key = os.environ.get("UGNAS_BRIDGE_KEY", "")
    panel = None
    if admin.get("user"):
        from sunpanel.internal import PanelInternal
        panel = PanelInternal(sp["base"], user=admin.get("user", ""), cred=admin.get("cred", ""))
    svc = SyncService(SunPanelClient(sp["base"], sp["token"]), bridge_base=bridge, key=key, panel=panel)
    plan = svc.plan(rows, selected=selected, dispose=dispose)
    if group_id:
        for op in plan.ops:
            if op.action == "create":
                op.group_id = int(group_id)
    cmap = {c.only_name: {"url": c.url, "title": c.title, "icon": c.icon,
                          "group_id": c.group_id, "lan_url": c.lan_url} for c in cards}
    res = svc.apply(plan, cards=cmap)
    return {"success": True, **res}


@router.post("/rollback")
async def rollback(request: Request):
    body = await request.json()
    path = body.get("snapshot") or ""
    if not path or not os.path.exists(path):
        return JSONResponse({"success": False, "error": "snapshot not found"}, status_code=400)
    sp = get_cfg("sunpanel")
    if not sp:
        return JSONResponse({"success": False, "error": "Sun-Panel 未配置"}, status_code=400)
    svc = SyncService(SunPanelClient(sp["base"], sp["token"]))
    return {"success": True, **svc.rollback(path)}
