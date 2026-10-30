#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理页认证：口令哈希（PBKDF2-SHA256）+ 服务端会话（HttpOnly Cookie）。"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time

from store.db import connect

ITER = 200_000
COOKIE = "dsb_session"
SESSION_TTL = 7 * 86400


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER, 32)
    return f"pbkdf2${ITER}${_b64(salt)}${_b64(dk)}"


def verify_pw(pw: str, stored: str) -> bool:
    try:
        algo, it, salt_b, hash_b = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt_b), int(it), 32)
        return secrets.compare_digest(dk, base64.b64decode(hash_b))
    except Exception:
        return False


def admin_exists() -> bool:
    c = connect()
    try:
        return c.execute("SELECT 1 FROM admin WHERE id=1").fetchone() is not None
    finally:
        c.close()


def set_admin(pw: str) -> None:
    c = connect()
    try:
        with c:
            c.execute("INSERT INTO admin(id,pw,created_at) VALUES(1,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET pw=excluded.pw, created_at=excluded.created_at",
                      (hash_pw(pw), int(time.time())))
    finally:
        c.close()


def verify_admin(pw: str) -> bool:
    c = connect()
    try:
        row = c.execute("SELECT pw FROM admin WHERE id=1").fetchone()
        return bool(row) and verify_pw(pw, row["pw"])
    finally:
        c.close()


def create_session() -> str:
    tok = secrets.token_urlsafe(32)
    now = int(time.time())
    c = connect()
    try:
        with c:
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            c.execute("INSERT INTO sessions(token,created_at,expires_at) VALUES(?,?,?)",
                      (tok, now, now + SESSION_TTL))
    finally:
        c.close()
    return tok


def session_valid(tok: str) -> bool:
    if not tok:
        return False
    c = connect()
    try:
        row = c.execute("SELECT expires_at FROM sessions WHERE token=?", (tok,)).fetchone()
        return bool(row) and int(row["expires_at"]) > int(time.time())
    finally:
        c.close()


def revoke_session(tok: str) -> None:
    if not tok:
        return
    c = connect()
    try:
        with c:
            c.execute("DELETE FROM sessions WHERE token=?", (tok,))
    finally:
        c.close()
