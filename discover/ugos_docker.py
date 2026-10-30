#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UGOS Docker 发现（只读）

依据 metaneutrons/ugos-cli docs/api-docker.md：
- ContainerListV2: POST {base}/ugreen/v1/docker/container/ContainerListV2  body {pageNum,pageSize}
- GetContainerById: GET  .../GetContainerById?containerId=<id>  → ContainerDetail（含 portMapping）
只做读操作：列表 / 详情。绝不 Start/Stop/Remove。
"""
from __future__ import annotations

from typing import Any, Dict, List

from ugreen.client import UgosClient, UgosError

V1 = "/ugre" + "en/v1/"
CONTAINER = V1 + "docker/container/"


class UgosDocker:
    def __init__(self, client: UgosClient):
        self.c = client

    def list_containers(self, page_size: int = 100, max_pages: int = 20) -> List[dict]:
        out: List[dict] = []
        page = 1
        while page <= max_pages:
            j = self.c.request(CONTAINER + "ContainerListV2", method="POST",
                               body={"pageNum": page, "pageSize": page_size})
            data = j.get("data") or {}
            batch = data.get("result") or []
            out.extend(batch)
            total = int(data.get("total") or data.get("originalTotal") or 0)
            if not batch or len(out) >= total:
                break
            page += 1
        return out

    def container_detail(self, container_id: str) -> dict:
        j = self.c.request(CONTAINER + "GetContainerById", method="GET",
                           params={"containerId": container_id})
        d = j.get("data")
        if isinstance(d, dict) and "result" in d and isinstance(d["result"], dict):
            return d["result"]
        return d if isinstance(d, dict) else {}

    def discover(self, with_detail: bool = True) -> List[dict]:
        items = self.list_containers()
        out = []
        for it in items:
            rec = {
                "name": it.get("name") or it.get("containerName") or "",
                "containerId": it.get("containerId") or "",
                "image": (it.get("imageName") or "") + ((":" + it["version"]) if it.get("version") else ""),
                "status": it.get("status") or "",
                "project": it.get("projectName") or "",
                "application": it.get("application") or "",
                "ports": [],
            }
            if with_detail and rec["containerId"]:
                try:
                    d = self.container_detail(rec["containerId"])
                    for pm in (d.get("portMapping") or []):
                        rec["ports"].append({
                            "nasPort": int(pm.get("nasPort") or 0),
                            "containerPort": int(pm.get("containerPort") or 0),
                            "type": pm.get("portType") or "tcp",
                        })
                    rec["networkMode"] = d.get("networkMode")
                except UgosError as e:
                    rec["detailError"] = f"{e.code}:{e.msg}"
            out.append(rec)
        return out


def port_index(containers: List[dict]) -> Dict[int, dict]:
    """nasPort -> {name, containerPort, type}"""
    idx: Dict[int, dict] = {}
    for c in containers:
        for p in c.get("ports", []):
            if p["nasPort"]:
                idx.setdefault(p["nasPort"], {"name": c["name"], "containerPort": p["containerPort"],
                                              "type": p["type"], "status": c["status"]})
    return idx
