#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统路由：健康检查 + 测试连接。"""
from __future__ import annotations

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from store.db import connect
from ugreen.client import UgosClient

router = APIRouter(prefix="/api", tags=["system"])


def _cfg(k: str):
    c = connect()
    try:
        return c.execute("SELECT ts FROM config WHERE k=?", (k,)).fetchone() is not None
    finally:
        c.close()


@router.get("/health")
def health():
    return {"ok": True, "version": "2.0.0-dev", "service": "ugnas-bridge",
            "configured": {"ugreen": _cfg("ugreen"), "sunpanel": _cfg("sunpanel")}}


@router.get("/health/detail")
def health_detail():
    from service.health_service import HealthService
    return HealthService().summary()


@router.post("/health/run")
def health_run():
    from service.health_service import HealthService
    return HealthService().run_once()


@router.post("/test/ugreen")
async def test_ugreen(request: Request):
    from web.api.config import get_cfg
    body = await request.json()
    if not (body or {}).get("base"):
        body = get_cfg("ugreen") or {}
    try:
        c = UgosClient(body["base"])
        d = c.login(body["user"], body["cred"])
        return {"ok": True, "nas_name": d.get("nas_name"), "model": d.get("model"),
                "system_version": d.get("system_version")}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)[:200]})


@router.post("/test/sunpanel")
async def test_sunpanel(request: Request):
    from web.api.config import get_cfg
    body = await request.json()
    if not (body or {}).get("base"):
        body = get_cfg("sunpanel") or {}
    try:
        r = requests.post(f"{body['base'].rstrip('/')}/openapi/v1/version",
                          headers={"token": body["token"], "Content-Type": "application/json"},
                          json={}, timeout=10)
        j = r.json()
        return {"ok": j.get("code") == 0, "code": j.get("code"),
                "version": (j.get("data") or {}).get("version")}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)[:200]})
