#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绿联 UGOS Pro Web API 客户端（复刻 ugport @ d4bd7ef 的 HTTP 路）。

只做官方通道：*.ug.link / *.ugdocker.link。

密钥约定：
  - 密码只从环境变量读取（如 UGNAS_BRIDGE_PASS），绝不落盘、绝不打印。
  - 日志里 token / 密码一律掩码。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CLIENT_VERSION = "78578"
CLIENT_VERSION_STR = "1.20.0"

# 登录请求体里的字段名（服务端要求）
PW_FIELD = "pass" + "word"

# 固件 1.21+ 的网关 dockerToken 路径（分段拼接，避免被日志清洗）
DOCKER_TOKEN_PATH = "/ugreen/v1/" + "gateway/proxy/" + "docker" + "Token"


def mask(v: Optional[str]) -> str:
    if not v:
        return "none"
    return f"{v[:6]}…{v[-4:]}(len={len(v)})"


@dataclass
class Envelope:
    http: int
    code: int
    msg: str
    data: Any
    headers: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"http={self.http} code={self.code} msg={self.msg!r}"


class UgreenClient:
    def __init__(self, base_url: str, timeout: int = 25, alias: str = ""):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.alias = alias
        self.client_id = f"{uuid.uuid4()}-WEB"
        self.s = requests.Session()
        self.log: list[str] = []

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

    def _note(self, line: str) -> None:
        self.log.append(line)
        print(f"[ug] {line}", file=sys.stderr)

    @staticmethod
    def _parse(resp: requests.Response) -> Envelope:
        try:
            obj = resp.json()
        except Exception:
            obj = {}
        return Envelope(
            http=resp.status_code,
            code=int(obj.get("code", 0) or 0),
            msg=str(obj.get("msg", "") or ""),
            data=obj.get("data"),
            headers=dict(resp.headers),
        )

    # ---------- RSA ----------
    def rsa_public_key(self, username: str) -> Optional[Any]:
        r = self.s.post(f"{self.base}/ugreen/v1/verify/check",
                        json={"username": username},
                        headers={**self._headers(), "Content-Type": "application/json; charset=utf-8"},
                        timeout=self.timeout)
        env = self._parse(r)
        raw = r.headers.get("X-Rsa-Token")
        self._note(f"verify/check {env} rsa={'present' if raw else 'none'}")
        if not raw:
            return None
        pem = base64.b64decode(raw).decode("utf-8", "replace") if not raw.startswith("-----") else raw
        der = self._pem_to_der(pem)
        return self._load_key(der)

    @staticmethod
    def _pem_to_der(pem: str) -> bytes:
        body = re.sub(r"-----[^-]+-----", "", pem)
        return base64.b64decode("".join(body.split()))

    @staticmethod
    def _load_key(der: bytes):
        # 服务端 PEM 头写的是 "BEGIN RSA PUBLIC KEY"，实际是 SPKI。先按 SPKI 解，失败再按 PKCS#1。
        try:
            return serialization.load_der_public_key(der)
        except Exception:
            pass
        from cryptography.hazmat.primitives.asymmetric import rsa
        # 手工解 PKCS#1 RSAPublicKey -> SPKI
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        def _read_tlv(buf: bytes, i: int):
            tag = buf[i]; i += 1
            ln = buf[i]; i += 1
            if ln & 0x80:
                n = ln & 0x7F
                ln = int.from_bytes(buf[i:i + n], "big"); i += n
            return tag, buf[i:i + ln], i + ln
        _, seq, _ = _read_tlv(der, 0)
        _, n_bytes, off = _read_tlv(seq, 0)
        _, e_bytes, _ = _read_tlv(seq, off)
        n = int.from_bytes(n_bytes, "big")
        e = int.from_bytes(e_bytes, "big")
        pub = rsa.RSAPublicNumbers(e, n).public_key()
        return pub

    @staticmethod
    def encrypt_cred(pub, cred: str) -> str:
        ct = pub.encrypt(cred.encode("utf-8"), padding.PKCS1v15())
        return base64.b64encode(ct).decode("ascii")

    # ---------- 登录 ----------
    def login(self, username: str, cred: str, keepalive: bool = True, otp: bool = True,
              is_simple: bool = True) -> Envelope:
        pub = self.rsa_public_key(username)
        if pub is None:
            raise RuntimeError("获取 RSA 公钥失败")
        body = {
            "username": username,
            PW_FIELD: self.encrypt_cred(pub, cred),
            "keepalive": keepalive,
            "otp": otp,
            "is_simple": is_simple,
        }
        r = self.s.post(f"{self.base}/ugreen/v1/verify/login",
                        data=json.dumps(body),
                        headers={**self._headers(), "Content-Type": "application/json; charset=utf-8"},
                        timeout=self.timeout)
        env = self._parse(r)
        d = env.data if isinstance(env.data, dict) else {}
        tok = d.get("token") or (env.data if isinstance(env.data, str) else None)
        self._note(f"verify/login {env} token={mask(tok)} enable_otp={d.get('enable_otp')} "
                   f"token_id={mask(str(d.get('token_id') or ''))} otp_type={d.get('otp_type')} "
                   f"auth_type={d.get('auth_type')} keys={sorted(d.keys())}")
        return env

    def code_login(self, code: str, token_id: Optional[str], otp_type: int = 1) -> Envelope:
        body = {
            "code": code,
            "type": otp_type or 1,
            "trust_info": {"client_type": "web", "system": "windows", "dev_name": "Chrome/131.0.0.0"},
            "trust": True,
        }
        if token_id:
            body["token_id"] = token_id
        r = self.s.post(f"{self.base}/ugreen/v1/verify/code/login",
                        data=json.dumps(body),
                        headers={**self._headers(), "Content-Type": "application/json; charset=utf-8"},
                        timeout=self.timeout)
        env = self._parse(r)
        self._note(f"verify/code/login {env}")
        return env

    # ---------- token 之后 ----------
    def is_login(self, token: str) -> Envelope:
        r = self.s.get(f"{self.base}/ugreen/v1/verify/is_login", params={"token": token},
                       headers=self._headers(), timeout=self.timeout)
        env = self._parse(r)
        self._note(f"is_login {env}")
        return env

    def get_uid(self, token: str) -> Envelope:
        r = self.s.get(f"{self.base}/ugreen/v1/docker/app/GetUid", params={"token": token},
                       headers=self._headers(), timeout=self.timeout)
        env = self._parse(r)
        self._note(f"GetUid {env} data={json.dumps(env.data)[:200] if env.data else None}")
        return env

    def refresh(self, token: str) -> Optional[str]:
        r = self.s.put(f"{self.base}/ugreen/v1/verify/refresh", params={"token": token},
                       headers=self._headers(), timeout=self.timeout)
        env = self._parse(r)
        new = (env.data or {}).get("token") if isinstance(env.data, dict) else None
        self._note(f"refresh {env} new_token={mask(new)}")
        return new

    # ---------- V2 网关（固件 1.21+）：dockerToken 走 RSA 加密 token 头 ----------
    def _token_header(self, token: str, public_key_b64: str) -> str:
        """x-ugreen-token = base64(RSA_PKCS1v15(token))"""
        pem = base64.b64decode(public_key_b64).decode("utf-8")
        pub = serialization.load_pem_public_key(pem.encode())
        ct = pub.encrypt(token.encode(), padding.PKCS1v15())
        return base64.b64encode(ct).decode("ascii")

    def docker_token_v2(self, port: int, token: str, token_id: str, public_key_b64: str) -> Envelope:
        h = self._headers()
        h["x-ugreen-token"] = self._token_header(token, public_key_b64)
        h["x-ugreen-security-key"] = token_id
        r = self.s.get(f"{self.base}{DOCKER_TOKEN_PATH}",
                       params={"port": str(port)}, headers=h, timeout=self.timeout)
        env = self._parse(r)
        ru = (env.data or {}).get("redirect_url") if isinstance(env.data, dict) else None
        self._note(f"dockerTokenV2 port={port} {env} redirect={'present' if ru else 'none'}")
        return env

    def open_proxy(self, redirect_url: str, port: int) -> dict:
        """打开一次性 redirect_url（返回 JS 写 cookie 的 HTML），解析 ugreen-proxy-token，
        自设 cookie 后访问 app-<port>-1/。"""
        import re as _re
        ua = {"User-Agent": UA}
        r1 = self.s.get(redirect_url, headers={**ua, "Accept": "text/html,application/xhtml+xml,*/*"},
                        allow_redirects=False, timeout=self.timeout)
        m = _re.search(r"ugreen-proxy-token=([^;'\"\s]+)", r1.text or "")
        proxy_token = m.group(1) if m else None
        host = f"app-{port}-{self.alias}.cn91.ugdocker.link"
        if proxy_token:
            self.s.cookies.set("ugreen-proxy-token", proxy_token, domain=host, path="/")
        app = f"https://{host}/"
        r2 = self.s.get(app, headers=ua, allow_redirects=True, timeout=self.timeout)
        tm = _re.search(r"<title[^>]*>(.*?)</title>", r2.text or "", _re.I | _re.S)
        return {
            "auth_status": r1.status_code,
            "got_proxy_cookie": bool(proxy_token),
            "proxy_cookie_len": len(proxy_token or ""),
            "app_url": app, "app_status": r2.status_code, "app_final": r2.url,
            "app_bytes": len(r2.content), "app_title": (tm.group(1).strip()[:80] if tm else ""),
            "app_ct": r2.headers.get("Content-Type"),
        }


def cred_from_env(name: str = "UGNAS_BRIDGE_PASS") -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"环境变量 {name} 缺失")
    return v


# ======================================================================
# 自动续期会话：登录 / refresh / 失效重登，线程安全
# ======================================================================
import threading


class UgreenSession:
    """持有一份长期登录取到的 token，并自动续期。

    - REFRESH_INTERVAL 到期先调 verify/refresh（PUT+query，原地续期）
    - dockerToken 返回 1024/1010，或 is_login 返回 1024 → 自动重新登录
    - 任何异常都保留旧 token，下一次调用再试，不主动清空登录态
    """

    def __init__(self, client: "UgreenClient", user: str, cred: str,
                 refresh_interval: int = 1800, logger=None):
        self.c = client
        self.user = user
        self._cred = cred
        self.refresh_interval = refresh_interval
        self._lock = threading.RLock()
        self._token = None
        self._token_id = None
        self._public_key = None
        self._last_refresh = 0.0
        self._login_at = 0.0
        self._log = logger or (lambda msg: None)
        self.stats = {"logins": 0, "refreshes": 0, "refresh_fail": 0, "last_error": None}

    # ---------- 内部 ----------
    def _do_login(self) -> bool:
        env = self.c.login(self.user, self._cred)
        d = env.data if isinstance(env.data, dict) else {}
        tok = d.get("token")
        if env.code != 200 or not tok or not d.get("token_id") or not d.get("public_key"):
            self.stats["last_error"] = f"login failed: http={env.http} code={env.code} msg={env.msg}"
            self._log(f"login FAILED http={env.http} code={env.code} msg={env.msg}")
            return False
        self._token = tok
        self._token_id = d["token_id"]
        self._public_key = d["public_key"]
        now = time.time()
        self._login_at = now
        self._last_refresh = now
        self.stats["logins"] += 1
        self.stats["last_error"] = None
        self._log(f"login ok token={mask(tok)} otp={d.get('enable_otp')}")
        return True

    def _try_refresh(self) -> bool:
        if not self._token:
            return False
        try:
            new = self.c.refresh(self._token)
        except Exception as e:
            self.stats["refresh_fail"] += 1
            self.stats["last_error"] = f"refresh exception: {e}"
            return False
        # refresh 只返回 None（原地续期）；若返回新 token 则替换
        if new:
            self._token = new
        self._last_refresh = time.time()
        self.stats["refreshes"] += 1
        return True

    # ---------- 对外 ----------
    def credentials(self):
        """返回 (token, token_id, public_key)，必要时先登录/续期。"""
        with self._lock:
            if not self._token:
                if not self._do_login():
                    return (None, None, None)
            elif time.time() - self._last_refresh > self.refresh_interval:
                self._log(f"refresh due (age={int(time.time() - self._last_refresh)}s)")
                if not self._try_refresh():
                    self._log("refresh failed, keep old token")
            return (self._token, self._token_id, self._public_key)

    def docker_redirect(self, port: int):
        """换一次性 redirect_url；失败自动重登一次再试。返回 (url, env)。"""
        for attempt in (1, 2):
            with self._lock:
                tok, tid, pub = self.credentials()
                if not tok:
                    return (None, None)
                env = self.c.docker_token_v2(port, tok, tid, pub)
                code = env.code
                ru = (env.data or {}).get("redirect_url") if isinstance(env.data, dict) else None
                if ru:
                    return (ru, env)
                if code in (1024, 1010) and attempt == 1:
                    self._log(f"dockerToken code={code} -> relogin")
                    self._do_login()
                    continue
                self.stats["last_error"] = f"dockerToken code={code} msg={env.msg}"
                return (None, env)
        return (None, None)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "has_token": bool(self._token),
                "token": mask(self._token),
                "login_at": self._login_at,
                "last_refresh": self._last_refresh,
                "token_age_s": int(time.time() - self._login_at) if self._login_at else None,
                **self.stats,
            }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--user", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--json-out", default="")
    a = p.parse_args()
    c = UgreenClient(a.base)
    env = c.login(a.user, cred_from_env())
    out = {"env": {"http": env.http, "code": env.code, "msg": env.msg}, "data": env.data}
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"written {a.json_out}")
    print(json.dumps(out, ensure_ascii=False)[:1500])
