#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发现路由（F2-1/F2-2）：执行发现、应用清单、手动绑定端口。

2026-10-31 QA 修复（P2-3）：手动绑定校验端口 1-65535、请求内去重、已存在端口不重复插入。
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from store.db import connect
from ugreen.client import UgosClient
from discover.ugos_docker import UgosDocker
from discover.container_exec import ContainerExec
from service.discover_service import DiscoverService
from web.api.config import get_cfg

router = APIRouter(prefix="/api", tags=["discover"])


@router.get("/apps")
def list_apps():
    c = connect()
    try:
        rows = c.execute("SELECT container_id,name,net,ports,source,state,discovered_at FROM apps ORDER BY name").fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["ports"] = json.loads(d["ports"] or "[]")
        out.append(d)
    return {"apps": out}


@router.post("/apps/manual")
async def manual_bind(request: Request):
    body = await request.json()
    raw_ports = body.get("ports") or []
    names = body.get("names") or {}
    now = int(time.time())

    # 校验 + 去重
    ports = []
    invalid = []
    for p in raw_ports:
        try:
            p = int(p)
        except (TypeError, ValueError):
            invalid.append(str(p))
            continue
        if not (1 <= p <= 65535):
            invalid.append(str(p))
            continue
        if p not in ports:
            ports.append(p)

    c = connect()
    added = skipped = 0
    skipped_ports = []
    try:
        existing = set()
        for r in c.execute("SELECT ports FROM apps").fetchall():
            try:
                existing.update(int(x) for x in json.loads(r["ports"] or "[]"))
            except Exception:
                continue
        with c:
            for p in ports:
                if p in existing:
                    skipped += 1
                    skipped_ports.append(p)
                    continue
                nm = names.get(str(p)) or f"manual-{p}"
                c.execute("INSERT INTO apps(container_id,name,net,ports,source,state,discovered_at) "
                          "VALUES(?,?,?,?,?,?,?) ON CONFLICT(container_id,name) DO UPDATE SET "
                          "ports=excluded.ports, source=excluded.source, discovered_at=excluded.discovered_at",
                          (f"manual:{p}", nm, "manual", json.dumps([p]), "manual", "manual", now))
                added += 1
    finally:
        c.close()
    return {"success": True, "added": added, "skipped": skipped,
            "skipped_ports": skipped_ports, "invalid": invalid}


@router.post("/discover/run")
async def run_discover():
    ug = get_cfg("ugreen")
    if not ug:
        return JSONResponse({"success": False, "error": "ugreen not configured"}, status_code=400)
    try:
        c = UgosClient(ug["base"])
        c.login(ug["user"], ug["cred"])
        svc = DiscoverService(UgosDocker(c), ContainerExec(c))
        res = svc.run()
        return {"success": True, "count": res["count"], "sources": res["sources"]}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"success": False, "error": str(e)[:240]}, status_code=502)
