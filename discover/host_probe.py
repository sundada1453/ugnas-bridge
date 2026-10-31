#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宿主 TCP 监听端口探测（四态判定第二层兜底）。

背景：UGOS Docker API 的 portMapping 对 host 网络容器为空，容器内扫描也可能漏；
但 NAS 宿主 netns 能看到全部 LISTEN 端口。采用 tailscale 容器（netns=host）作为
只读跳板，读取 /proc/net/tcp{,6} 的 LISTEN 项；仅读，不改变容器状态。

结果缓存 120s，避免四态预览每次拖慢；失败返回 ok=False，不阻断已有发现结果。
2026-10-31 用户报障：sub2api 8080 等 host 网络应用被误判 expired，本层用于阻止误判。
"""
from __future__ import annotations

import re
import time
from typing import List

from store.db import connect

_CACHE = {"ts": 0.0, "result": None}
_TTL = 120.0


def parse_listen_ports(text: str):
    """解析 /proc/net/tcp{,6} 输出中的 LISTEN 十六进制端口。"""
    ports = set()
    for line in (text or "").splitlines():
        m = re.search(r":([0-9A-Fa-f]{1,4})$", line.strip())
        if m:
            p = int(m.group(1), 16)
            if 1 <= p <= 65535:
                ports.add(p)
    return sorted(ports)


def _container_id(name: str) -> str:
    c = connect()
    try:
        row = c.execute("SELECT container_id FROM apps WHERE name=? AND container_id<>'' LIMIT 1", (name,)).fetchone()
        return row["container_id"] if row else ""
    finally:
        c.close()


def _candidates() -> List[str]:
    # tailscale 容器 netns=host（CEO 已验证）；shell-now 作为同类 host 容器兜底
    return [n for n in ("tailscale", "shell-now") if _container_id(n)]


def host_listening_ports(force: bool = False, ttl: float = _TTL) -> dict:
    """返回 {"ok":bool,"ports":[...],"container":name,"error":...}。"""
    now = time.time()
    if not force and _CACHE["result"] is not None and now - _CACHE["ts"] < ttl:
        return _CACHE["result"]

    result = {"ok": False, "ports": [], "container": "", "error": ""}
    try:
        from web.api.config import get_cfg
        from ugreen.client import UgosClient
        from discover.container_exec import ContainerExec

        ug = get_cfg("ugreen") or {}
        if not ug.get("base") or not ug.get("user") or not ug.get("cred"):
            result["error"] = "ugreen not configured"
        else:
            cli = UgosClient(ug["base"])
            cli.login(ug["user"], ug["cred"])
            ex = ContainerExec(cli)
            # /proc/net/tcp 的 LISTEN(0A) 项：地址:十六进制端口；宿主 netns 中即宿主监听端口
            cmd = "for f in /proc/net/tcp /proc/net/tcp6; do awk 'NR>1 && $4==\"0A\" {print $2}' $f 2>/dev/null; done"
            for name in ("tailscale", "shell-now"):
                cid = _container_id(name)
                if not cid:
                    continue
                r = ex.run(cid, cmd, timeout=15)
                if not r.get("ok"):
                    result["error"] = f"{name}: {r.get('error', 'exec failed')}"
                    continue
                ports = parse_listen_ports(r.get("output") or "")
                if ports:
                    result.update({"ok": True, "ports": ports, "container": name, "error": ""})
                    break
                result["error"] = f"{name}: no LISTEN ports parsed"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {str(e)[:160]}"

    _CACHE["ts"] = now
    _CACHE["result"] = result
    return result
