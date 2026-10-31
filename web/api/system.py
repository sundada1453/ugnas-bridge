#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统路由：健康检查 + 测试连接。

2026-10-31 QA 修复（P1-2）：测试连接按「字段级合并」使用已保存配置——
前端传空字符串表示「沿用已存值」，不再把空凭据发给后端导致必然失败。
2026-10-31 QA 复测（P2-7）：configured.health 改为判断有效探测地址（health.host 或 Sun-Panel 主机回退）。
"""
from __future__ import annotations

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from store.db import connect
from ugreen.client import UgosClient

router = APIRouter(prefix="/api", tags=["system"])


def _cfg(k: str):
    """读取配置（密文由 config 路由写入，此处仅判存在）。"""
    c = connect()
    try:
        return c.execute("SELECT ts FROM config WHERE k=?", (k,)).fetchone() is not None
    finally:
        c.close()


def _health_configured() -> bool:
    """P2-7：反映是否有可用探测地址（health.host 或 Sun-Panel 主机回退），与 /api/health/detail 一致。"""
    try:
        from service.health_service import HealthService
        return bool(HealthService().probe_host())
    except Exception:  # noqa: BLE001
        return _cfg("health")


def _merge_cfg(kind: str, body: dict) -> dict:
    from web.api.config import get_cfg
    out = dict(get_cfg(kind) or {})
    for k, v in (body or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue  # 空 = 沿用已存值
        out[k] = v.strip() if isinstance(v, str) else v
    return out


@router.get("/health")
def health():
    return {"ok": True, "version": "2.0.0", "service": "ugnas-bridge",
            "configured": {"ugreen": _cfg("ugreen"), "sunpanel": _cfg("sunpanel"),
                           "health": _health_configured()}}


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
    body = _merge_cfg("ugreen", await request.json())
    if not body.get("base") or not body.get("user") or not body.get("cred"):
        return JSONResponse(status_code=400,
                            content={"success": False, "error": "请先填写并保存绿联地址/用户名/密码"})
    try:
        c = UgosClient(body["base"])
        d = c.login(body["user"], body["cred"])
        return {"success": True, "ok": True, "nas_name": d.get("nas_name"), "model": d.get("model"),
                "system_version": d.get("system_version")}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"success": False, "error": f"绿联连接失败：{str(e)[:200]}"})


@router.post("/test/sunpanel")
async def test_sunpanel(request: Request):
    body = _merge_cfg("sunpanel", await request.json())
    if not body.get("base") or not body.get("token"):
        return JSONResponse(status_code=400,
                            content={"success": False, "error": "请先填写并保存 Sun-Panel 地址/OpenAPI Token"})
    try:
        r = requests.post(f"{body['base'].rstrip('/')}/openapi/v1/version",
                          headers={"token": body["token"], "Content-Type": "application/json"},
                          json={}, timeout=10)
        j = r.json()
        ok = j.get("code") == 0
        return {"success": ok, "ok": ok, "code": j.get("code"),
                "version": (j.get("data") or {}).get("version"),
                "error": "" if ok else f"面板返回 code={j.get('code')} msg={j.get('msg', '')}"}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"success": False, "error": f"Sun-Panel 连接失败：{str(e)[:200]}"})
