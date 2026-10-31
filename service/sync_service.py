#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步执行服务（F3-4）

与 v1 state 语义对齐：快照 JSON = {"ts","service_base","changed":{onlyName:{new_url,old_url,...}}}
- plan(): 只对「勾选」的 diff 行生成操作；expired 按 dispose ∈ {skip,trash,delete}
- apply(): 先落快照再执行，逐条记录 sync_runs
- rollback(): 按快照还原；delete 走重建，trash 还原分组

2026-10-31 QA 修复：
- P0-1：delete 分支不再调用不存在的 SunPanelClient.delete_item，改走 PanelInternal.delete_items_by_names()（批量）；
- P2-6：快照记录 old_title/old_group_id/old_icon/old_lan_url/action，回滚还原完整状态（delete 重建卡片）。
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


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class SyncService:
    def __init__(self, client, bridge_base: str = "", key: str = "", group_trash: str = "回收站", panel=None):
        """client: SunPanelClient（官方 OpenAPI）；panel: PanelInternal（管理员内部接口，删除用）。"""
        self.client = client
        self.panel = panel
        self.bridge_base = bridge_base.rstrip("/")
        self.key = key
        self.group_trash = group_trash

    def open_url(self, port: int) -> str:
        if not self.bridge_base:
            return ""
        q = f"?k={self.key}" if self.key else ""
        return f"{self.bridge_base}/open/{port}{q}"

    # ---------- 计划 ----------
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
                          group_id=_as_int(gid),
                          new_url=self.open_url(port)))
        return Plan(ops, sorted(sel), self.bridge_base)

    # ---------- 快照（v1 兼容 + 扩展字段） ----------
    def _snapshot(self, changes: Dict[str, dict]) -> str:
        os.makedirs(SNAP_DIR, exist_ok=True)
        p = os.path.join(SNAP_DIR, f"cards_state_{time.strftime('%Y%m%d_%H%M%S')}.json")
        data = {"ts": _iso(), "service_base": self.bridge_base, "changed": changes}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return p

    # ---------- 执行 ----------
    def apply(self, plan: Plan, cards: Dict[str, dict]) -> dict:
        """cards: only_name -> {url,title,icon,group_id,lan_url}（当前卡片，用于生成快照）。"""
        changes: Dict[str, dict] = {}
        for op in plan.executable():
            old = cards.get(op.only_name) or {}
            changes[op.only_name] = {
                "action": op.action,
                "new_url": op.new_url,
                "old_url": old.get("url", ""),
                "old_title": old.get("title", ""),
                "old_icon": old.get("icon", ""),
                "old_group_id": old.get("group_id", ""),
                "old_lan_url": old.get("lan_url", ""),
            }
        snap = self._snapshot(changes)

        # P0-1：delete 走管理员内部接口，先批量定位 id 再一次性删除
        delete_ops = [o for o in plan.executable() if o.action == "delete"]
        delete_result: Dict[str, tuple] = {}
        if delete_ops:
            try:
                if not self.panel:
                    raise RuntimeError("删除需在设置中配置 Sun-Panel 管理员账号（默认仅支持移回收站）")
                resp = self.panel.delete_items_by_names([o.only_name for o in delete_ops])
                deleted = set(resp.get("deleted") or [])
                missing = set(resp.get("missing") or [])
                for op in delete_ops:
                    if op.only_name in deleted:
                        delete_result[op.only_name] = (True, "")
                    elif op.only_name in missing:
                        delete_result[op.only_name] = (False, "卡片不存在（可能已被删除）")
                    else:
                        delete_result[op.only_name] = (False, "面板未返回删除结果")
            except Exception as e:  # noqa: BLE001
                msg = str(e)[:160]
                for op in delete_ops:
                    delete_result[op.only_name] = (False, msg)

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
                    good, err = delete_result.get(op.only_name, (False, "delete skipped"))
                    if not good:
                        raise RuntimeError(err)
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

    # ---------- 回滚 ----------
    def rollback(self, snapshot_path: str) -> dict:
        data = json.load(open(snapshot_path, encoding="utf-8"))
        ok = fail = 0
        errors = []
        for on, rec in (data.get("changed") or {}).items():
            try:
                action = rec.get("action") or "update"
                old_title = rec.get("old_title") or ""
                old_url = rec.get("old_url") or ""
                old_group = _as_int(rec.get("old_group_id"))
                if action == "delete":
                    # 删除操作不可逆，用快照重建卡片
                    self.client.create_item(on, old_title or on, old_url,
                                            icon_url=rec.get("old_icon") or "",
                                            item_group_id=old_group)
                else:
                    fields = {"url": old_url}
                    if old_title:
                        fields["title"] = old_title
                    if old_group is not None:
                        fields["itemGroupID"] = old_group
                    if rec.get("old_lan_url"):
                        fields["lanUrl"] = rec["old_lan_url"]
                    self.client.update_item(on, **fields)
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                errors.append({"only_name": on, "error": str(e)[:160]})
        return {"ok": ok, "fail": fail, "errors": errors}
