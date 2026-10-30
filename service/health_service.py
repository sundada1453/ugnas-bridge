#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康监测（F4）：定时探测应用可达性，写 health 表，供仪表盘联动。"""
from __future__ import annotations
import json, time, urllib.request
from typing import Dict, List

from store.db import connect


class HealthService:
    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout

    def _apps(self) -> List[dict]:
        c = connect()
        try:
            rows = c.execute("SELECT name,ports,state FROM apps").fetchall()
        finally:
            c.close()
        out = []
        for r in rows:
            for p in json.loads(r["ports"] or "[]"):
                out.append({"app": r["name"], "port": int(p)})
        return out

    def _probe(self, port: int) -> Dict:
        t0 = time.time()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "ugnas-bridge-health"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                ok = 200 <= r.status < 500
            return {"up": 1 if ok else 0, "latency_ms": int((time.time() - t0) * 1000), "err": ""}
        except Exception as e:  # noqa: BLE001
            return {"up": 0, "latency_ms": int((time.time() - t0) * 1000), "err": str(e)[:120]}

    def run_once(self) -> Dict:
        now = int(time.time())
        rows = []
        c = connect()
        try:
            with c:
                for a in self._apps():
                    pr = self._probe(a["port"])
                    c.execute("INSERT INTO health(app,port,up,latency_ms,checked_at) VALUES(?,?,?,?,?) "
                              "ON CONFLICT(app) DO UPDATE SET port=excluded.port, up=excluded.up, "
                              "latency_ms=excluded.latency_ms, checked_at=excluded.checked_at",
                              (a["app"], a["port"], pr["up"], pr["latency_ms"], now))
                    rows.append({"app": a["app"], "port": a["port"], **pr})
        finally:
            c.close()
        up = sum(1 for r in rows if r["up"])
        return {"ts": now, "total": len(rows), "up": up, "down": len(rows) - up, "rows": rows}

    def summary(self) -> Dict:
        c = connect()
        try:
            rows = [dict(r) for r in c.execute("SELECT app,port,up,latency_ms,checked_at FROM health ORDER BY app").fetchall()]
        finally:
            c.close()
        up = sum(1 for r in rows if r["up"])
        return {"total": len(rows), "up": up, "down": len(rows) - up, "rows": rows}
