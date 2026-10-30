#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 验收一键自检（规格书 §6）。用法：
python3 scripts/verify.py --base http://127.0.0.1:8770 [--key KEY]
未配置绿联时跳过 open 检查（配置后再跑即完整）。
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
            return resp.status, resp.read()[:500]
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    checks = []

    status, body = req(base + "/api/health")
    checks.append(("health 200", status == 200))
    configured = False
    try:
        configured = bool(json.loads(body).get("configured", {}).get("ugreen"))
    except Exception:
        pass

    if configured:
        s, _ = req(base + "/open/8080")
        checks.append(("open 无口令 401", s == 401))
        if a.key:
            s, _ = req(base + "/open/8080?k=" + a.key)
            checks.append(("open 带口令 302", s == 302))
    else:
        print("SKIP open 检查：绿联尚未配置（配置后重跑即完整）")

    ok = all(c[1] for c in checks)
    for name, passed in checks:
        print("PASS" if passed else "FAIL", name)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
