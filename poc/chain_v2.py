#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step2 终版：纯 Python 走通 is_login → GetUid → dockerToken(V2) → redirect_url → Set-Cookie → app-<port>-1/。
覆盖端口 8080 / 5244 / 8097，证据写 capture/chain_v2_<ts>.json。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from ugreen_client import UgreenClient  # noqa: E402

BASE = "https://<ALIAS>.ug.link"
PORTS = [8080, 5244, 8097]


def main() -> int:
    cred = os.environ.get("UGNAS_BRIDGE_PASS") or os.environ.get("DSH_SECRET_NAS_DHADMIN_PASS")
    if not cred:
        print("missing UGNAS_BRIDGE_PASS", file=sys.stderr)
        return 2
    c = UgreenClient(BASE)
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "steps": []}

    env = c.login(os.environ.get("UGNAS_BRIDGE_USER", ""), cred)
    d = env.data if isinstance(env.data, dict) else {}
    tok, tid, pub = d.get("token"), d.get("token_id"), d.get("public_key")
    ev["login"] = {"http": env.http, "code": env.code, "msg": env.msg,
                   "enable_otp": d.get("enable_otp"), "token_len": len(tok or ""),
                   "auth_type": d.get("auth_type"), "model": d.get("model"),
                   "system_version": d.get("system_version")}
    if not (tok and tid and pub):
        print(json.dumps(ev, ensure_ascii=False))
        return 1

    isl = c.is_login(tok)
    ev["is_login"] = {"http": isl.http, "code": isl.code, "msg": isl.msg}
    uid = c.get_uid(tok)
    ev["get_uid"] = {"http": uid.http, "code": uid.code, "data": uid.data}

    for port in PORTS:
        rec = {"port": port}
        dt = c.docker_token_v2(port, tok, tid, pub)
        ru = (dt.data or {}).get("redirect_url") if isinstance(dt.data, dict) else None
        rec["docker_token"] = {"http": dt.http, "code": dt.code, "msg": dt.msg,
                               "has_redirect": bool(ru)}
        if ru:
            rec["open"] = c.open_proxy(ru, port)
        ev["steps"].append(rec)
        print(json.dumps({k: (v if k != "docker_token" else
                              {"http": v["http"], "code": v["code"], "has_redirect": v["has_redirect"]})
                          for k, v in rec.items()}, ensure_ascii=False))

    outdir = os.path.join(os.path.dirname(__file__), "..", "capture")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.abspath(os.path.join(outdir, f"chain_v2_{time.strftime('%Y%m%d_%H%M%S')}.json"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    print("EVIDENCE:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
