#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 验收一键自检（规格书 §6），判定与真实状态机一致。

用法：python3 scripts/verify.py --base http://127.0.0.1:8770 [--key KEY]

状态机：
1) needs_setup=true -> open 检查 SKIP
2) 已初始化但 ugreen 未配置 -> open 期望 400
3) 已初始化且 ugreen 已配置：带 --key -> 无?k= 401、带?k= 302；不带 --key -> 接受 401/302/502
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def req(url, method="GET", timeout=8):
    r = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()[:600]
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()[:200]


def jget(body):
    try:
        return json.loads(body)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    checks = []

    st, body = req(base + "/api/health")
    checks.append(("health 200", st == 200))
    health = jget(body)

    st2, body2 = req(base + "/api/setup/status")
    needs_setup = bool(jget(body2).get("needs_setup", True))

    if needs_setup:
        print("SKIP open 检查：实例未初始化（needs_setup=true）")
    elif not health.get("configured", {}).get("ugreen"):
        s, _ = req(base + "/open/8080")
        checks.append(("open 未配置 400", s == 400))
    else:
        if a.key:
            s, _ = req(base + "/open/8080")
            checks.append(("open 无口令 401", s == 401))
            s, _ = req(base + "/open/8080?k=" + a.key)
            checks.append(("open 带口令 302", s == 302))
        else:
            s, _ = req(base + "/open/8080")
            checks.append(("open 可达(401/302/502)", s in (401, 302, 502)))

    ok = all(c[1] for c in checks)
    for name, passed in checks:
        print("PASS" if passed else "FAIL", name)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
