#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""混合发现：bridge portMapping + 容器内进程扫描 + env/监听交集 + 名称兜底。

输出每个容器的端口候选与来源，用于 v2 F2 一键发现（C 主 + A 兜底）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ugreen.client import UgosClient            # noqa: E402
from discover.ugos_docker import UgosDocker      # noqa: E402
from discover.container_exec import ContainerExec  # noqa: E402

CONTAINER = "/ugre" + "en/v1/docker/container/"


def nas_listening_ports() -> set[int]:
    """通过 NAS SSH（2222 root）获取宿主监听端口；不可用时返回空集合。"""
    path = os.environ.get("UGNAS_LISTEN_FILE", "")
    if path and os.path.exists(path):
        return {int(x) for x in open(path).read().split() if x.isdigit()}
    return set()


def main():
    c = UgosClient(os.environ.get("UGOS_BASE", "https://sunjiawei1453.cn91.ug.link"))
    info = c.login("dhadmin", os.environ["DSH_SECRET_NAS_DHADMIN_PASS"])
    g = UgosDocker(c)
    ex = ContainerExec(c)
    listen = nas_listening_ports()

    containers = g.list_containers()
    out = []
    t0 = time.time()
    for it in containers:
        cid, name = it.get("containerId"), it.get("name")
        d = c.request(CONTAINER + "ShowLocalContainer", method="GET", params={"containerId": cid})["data"]
        net = ((d.get("network") or [{}])[0] or {}).get("netWorkType")
        pm = sorted({int(x["nasPort"]) for x in (d.get("portMapping") or [])
                     if str(x.get("nasPort", "")).isdigit()})
        env_ports = set()
        for e in (d.get("environmentVariable") or []):
            for k, v in ((e.get("variable", ""), e.get("price", "")), (e.get("price", ""), e.get("variable", ""))):
                if re.search(r"PORT|ADDR", str(k), re.I):
                    m = re.search(r"(\d{2,5})", str(v))
                    if m:
                        env_ports.add(int(m.group(1)))
        rec = {"name": name, "containerId": cid, "network": net, "status": it.get("status"),
               "ports": [], "source": None, "detail": {}}
        if pm:
            rec["ports"], rec["source"] = pm, "portMapping"
        else:
            scan = {}
            try:
                sr = ex.listening_ports(cid, timeout=15)
                scan = sr.get("parsed") or {}
            except Exception as e:
                rec["detail"]["scanError"] = str(e)[:120]
            ports = sorted({p for ps in scan.values() for p in ps})
            if not ports:
                uidcmd = ("U=$(awk '/^Uid:/{print $2}' /proc/1/status); "
                          "for f in /proc/net/tcp /proc/net/tcp6; do awk -v u=$U 'NR>1 && $4==\"0A\" && $8==u {print $2}' $f; done "
                          "| while read a; do p=${a##*:}; echo PORT=$((0x$p)); done | sort -u")
                try:
                    ur = ex.run(cid, uidcmd, timeout=12)
                    up = sorted({int(m) for m in re.findall(r"PORT=(\d+)", ur.get("output") or "")})
                    if up and "UID=0" not in (ur.get("output") or ""):
                        ports = up
                        rec["detail"]["uidFilter"] = True
                except Exception:
                    pass
            ports = [p for p in ports if p in listen or not listen]
            if ports:
                rec["ports"], rec["source"] = ports, "container-scan"
                rec["detail"]["scanPids"] = scan
            else:
                cand = sorted(env_ports & listen) if listen else sorted(env_ports)
                if cand:
                    rec["ports"], rec["source"] = cand, "env+listen"
                else:
                    rec["source"] = "unknown"
        out.append(rec)

    res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "nas": {k: info.get(k) for k in ("nas_name", "system_version")},
           "elapsed_s": round(time.time() - t0, 1), "containers": out}
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    p = os.path.join(ROOT, "logs", f"discover_hybrid_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    from collections import Counter
    print(json.dumps({"elapsed_s": res["elapsed_s"],
                      "sources": dict(Counter(x["source"] for x in out)),
                      "file": os.path.abspath(p)}, ensure_ascii=False))
    for x in out:
        if x["ports"]:
            print(f"  {x['name']:24s} {x['network'] or '-':7s} {x['source']:14s} {x['ports']}")


if __name__ == "__main__":
    main()
