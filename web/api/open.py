#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免登录跳转：/open/{port}?k=<KEY> → dockerToken → 302。"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ugreen.client import UgosClient
from web.api.config import get_cfg

router = APIRouter(tags=["open"])


@router.get("/open/{port}")
def open_port(port: int, request: Request):
    ug = get_cfg("ugreen")
    if not ug:
        raise HTTPException(400, "ugreen not configured")
    key_expected = os.environ.get("UGNAS_BRIDGE_KEY", "")
    if key_expected and request.query_params.get("k") != key_expected:
        raise HTTPException(401, "invalid key")
    try:
        c = UgosClient(ug["base"])
        d = c.login(ug["user"], ug["cred"])
        j = c.docker_token_v2(port, d["token"], d["token_id"], d["public_key"])
        ru = ((j.get("data") or {}) if isinstance(j, dict) else {}).get("redirect_url")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"bridge upstream failed: {str(e)[:120]}")
    if not ru:
        raise HTTPException(502, "dockerToken failed")
    return RedirectResponse(ru, status_code=302)
