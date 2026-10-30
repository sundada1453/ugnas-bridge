#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ugnas-bridge v2 · FastAPI 骨架（M1-6）

- 配置加密落盘：SQLite + 机器绑定密钥（core/crypto.py），绝不回显明文
- 测试连接：/api/test/ugreen（登录实测）、/api/test/sunpanel（version 实测）
- /open/{port}?k= ：复用 v1 换 token → 302
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core.crypto import encrypt, decrypt      # noqa: E402
from ugreen.client import UgosClient, UgosError  # noqa: E402

DB = os.environ.get("UGNAS_BRIDGE_DB", os.path.join(ROOT, "state", "ugnas_bridge.db"))
os.makedirs(os.path.dirname(DB), exist_ok=True)
app = FastAPI(title="ugnas-bridge", version="2.0.0-poc")


def db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, enc TEXT, salt TEXT, ts INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, action TEXT, detail TEXT)")
    return c


def put_cfg(k: str, value: dict):
    salt = os.urandom(16)
    enc = encrypt(json.dumps(value, ensure_ascii=False), salt)
    c = db()
    with c:
        c.execute("INSERT INTO config(k,enc,salt,ts) VALUES(?,?,?,?) "
                  "ON CONFLICT(k) DO UPDATE SET enc=excluded.enc, salt=excluded.salt, ts=excluded.ts",
                  (k, enc, base64.b64encode(salt).decode(), int(time.time())))
    c.close()


def get_cfg(k: str):
    c = db()
    row = c.execute("SELECT enc,salt FROM config WHERE k=?", (k,)).fetchone()
    c.close()
    if not row:
        return None
    return json.loads(decrypt(row[0], base64.b64decode(row[1])))


class UgreenCfg(BaseModel):
    base: str
    user: str
    cred: str


class SunPanelCfg(BaseModel):
    base: str
    token: str


@app.get("/api/health")
def health():
    ug = get_cfg("ugreen") or {}
    sp = get_cfg("sunpanel") or {}
    return {"ok": True, "version": app.version, "configured": {"ugreen": bool(ug), "sunpanel": bool(sp)},
            "ts": int(time.time())}


@app.post("/api/config/ugreen")
async def set_ugreen(request: Request):
    put_cfg("ugreen", await request.json())
    return {"ok": True}


@app.post("/api/config/sunpanel")
async def set_sunpanel(request: Request):
    put_cfg("sunpanel", await request.json())
    return {"ok": True}


@app.get("/api/config")
def get_all():
    ug = get_cfg("ugreen") or {}
    sp = get_cfg("sunpanel") or {}
    return {
        "ugreen": {**{k: ug.get(k) for k in ("base", "user")}, "cred": ("***" if ug.get("cred") else "")},
        "sunpanel": {"base": sp.get("base"), "token": ("***" if sp.get("token") else "")},
    }


@app.post("/api/test/ugreen")
async def test_ugreen(request: Request):
    cfg = await request.json()
    try:
        c = UgosClient(cfg["base"])
        d = c.login(cfg["user"], cfg["cred"])
        return {"ok": True, "nas_name": d.get("nas_name"), "model": d.get("model"),
                "system_version": d.get("system_version")}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)[:200]})


@app.post("/api/test/sunpanel")
async def test_sunpanel(request: Request):
    import requests
    cfg = await request.json()
    try:
        r = requests.post(f"{cfg['base'].rstrip('/')}/openapi/v1/version",
                          headers={"token": cfg["token"], "Content-Type": "application/json"},
                          json={}, timeout=10)
        j = r.json()
        ok = j.get("code") == 0
        return {"ok": ok, "code": j.get("code"), "version": (j.get("data") or {}).get("version")}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)[:200]})


@app.get("/open/{port}")
def open_port(port: int, request: Request):
    ug = get_cfg("ugreen")
    if not ug:
        raise HTTPException(400, "ugreen not configured")
    key_expected = os.environ.get("UGNAS_BRIDGE_KEY", "")
    if key_expected and request.query_params.get("k") != key_expected:
        raise HTTPException(401, "invalid key")
    c = UgosClient(ug["base"])
    d = c.login(ug["user"], ug["cred"])
    j = c.docker_token_v2(port, d["token"], d["token_id"], d["public_key"])
    ru = ((j.get("data") or {}) if isinstance(j, dict) else {}).get("redirect_url")
    if not ru:
        raise HTTPException(502, f"dockerToken failed: {j.get('code') if isinstance(j, dict) else '?'}")
    return RedirectResponse(ru, status_code=302)
