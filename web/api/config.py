#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置路由：加密落盘 + 脱敏回显 + 字段级合并。

2026-10-31 QA 修复：
- P1-3：put_cfg 改为「非空字段覆盖、空字符串=不修改」的合并语义，避免整字典覆盖清空未重填的凭据；
- P2-1：支持 {"__clear__": true} 删除整项配置（用于移除 Sun-Panel 管理员账号、解除删除锁定）。
"""
from __future__ import annotations

import base64
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.crypto import decrypt, encrypt
from store.db import audit, connect

router = APIRouter(prefix="/api/config", tags=["config"])
_FIELDS = {
    "ugreen": ("base", "user", "cred"),
    "sunpanel": ("base", "token"),
    "sunpanel_admin": ("user", "cred"),
    "health": ("host",),
}


def put_cfg(k: str, value: dict) -> None:
    """字段级合并：空值不覆盖已存值；__clear__ 删除整项。"""
    value = value or {}
    if value.get("__clear__"):
        delete_cfg(k)
        return
    cur = get_cfg(k) or {}
    for f, v in value.items():
        if f.startswith("__"):
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue  # 留空 = 不修改
        cur[f] = v.strip() if isinstance(v, str) else v
    salt = os.urandom(16)
    enc = encrypt(json.dumps(cur, ensure_ascii=False), salt)
    c = connect()
    try:
        with c:
            c.execute("INSERT INTO config(k,enc,salt,ts) VALUES(?,?,?,?) "
                      "ON CONFLICT(k) DO UPDATE SET enc=excluded.enc, salt=excluded.salt, ts=excluded.ts",
                      (k, enc, base64.b64encode(salt).decode(), int(time.time())))
    finally:
        c.close()


def delete_cfg(k: str) -> None:
    c = connect()
    try:
        with c:
            c.execute("DELETE FROM config WHERE k=?", (k,))
    finally:
        c.close()


def get_cfg(k: str):
    c = connect()
    try:
        row = c.execute("SELECT enc,salt FROM config WHERE k=?", (k,)).fetchone()
    finally:
        c.close()
    if not row:
        return None
    return json.loads(decrypt(row["enc"], base64.b64decode(row["salt"])))


@router.get("")
def get_all():
    out = {}
    for k, fields in _FIELDS.items():
        v = get_cfg(k) or {}
        out[k] = {f: ("***" if f in ("cred", "token") and v.get(f) else v.get(f) or "") for f in fields}
    return out


@router.post("/{kind}")
async def set_cfg(kind: str, request: Request):
    if kind not in _FIELDS:
        return JSONResponse({"success": False, "error": "unknown config"}, status_code=400)
    body = await request.json()
    put_cfg(kind, body or {})
    audit("config.set", kind)
    return {"success": True}


@router.delete("/{kind}")
def clear_cfg(kind: str):
    """删除整项配置（P2-1：移除管理员账号/清空某项配置）。"""
    if kind not in _FIELDS:
        return JSONResponse({"success": False, "error": "unknown config"}, status_code=400)
    delete_cfg(kind)
    audit("config.clear", kind)
    return {"success": True}
