#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调研 POC：验证 UGOS 登录 → is_login → GetUid → dockerToken(v1) → redirect → cookie → 应用页。
保留作为协议排查工具；固件 1.21 后换 token 需用 UgreenSession.docker_redirect（v2 双头）。
"""
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error
import ssl
import uuid

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def hdr(base):
    return {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Origin": base,
            "Referer": base + "/desktop/", "Client-Id": f"{uuid.uuid4()}-WEB",
            "Client-Version": "78578", "Client-Version-Str": "1.20.0",
            "UG-Agent": "PC/WEB", "X-Specify-Language": "zh-CN"}


def rq(url, base, data=None, cookie=None, timeout=15):
    h = hdr(base)
    if data is not None:
        h["Content-Type"] = "application/json"
    if cookie:
        h["Cookie"] = cookie
    r = urllib.request.Request(url, data=(json.dumps(data).encode() if data is not None else None),
                               headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=ctx) as x:
            return x.status, {k.lower(): v for k, v in x.headers.items()}, x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, {}, repr(e)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "https://<ALIAS>.ug.link"
    user = os.environ.get("UGNAS_BRIDGE_USER", "")
    cred = os.environ.get("UGNAS_BRIDGE_PASS") or os.environ.get("DSH_SECRET_NAS_DHADMIN_PASS")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    # 1) 登录
    s, h, b = rq(f"{base}/ugreen/v1/verify/check", base, {"username": user})
    pem = base64.b64decode(h.get("x-rsa-token", "")).decode("utf-8", "replace")
    pem = pem.replace("BEGIN RSA PUBLIC KEY", "BEGIN PUBLIC KEY").replace("END RSA PUBLIC KEY", "END PUBLIC KEY")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_public_key(pem.encode())
    enc = base64.b64encode(key.encrypt(cred.encode(), padding.PKCS1v15())).decode()
    s, h, b = rq(f"{base}/ugreen/v1/verify/login", base,
                 {"username": user, "password": enc, "keepalive": False, "otp": True, "is_simple": True})
    j = json.loads(b)
    d = j.get("data") or {}
    tok, tid, pub = d.get("token"), d.get("token_id"), d.get("public_key")
    print(f"login code={j.get('code')} token={'yes' if tok else 'no'}")
    # 2) v1 链路（旧固件）：GetUid + dockerToken（明文 query）
    s, h, b = rq(f"{base}/ugreen/v1/docker/app/GetUid?token={tok}", base)
    print("GetUid(v1):", b[:200])
    s, h, b = rq(f"{base}/ugreen/v1/docker/app/dockerToken?port={port}&token={tok}", base)
    print("dockerToken(v1):", b[:200])


if __name__ == "__main__":
    main()
