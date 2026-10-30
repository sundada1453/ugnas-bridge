#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sun-Panel 卡片批量改写脚本（OpenAPI v1）

把「绿联NAS」分组里各容器卡片的 url（公网入口）改成
    http://<SERVICE_HOST>:<SERVICE_PORT>/open/<port>?k=<KEY>
lanUrl 保持不变。支持 --dry-run / --apply / --rollback。

用法：
  # 1) 先看改动（默认 dry-run，不写任何东西）
  python3 update_cards.py --map cards.json --service-base http://<SERVICE>:8770 --service-key <KEY> --dry-run

  # 2) 真正写入，并落 state 文件（回滚依据）
  python3 update_cards.py --map cards.json --service-base http://<SERVICE>:8770 --service-key <KEY> --apply

  # 3) 回滚（按 state 还原 old url）
  python3 update_cards.py --rollback

cards.json 形如：
[{"onlyName":"ug-openlist","port":5244},{"onlyName":"ug-emby","port":8097}]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

DEFAULT_BASE = "http://<SUNPANEL>:13002/openapi/v1"
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state", "cards_state.json")


class OpenAPI:
    def __init__(self, base: str, token: str, timeout: int = 15):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def call(self, path: str, payload: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        r = requests.post(url, json=payload or {}, headers={"token": self.token}, timeout=self.timeout)
        try:
            return r.json()
        except Exception:
            return {"code": -1, "msg": f"non-json http={r.status_code}", "raw": r.text[:200]}

    def version(self):
        return self.call("/version")

    def group_list(self):
        return self.call("/itemGroup/getList")

    def item_info(self, only_name: str):
        return self.call("/item/getInfoByOnlyName", {"onlyName": only_name})

    def batch_update(self, items: list[dict]) -> dict:
        return self.call("/item/batchUpdate", {"items": items})

    def item_update(self, only_name: str, url: str) -> dict:
        # 兼容 1.8.x（无 batchUpdate，仅单条 update）
        return self.call("/item/update", {"onlyName": only_name, "url": url})


def die(msg: str, code: int = 1):
    print(f"ERROR {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_map(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "cards" in data:
        data = data["cards"]
    out = []
    for it in data:
        if "onlyName" not in it or "port" not in it:
            die(f"map entry missing onlyName/port: {it}")
        out.append({"onlyName": it["onlyName"], "port": int(it["port"])})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--token", default=os.environ.get("SUNPANEL_OPENAPI_TOKEN", ""),
                    help="OpenAPI token；传 - 从 stdin 读，避免进 shell history")
    ap.add_argument("--group-only-name", default="ugreen-nas")
    ap.add_argument("--map", default="")
    ap.add_argument("--service-base", default="http://<SERVICE>:8770")
    ap.add_argument("--service-key", default=os.environ.get("UGNAS_BRIDGE_KEY", ""),
                    help="服务访问口令（默认取环境变量 UGNAS_BRIDGE_KEY）")
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--dry-run", action="store_true", default=False)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args()

    if a.token == "-":
        a.token = sys.stdin.readline().strip()
    if not a.token:
        die("缺少 OpenAPI token（--token - 从 stdin 读，或环境变量 SUNPANEL_OPENAPI_TOKEN）")
    api = OpenAPI(a.base, a.token)

    ver = api.version()
    print(f"version: {json.dumps(ver, ensure_ascii=False)[:200]}")
    if ver.get("code") != 0:
        die(f"OpenAPI 不可用：{ver.get('code')} {ver.get('msg')}（1000=token 过期）")

    grp = api.group_list()
    if grp.get("code") != 0:
        die(f"itemGroup/getList 失败：{grp}")
    groups = grp.get("data", {}).get("list", [])
    gid = next((g for g in groups if g.get("onlyName") == a.group_only_name), None)
    print(f"group '{a.group_only_name}': {json.dumps(gid, ensure_ascii=False)}")

    # ---------- 回滚 ----------
    if a.rollback:
        if not os.path.exists(a.state):
            die(f"state 不存在：{a.state}")
        st = json.load(open(a.state, encoding="utf-8"))
        items = [{"onlyName": k, "url": v["old_url"]} for k, v in st.get("changed", {}).items()]
        if not items:
            print("没有可回滚项")
            return 0
        print(f"回滚 {len(items)} 条…")
        res = api.batch_update(items)
        okn = 0
        if res.get("code") == 0:
            okn = len(items) - len((res.get("data") or {}).get("failItems", []))
        else:
            print("batchUpdate 不可用，逐条回滚")
            for it in items:
                r = api.item_update(it["onlyName"], it["url"])
                print(f"  item/update {it['onlyName']} -> code={r.get('code')}")
                if r.get("code") == 0: okn += 1
        if okn == len(items):
            os.rename(a.state, a.state + f".rolledback.{int(time.time())}")
            print(f"回滚完成 {okn}/{len(items)}，state 已归档")
            return 0
        print(f"回滚部分失败 {okn}/{len(items)}")
        return 1

    # ---------- 生成改动 ----------
    if not a.map:
        die("需要 --map cards.json")
    cards = load_map(a.map)
    plan, report = [], []
    for c in cards:
        info = api.item_info(c["onlyName"])
        if info.get("code") != 0:
            report.append({**c, "status": "not_found", "msg": info.get("msg")})
            continue
        d = info.get("data", {})
        new_url = f"{a.service_base.rstrip('/')}/open/{c['port']}"
        if a.service_key:
            new_url += f"?k={a.service_key}"
        plan.append({"onlyName": c["onlyName"], "url": new_url})
        report.append({"onlyName": c["onlyName"], "title": d.get("title"),
                       "old_url": d.get("url"), "new_url": new_url,
                       "lanUrl_keep": d.get("lanUrl"), "status": "ok"})

    print("\n=== 变更计划 ===")
    for r in report:
        print(json.dumps(r, ensure_ascii=False))

    if a.dry_run or not a.apply:
        print(f"\n[dry-run] 将修改 {len(plan)} 条；未写入。加 --apply 落盘。")
        return 0

    # ---------- 执行 ----------
    ok, fail = [], []
    mode = "batch"
    for i in range(0, len(plan), 20):
        chunk = plan[i:i + 20]
        res = api.batch_update(chunk) if mode == "batch" else {"code": -1}
        if mode == "batch":
            print("batchUpdate ->", json.dumps(res, ensure_ascii=False)[:300])
        if res.get("code") == 0:
            d = res.get("data", {})
            failed_names = {x["onlyName"] for x in d.get("failItems", [])}
            for it in chunk:
                (fail if it["onlyName"] in failed_names else ok).append(it)
        else:
            if mode == "batch":
                print("batchUpdate 不可用（面板 < 2.0.0-dev-13），降级为逐条 item/update")
                mode = "single"
            for it in chunk:
                r = api.item_update(it["onlyName"], it["url"])
                print(f"  item/update {it['onlyName']} -> code={r.get('code')} msg={r.get('msg')}")
                (ok if r.get("code") == 0 else fail).append(it)

    old = {r["onlyName"]: r["old_url"] for r in report if r.get("status") == "ok"}
    state = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "service_base": a.service_base,
             "changed": {it["onlyName"]: {"new_url": it["url"], "old_url": old.get(it["onlyName"])}
                         for it in ok}}
    os.makedirs(os.path.dirname(a.state), exist_ok=True)
    if os.path.exists(a.state):
        os.rename(a.state, a.state + f".bak.{int(time.time())}")
    json.dump(state, open(a.state, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n成功 {len(ok)} 条，失败 {len(fail)} 条；state: {os.path.abspath(a.state)}")
    return 0 if not fail else 2


if __name__ == "__main__":
    raise SystemExit(main())
