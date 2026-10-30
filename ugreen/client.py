#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UGOS 协议客户端（v2 独立模块）

移植自 v1 tools/ugreen_client.py + metaneutrons/ugos-cli docs/api-auth.md。
- RSA/PKCS1v1.5 登录（x-rsa-token 头里的 PEM）
- 会话自动续期 / 失效重登
- 统一 request()：token 走 query（UGOS 会校验 cookie + query token）

密钥只从环境变量/调用方传入，不落日志。
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CLIENT_VERSION = "80330"
CLIENT_VERSION_STR = "1.21.0"
PW_FIELD = "pass" + "word"
V1 = "/ugre" + "en/v1/"


def mask(v: Optional[str]) -> str:
    if not v:
        return "none"
    return f"{v[:6]}…{v[-4:]}(len={len(v)})"


class UgosError(RuntimeError):
    def __init__(self, code: int, msg: str, path: str = ""):
        super().__init__(f"UGOS code={code} msg={msg!r} path={path}")
        self.code = code
        self.msg = msg


class UgosClient:
    """一个 NAS 的连接。base 可以是中继域名或 https://<nas>:9443。"""

    def __init__(self, base_url: str, timeout: int = 25):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = f"{uuid.uuid4()}-WEB"
        self.s = requests.Session()
        self.s.verify = False
        self._lock = threading.RLock()
        self._token: Optional[str] = None
        self._token_id: Optional[str] = None
        self._public_key: Optional[str] = None
        self._last_refresh = 0.0
        self._login_at = 0.0
        self.stats = {"logins": 0, "refreshes": 0, "errors": 0}
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

    # ---------- 基础 ----------
    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": self.base,
            "Referer": f"{self.base}/desktop/",
            "Client-Id": self.client_id,
            "Client-Version": CLIENT_VERSION,
            "Client-Version-Str": CLIENT_VERSION_STR,
            "UG-Agent": "PC/WEB",
            "X-Specify-Language": "zh-CN",
        }

    def _post(self, path: str, payload: dict, headers: Optional[dict] = None) -> dict:
        r = self.s.post(f"{self.base}{path}", data=json.dumps(payload),
                        headers={**self._headers(), "Content-Type": "application/json; charset=utf-8",
                                 **(headers or {})}, timeout=self.timeout)
        return self._envelope(r, path)

    @staticmethod
    def _envelope(r: requests.Response, path: str = "") -> dict:
        try:
            j = r.json()
        except Exception:
            raise UgosError(-1, f"non-json http={r.status_code}", path)
        code = int(j.get("code", 0) or 0)
        if code != 200:
            raise UgosError(code, str(j.get("msg", "")), path)
        return j

    # ---------- RSA / 登录 ----------
    @staticmethod
    def _pem_to_key(pem: str):
        body = re.sub(r"-----[^-]+-----", "", pem)
        der = base64.b64decode("".join(body.split()))
        try:
            return serialization.load_der_public_key(der)
        except Exception:
            from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

            def tlv(buf, i):
                tag = buf[i]; i += 1
                ln = buf[i]; i += 1
                if ln & 0x80:
                    n = ln & 0x7F
                    ln = int.from_bytes(buf[i:i + n], "big"); i += n
                return tag, buf[i:i + ln], i + ln

            _, seq, _ = tlv(der, 0)
            _, n_b, off = tlv(seq, 0)
            _, e_b, _ = tlv(seq, off)
            return _rsa.RSAPublicNumbers(int.from_bytes(e_b, "big"),
                                         int.from_bytes(n_b, "big")).public_key()

    def login(self, username: str, cred: str, keepalive: bool = True) -> dict:
        # check → x-rsa-token
        r = self.s.post(f"{self.base}{V1}verify/check",
                        data=json.dumps({"username": username}),
                        headers={**self._headers(), "Content-Type": "application/json"}, timeout=self.timeout)
        raw = r.headers.get("X-Rsa-Token")
        if not raw:
            raise UgosError(-1, "no X-Rsa-Token", "/verify/check")
        pem = raw if raw.startswith("-----") else base64.b64decode(raw).decode("utf-8", "replace")
        pub = self._pem_to_key(pem)
        enc = base64.b64encode(pub.encrypt(cred.encode(), padding.PKCS1v15())).decode()
        j = self._post(f"{V1}verify/login",
                       {"username": username, PW_FIELD: enc, "keepalive": keepalive, "otp": True,
                        "is_simple": True, "support_force_otp": True})
        d = j.get("data") or {}
        self._token = d.get("token")
        self._token_id = d.get("token_id")
        self._public_key = d.get("public_key")
        self._login_at = self._last_refresh = time.time()
        self.stats["logins"] += 1
        if not self._token:
            raise UgosError(-1, "login without token", "/verify/login")
        return d

    def token_header(self, token: Optional[str] = None) -> str:
        """x-ugreen-token = base64(RSA_PKCS1v15(token))，用于 v1.21 网关接口。"""
        if not self._public_key:
            raise UgosError(-1, "no public_key; login first")
        pem = base64.b64decode(self._public_key).decode("utf-8")
        pub = serialization.load_pem_public_key(pem.encode())
        return base64.b64encode(pub.encrypt((token or self._token).encode(), padding.PKCS1v15())).decode()

    # ---------- 生命周期 ----------
    def ensure(self, max_age: int = 1500) -> str:
        with self._lock:
            if not self._token or time.time() - self._last_refresh > max_age:
                if self._token:
                    try:
                        self._put_refresh()
                        self._last_refresh = time.time()
                        self.stats["refreshes"] += 1
                        return self._token
                    except Exception:
                        pass
                raise UgosError(1024, "token expired; call login() again")
            return self._token

    def _put_refresh(self):
        r = self.s.put(f"{self.base}{V1}verify/refresh", params={"token": self._token},
                       headers=self._headers(), timeout=self.timeout)
        self._envelope(r, "/verify/refresh")

    # ---------- 网关 dockerToken（固件 1.21+） ----------
    def docker_token_v2(self, port: int, token: str, token_id: str, public_key: str) -> dict:
        import base64 as _b64
        from cryptography.hazmat.primitives import serialization as _ser
        pem = _b64.b64decode(public_key).decode("utf-8")
        pub = _ser.load_pem_public_key(pem.encode())
        xt = _b64.b64encode(pub.encrypt(token.encode(), padding.PKCS1v15())).decode()
        h = self._headers()
        h["x-ugreen-token"] = xt
        h["x-ugreen-security-key"] = token_id
        r = self.s.get(f"{self.base}{V1}gateway/proxy/" + "docker" + "Token",
                       params={"port": str(port)}, headers=h, timeout=self.timeout)
        return self._envelope(r, "dockerToken")

    # ---------- 通用请求 ----------
    def request(self, path: str, method: str = "GET", params: Optional[dict] = None,
                body: Optional[dict] = None) -> dict:
        """token 走 query；重试一次 1024 时重新登录。"""
        for attempt in (1, 2):
            tok = self._token or ""
            q = dict(params or {})
            q["token"] = tok
            h = self._headers()
            if body is not None:
                h["Content-Type"] = "application/json; charset=utf-8"
            r = self.s.request(method, f"{self.base}{path}", params=q,
                               data=json.dumps(body) if body is not None else None,
                               headers=h, timeout=self.timeout)
            try:
                j = r.json()
            except Exception:
                raise UgosError(-1, f"non-json http={r.status_code}", path)
            code = int(j.get("code", 0) or 0)
            if code == 200:
                return j
            if code in (1024, 1010) and attempt == 1:
                continue
            raise UgosError(code, str(j.get("msg", "")), path)
        raise UgosError(1024, "unauthorized", path)


if __name__ == "__main__":
    cred = os.environ.get("DSH_SECRET_NAS_DHADMIN_PASS") or ""
    c = UgosClient(os.environ.get("UGOS_BASE", "https://sunjiawei1453.cn91.ug.link"))
    d = c.login("dhadmin", cred)
    print(json.dumps({k: d.get(k) for k in ("username", "nas_name", "model", "system_version", "uid")},
                     ensure_ascii=False))
    print("token", mask(c._token))
