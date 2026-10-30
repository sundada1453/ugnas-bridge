#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ugnas-bridge v2 · FastAPI 应用入口（F1-1：路由分层 + 管理认证）

- /api/* 默认需管理会话；白名单：health / setup* / login / session
- /open/{port} 免登录，靠 ?k= 口令校验
- /           返回管理页静态单页
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from store.db import init_db                      # noqa: E402
from web import security                          # noqa: E402
from web.api import auth, config, open as openapi, system  # noqa: E402

app = FastAPI(title="ugnas-bridge", version="2.0.0-dev")
init_db()

PUBLIC_API = {
    "/api/health",
    "/api/setup/status",
    "/api/setup",
    "/api/login",
    "/api/logout",
    "/api/session",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API:
        if not security.admin_exists():
            return JSONResponse({"ok": False, "error": "setup required"}, status_code=428)
        tok = request.cookies.get(security.COOKIE, "")
        if not security.session_valid(tok):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(auth.router)
app.include_router(system.router)
app.include_router(config.router)
app.include_router(openapi.router)

STATIC_DIR = os.path.join(HERE, "static")


@app.get("/")
def index():
    p = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(p):
        return FileResponse(p, media_type="text/html")
    return JSONResponse({"ok": True, "service": "ugnas-bridge", "ui": "not built yet"})


@app.get("/favicon.ico")
def favicon():
    return JSONResponse({}, status_code=204)
