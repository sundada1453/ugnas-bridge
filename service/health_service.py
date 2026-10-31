#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康监测（F4）：定时探测应用可达性，写 health 表，供仪表盘联动。

2026-10-31 QA 修复（P1-4）：
- 探测目标不再写死 127.0.0.1（云端部署必然全红），改为配置项 health.host（NAS 内网 IP/Tailscale IP）；
- 未配置探测地址时明确返回「未探测」，不再伪造全绿；
- 改用 TCP connect 判断端口可达（应用清单是按端口管理的，HTTP GET 对 SSH/VNC 类端口不适用）；
- health 表主键改为 (app, port)，修复「run 37 项、detail 27 项」的口径不一致。
"""
from __future__ import annotations

import json
import os
import socket
import time
from typing import Dict, List, Optional

from store.db import connect


class HealthService:
    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout

    def _probe_host(self) -> str:
        try:
            from web.api.config import get_cfg
            cfg = get_cfg("health") or {}
            host = (cfg.get("host") or "").strip()
            if not host:
                # 未单独配置时，默认沿用 Sun-Panel 所在主机（面板与 NAS 应用同机，常见即内网/Tailscale IP）
                from urllib.parse import urlparse
                sp = get_cfg("sunpanel") or {}
                host = (urlparse(sp.get("base") or "").hostname or "").strip()
        except Exception:  # noqa: BLE001
            host = ""
        return host or os.environ.get("UGNAS_HEALTH_HOST", "").strip()

    def _apps(self) -> List[dict]:
        c = connect()
        try:
            rows = c.execute("SELECT name,ports,state FROM apps").fetchall()
        finally:
            c.close()
        out = []
        for r in rows:
            ports = json.loads(r["ports"] or "[]")
            for p in ports:
                out.append({"app": r["name"], "port": int(p)})
        return out

    def _probe(self, host: str, port: int) -> Dict:
        t0 = time.time()
        try:
            with socket.create_connection((host, int(port)), timeout=self.timeout):
                pass
            return {"up": 1, "latency_ms": int((time.time() - t0) * 1000), "err": ""}
        except Exception as e:  # noqa: BLE001
            return {"up": 0, "latency_ms": int((time.time() - t0) * 1000), "err": str(e)[:120]}

    def run_once(self) -> Dict:
        host = self._probe_host()
        if not host:
            return {"ts": int(time.time()), "configured": False, "host": "",
                    "total": 0, "up": 0, "down": 0, "rows": [],
                    "error": "未配置健康探测地址：请到设置页填写 NAS 内网地址（健康探测用）"}
        now = int(time.time())
        rows = []
        c = connect()
        try:
            with c:
                c.execute("DELETE FROM health")
                for a in self._apps():
                    pr = self._probe(host, a["port"])
                    c.execute("INSERT INTO health(app,port,up,latency_ms,checked_at) VALUES(?,?,?,?,?)",
                              (a["app"], a["port"], pr["up"], pr["latency_ms"], now))
                    rows.append({"app": a["app"], "port": a["port"], **pr})
        finally:
            c.close()
        up = sum(1 for r in rows if r["up"])
        return {"ts": now, "configured": True, "host": host, "total": len(rows),
                "up": up, "down": len(rows) - up, "rows": rows}

    def summary(self) -> Dict:
        host = self._probe_host()
        c = connect()
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT app,port,up,latency_ms,checked_at FROM health ORDER BY app,port").fetchall()]
        finally:
            c.close()
        up = sum(1 for r in rows if r["up"])
        out = {"configured": bool(host), "host": host, "total": len(rows),
               "up": up, "down": len(rows) - up, "rows": rows}
        if not host:
            out["error"] = "未配置健康探测地址：请到设置页填写 NAS 内网地址（健康探测用）"
        elif not rows:
            out["error"] = "尚未探测：点击「立即探测」或等待定时任务"
        return out
