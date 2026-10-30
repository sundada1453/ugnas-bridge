#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置路由：加密落盘 + 脱敏回显。"""
from __future__ import annotations

import base64
import json
import os
import time

from fastapi import APIRouter, Request

from core.crypto import decrypt, encrypt
from store.db import audit, connect

router = APIRouter(prefix="/api/config", tags=["config"])
_FIELDS = {
    "ugreen": ("base", "user", "cred"),
    "sunpanel": ("base", "token"),
}


def put_cfg(k: str, value: dict) -> None:
    salt = os.urandom(16)
    enc = encrypt(json.dumps(value, ensure_ascii=False), salt)
    c = connect()
    try:
        with c:
            c.execute("INSERT INTO config(k,enc,salt,ts) VALUES(?,?,?,?) "
                      "ON CONFLICT(k) DO UPDATE SET enc=excluded.enc, salt=excluded.salt, ts=excluded.ts",
                      (k, enc, base64.b64encode(salt).decode(), int(time.time())))
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
        out[k] = {f: ("***" if f in ("cred", "token") and v.get(f) else v.get(f)) for f in fields}
    return out


@router.post("/{kind}")
async def set_cfg(kind: str, request: Request):
    if kind not in _FIELDS:
        return {"ok": False, "error": "unknown config"}
    body = await request.json()
    put_cfg(kind, body or {})
    audit("config.set", kind)
    return {"ok": True}
