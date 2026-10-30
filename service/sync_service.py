#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步执行服务（F3-4）

与 v1 state 语义对齐：快照 JSON = {"ts","service_base","changed":{onlyName:{new_url,old_url}}}
- plan(): 只对「勾选」的 diff 行生成操作；expired 按 dispose ∈ {skip,trash,delete}
- apply(): 先落快照再执行，逐条记录 sync_runs
- rollback(): 按快照 changed[only_name].old_url 还原
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from store.db import connect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "state", "snapshots")

ACTION_BY_STATE = {"new": "create", "update": "update", "same": "skip", "expired": "expired"}


@dataclass
class Op:
    only_name: str
    port: int
    state: str
    action: str
    title: str = ""
    icon: str = ""
    group_id: Optional[int] = None
    new_url: str = ""


@dataclass
class Plan:
    ops: List[Op]
    selected: List[str]
    service_base: str = ""

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for o in self.ops:
            if o.action == "skip":
                continue
            out[o.action] = out.get(o.action, 0) + 1
        return out

    def executable(self) -> List[Op]:
        return [o for o in self.ops if o.action != "skip"]

    def total_selected(self) -> int:
        return len(self.executable())


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class SyncService:
    def __init__(self, client, bridge_base: str = "", key: str = "", group_trash: str = "回收站"):
        self.client = client
        self.bridge_base = bridge_base.rstrip("/")
        self.key = key
        self.group_trash = group_trash

    def open_url(self, port: int) -> str:
        if not self.bridge_base:
            return ""
        q = f"?k={self.key}" if self.key else ""
        return f"{self.bridge_base}/open/{port}{q}"

    def plan(self, diff_rows, selected, dispose: Optional[Dict[str, str]] = None,
             default_dispose: str = "skip") -> Plan:
        dispose = dispose or {}
        sel = set(selected)
        ops: List[Op] = []
        for r in diff_rows:
            st = r["state"] if isinstance(r, dict) else r.state
            on = r["only_name"] if isinstance(r, dict) else r.only_name
            port = r["port"] if isinstance(r, dict) else r.port
            newp = (r.get("new") if isinstance(r, dict) else r.new) or {}
            if on not in sel or st == "same":
                continue
            act = ACTION_BY_STATE.get(st, "skip")
            if st == "expired":
                act = dispose.get(on, default_dispose)
            gid = newp.get("itemGroupID") or newp.get("item_group_id")
            ops.append(Op(on, port, st, act,
                          title=newp.get("title", ""), icon=newp.get("icon", ""),
                          group_id=int(gid) if gid else None,
                          new_url=self.open_url(port)))
        return Plan(ops, sorted(sel), self.bridge_base)

    def _snapshot(self, changes: Dict[str, dict]) -> str:
        os.makedirs(SNAP_DIR, exist_ok=True)
        p = os.path.join(SNAP_DIR, f"cards_state_{time.strftime('%Y%m%d_%H%M%S')}.json")
        data = {"ts": _iso(), "service_base": self.bridge_base, "changed": changes}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return p

    def apply(self, plan: Plan, cards: Dict[str, dict]) -> dict:
        changes: Dict[str, dict] = {}
        for op in plan.executable():
            old = (cards.get(op.only_name) or {}).get("url", "")
            changes[op.only_name] = {"new_url": op.new_url, "old_url": old}
        snap = self._snapshot(changes)
        ok = fail = 0
        results = []
        for op in plan.executable():
            try:
                if op.action == "create":
                    self.client.create_item(op.only_name, op.title, op.new_url, icon_url=op.icon,
                                            item_group_id=op.group_id)
                elif op.action == "update":
                    self.client.update_item(op.only_name, title=op.title or None,
                                            iconUrl=op.icon or None, url=op.new_url or None,
                                            itemGroupID=op.group_id)
                elif op.action == "trash":
                    g = self.client.create_group(self.group_trash)
                    gid = g.get("itemGroupID") or g.get("id")
                    self.client.update_item(op.only_name, itemGroupID=gid)
                elif op.action == "delete":
                    fn = getattr(self.client, "delete_item", None)
                    if not fn:
                        raise RuntimeError("delete unavailable: OpenAPI has no item delete (use panel admin API)")
                    fn(op.only_name)
                ok += 1
                results.append({"only_name": op.only_name, "action": op.action, "ok": True})
            except Exception as e:  # noqa: BLE001
                fail += 1
                results.append({"only_name": op.only_name, "action": op.action, "ok": False, "error": str(e)[:160]})
        self._record(plan, ok, fail, snap)
        return {"ok": ok, "fail": fail, "snapshot": snap, "results": results}

    def _record(self, plan: Plan, ok: int, fail: int, snap: str) -> None:
        c = connect()
        try:
            with c:
                c.execute("INSERT INTO sync_runs(ts,mode,total,ok,fail,snapshot_path,detail) VALUES(?,?,?,?,?,?,?)",
                          (int(time.time()), "apply", plan.total_selected(), ok, fail, snap,
                           json.dumps(plan.counts(), ensure_ascii=False)))
        finally:
            c.close()

    def rollback(self, snapshot_path: str) -> dict:
        data = json.load(open(snapshot_path, encoding="utf-8"))
        ok = fail = 0
        for on, rec in (data.get("changed") or {}).items():
            try:
                self.client.update_item(on, url=rec.get("old_url"))
                ok += 1
            except Exception:
                fail += 1
        return {"ok": ok, "fail": fail}
