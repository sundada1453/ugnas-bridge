#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发现编排服务（F2-1）：Docker API + 容器扫描 + 合并 + 入库。"""
from __future__ import annotations

import json
import time
from typing import List, Optional

from store.db import connect


class DiscoverService:
    def __init__(self, docker, execu=None, listen_ports: Optional[set] = None):
        self.docker = docker
        self.execu = execu
        self.listen = set(listen_ports or [])

    def collect(self) -> List[dict]:
        containers = self.docker.discover(with_detail=True)
        out = []
        for c in containers:
            ports = sorted({p["nasPort"] for p in c.get("ports", []) if p.get("nasPort")})
            source = "portMapping" if ports else None
            if not ports and self.execu and c.get("containerId"):
                try:
                    r = self.execu.listening_ports(c["containerId"])
                    parsed = r.get("parsed") or {}
                    got = sorted({p for ps in parsed.values() for p in ps})
                    if self.listen:
                        got = [p for p in got if p in self.listen]
                    if got:
                        ports, source = got, "container-scan"
                except Exception:
                    pass
            out.append({
                "container_id": c.get("containerId", ""),
                "name": c.get("name", ""),
                "net": (c.get("networkMode") or ""),
                "ports": ports,
                "source": source or "unknown",
                "state": c.get("status", ""),
            })
        return out

    def persist(self, rows: List[dict]) -> int:
        now = int(time.time())
        c = connect()
        n = 0
        try:
            with c:
                for r in rows:
                    c.execute(
                        "INSERT INTO apps(container_id,name,net,ports,source,state,discovered_at) "
                        "VALUES(?,?,?,?,?,?,?) "
                        "ON CONFLICT(container_id,name) DO UPDATE SET net=excluded.net, ports=excluded.ports, "
                        "source=excluded.source, state=excluded.state, discovered_at=excluded.discovered_at",
                        (r["container_id"], r["name"], r["net"], json.dumps(r["ports"]),
                         r["source"], r["state"], now))
                    n += 1
        finally:
            c.close()
        return n

    def run(self) -> dict:
        rows = self.collect()
        n = self.persist(rows)
        from collections import Counter
        return {"count": n, "sources": dict(Counter(r["source"] for r in rows)),
                "rows": rows, "ts": int(time.time())}
