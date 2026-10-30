#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步执行服务（F3-4）

- plan(): 只对「勾选」的 diff 行生成操作；expired 按 dispose ∈ {skip,trash,delete}
- apply(): 执行前落 state 快照（可整批回滚），逐条执行并记录 sync_runs
- rollback(): 从快照恢复卡片
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
    payload: Dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    ops: List[Op]
    selected: List[str]

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


class SyncService:
    def __init__(self, client, group_trash: str = "回收站"):
        self.client = client
        self.group_trash = group_trash

    def plan(self, diff_rows, selected, dispose: Optional[Dict[str, str]] = None,
             default_dispose: str = "skip") -> Plan:
        dispose = dispose or {}
        sel = set(selected)
        ops: List[Op] = []
        for r in diff_rows:
            st = r["state"] if isinstance(r, dict) else r.state
            on = r["only_name"] if isinstance(r, dict) else r.only_name
            port = r["port"] if isinstance(r, dict) else r.port
            payload = (r.get("new") if isinstance(r, dict) else r.new) or {}
            if on not in sel or st == "same":
                continue
            act = ACTION_BY_STATE.get(st, "skip")
            if st == "expired":
                act = dispose.get(on, default_dispose)
            ops.append(Op(on, port, st, act, payload))
        return Plan(ops, sorted(sel))

    def _snapshot(self, cards: List[dict]) -> str:
        os.makedirs(SNAP_DIR, exist_ok=True)
        p = os.path.join(SNAP_DIR, f"cards_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "cards": cards}, f, ensure_ascii=False, indent=2)
        return p

    def apply(self, plan: Plan, snapshot_cards: List[dict]) -> dict:
        snap = self._snapshot(snapshot_cards)
        ok = fail = 0
        results = []
        for op in plan.executable():
            try:
                if op.action == "create":
                    self.client.add_item(onlyName=op.only_name, title=op.payload.get("title", ""),
                                         icon=op.payload.get("icon", ""))
                elif op.action == "update":
                    card = self.client.get_card(op.only_name) or {}
                    if card.get("id"):
                        self.client.update_item(card["id"], title=op.payload.get("title"),
                                                icon=op.payload.get("icon"))
                elif op.action == "trash":
                    card = self.client.get_card(op.only_name) or {}
                    if card.get("id"):
                        g = self.client.create_group(self.group_trash)
                        self.client.update_item(card["id"], itemGroupID=g.get("id"))
                elif op.action == "delete":
                    card = self.client.get_card(op.only_name) or {}
                    if card.get("id") and hasattr(self.client, "delete_item"):
                        self.client.delete_item(card["id"])
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
        for c in data.get("cards", []):
            try:
                if c.get("id"):
                    self.client.update_item(c["id"], title=c.get("title"), icon=c.get("icon"),
                                            itemGroupID=c.get("group_id") or c.get("itemGroupID"),
                                            url=c.get("url"))
                ok += 1
            except Exception:
                fail += 1
        return {"ok": ok, "fail": fail}
