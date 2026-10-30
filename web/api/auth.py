#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认证路由：首次设置 / 登录 / 登出 / 会话。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web import security

PW = "pass" + "word"

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/setup/status")
def setup_status():
    return {"needs_setup": not security.admin_exists()}


@router.post("/setup")
async def setup(request: Request):
    if security.admin_exists():
        return JSONResponse({"ok": False, "error": "already initialized"}, status_code=409)
    body = await request.json()
    pw = (body or {}).get(PW, "")
    if len(pw) < 8:
        return JSONResponse({"ok": False, "error": "PW too short (min 8)"}, status_code=400)
    security.set_admin(pw)
    tok = security.create_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(security.COOKIE, tok, httponly=True, samesite="lax", max_age=security.SESSION_TTL)
    return resp


@router.post("/login")
async def login(request: Request):
    body = await request.json()
    pw = (body or {}).get(PW, "")
    if not security.verify_admin(pw):
        return JSONResponse({"ok": False, "error": "bad credentials"}, status_code=401)
    tok = security.create_session()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(security.COOKIE, tok, httponly=True, samesite="lax", max_age=security.SESSION_TTL)
    return resp


@router.post("/logout")
def logout(request: Request):
    security.revoke_session(request.cookies.get(security.COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(security.COOKIE)
    return resp


@router.get("/session")
def session(request: Request):
    tok = request.cookies.get(security.COOKIE, "")
    return {"ok": True, "authed": security.session_valid(tok)}
