#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绿联 NAS ⇄ Sun-Panel 免登录直连 · 本地小服务（B 方案，标准库，无第三方依赖）

用法：
    UGNAS_BRIDGE_PASS=... python3 ugnas_bridge.py --port 8770

路由：
    GET /                  → 端口索引页（便于手机直接点）
    GET /open/<port>?k=KEY → 换一次性 redirect_url 后 302 到 app-<port>-1/（浏览器落 cookie，免登录）
    GET /health            → JSON 状态（含 token 掩码、登录/续期计数）

设计要点：
    - 换 token 全在服务端完成，浏览器只做一次 302；不依赖内网、不需要扩展。
    - redirect_url 指向 https://app-<port>-<alias>.<dockerDomain>/api/ugreen/auth?token=...
      该页在应用域内用 JS 写 ugreen-proxy-token 再跳 /，因此 302 就能免登录进应用。
    - 后台心跳线程按 refresh_interval 续期，并把每次心跳写日志（常驻任务可见证据）。
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from ugreen_client import UgreenClient, UgreenSession  # noqa: E402

LOG_PATH = os.environ.get("UGNAS_BRIDGE_LOG", os.path.join(HERE, "..", "logs", "bridge.log"))
_log_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


PORTS = [8080, 5244, 8097, 7050, 6806, 9090, 6080, 8089, 4567, 8484, 8889,
         19119, 9820, 15888, 38090, 38766, 9208, 8023, 8024, 8888, 9527,
         5199, 10001, 10100, 18082, 28090]

INDEX_HTML = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>绿联应用直达</title>
<style>body{font-family:-apple-system,system-ui,"PingFang SC",sans-serif;margin:0;padding:20px;background:#111;color:#eee}
h1{font-size:18px;font-weight:600;margin:0 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
a{display:block;padding:14px 10px;border-radius:12px;background:#1e1e22;color:#eee;text-decoration:none;text-align:center;font-size:14px}
a:active{background:#2a2a30}small{color:#888;display:block;margin-top:4px}</style>
<h1>绿联应用直达</h1><div class="grid">{items}</div>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "UgnasBridge/1.0"
    protocol_version = "HTTP/1.1"
    session: UgreenSession = None  # 由 main 注入
    access_key: str = ""           # UGNAS_BRIDGE_KEY；为空则不校验（仅建议内网）

    def log_message(self, fmt, *args):  # 走统一日志
        log(f"HTTP {self.client_address[0]} {fmt % args}")

    # ---------- 鉴权 ----------
    def _key_ok(self, q) -> bool:
        if not self.access_key:
            return True
        got = (q.get("k") or [""])[0]
        return hmac.compare_digest(got, self.access_key)

    # ---------- 工具 ----------
    def _send(self, code: int, body: bytes, ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    # ---------- 路由 ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if path == "/":
            q = parse_qs(u.query)
            if not self._key_ok(q):
                return self._json(401, {"error": "missing/invalid key"})
            suffix = f"?k={self.access_key}" if self.access_key else ""
            items = "".join(f'<a href="/open/{p}{suffix}">{p}<small>open</small></a>' for p in PORTS)
            return self._send(200, INDEX_HTML.format(items=items).encode(), "text/html; charset=utf-8")
        if path == "/health":
            snap = self.session.snapshot()
            snap.update({"ok": snap["has_token"], "ts": int(time.time())})
            return self._json(200, snap)
        if path.startswith("/open/"):
            if not self._key_ok(parse_qs(u.query)):
                log(f"AUTH-DENY {self.client_address[0]} {path}")
                return self._json(401, {"error": "missing/invalid key"})
            port_s = path[len("/open/"):]
            if not port_s.isdigit():
                return self._json(400, {"error": "bad port"})
            port = int(port_s)
            t0 = time.time()
            ru, env = self.session.docker_redirect(port)
            dt = int((time.time() - t0) * 1000)
            if not ru:
                log(f"OPEN port={port} FAILED code={getattr(env,'code',None)} cost={dt}ms")
                return self._json(502, {"error": "dockerToken failed", "code": getattr(env, "code", None),
                                        "msg": getattr(env, "msg", "")})
            log(f"OPEN port={port} OK cost={dt}ms -> app-{port}")
            return self._send(302, b"", extra={"Location": ru})
        return self._json(404, {"error": "not found"})


def heartbeat(session: UgreenSession, interval: int, stop: threading.Event):
    while not stop.wait(interval):
        # 心跳同时承担续期触发：到期就 refresh，保证常驻期间 token 不过期
        try:
            session.credentials()
        except Exception as e:
            log(f"HEARTBEAT refresh error: {e}")
        snap = session.snapshot()
        log(f"HEARTBEAT " + json.dumps({k: snap[k] for k in
                                        ("has_token", "token", "token_age_s", "logins", "refreshes",
                                         "refresh_fail", "last_error")}, ensure_ascii=False))


def main() -> int:
    env = os.environ
    ap = argparse.ArgumentParser()
    # 全部参数支持环境变量，便于 systemd / 容器参数化部署
    ap.add_argument("--host", default=env.get("UGNAS_BRIDGE_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(env.get("UGNAS_BRIDGE_PORT", "8770")))
    ap.add_argument("--base", default=env.get("UGNAS_BRIDGE_BASE", "https://<ALIAS>.ug.link"))
    ap.add_argument("--alias", default=env.get("UGNAS_BRIDGE_ALIAS", ""))
    ap.add_argument("--user", default=env.get("UGNAS_BRIDGE_USER", ""))
    ap.add_argument("--refresh-interval", type=int, default=int(env.get("UGNAS_BRIDGE_REFRESH", "1800")))
    ap.add_argument("--heartbeat", type=int, default=int(env.get("UGNAS_BRIDGE_HEARTBEAT", "300")))
    a = ap.parse_args()

    cred = env.get("UGNAS_BRIDGE_PASS") or env.get("DSH_SECRET_NAS_DHADMIN_PASS")
    if not cred:
        log("FATAL missing UGNAS_BRIDGE_PASS")
        return 2

    client = UgreenClient(a.base, alias=a.alias)
    session = UgreenSession(client, a.user, cred, refresh_interval=a.refresh_interval, logger=log)
    log(f"START host={a.host} port={a.port} base={a.base} refresh={a.refresh_interval}s heartbeat={a.heartbeat}s")
    if not session.credentials()[0]:
        log("FATAL initial login failed")
        return 3

    Handler.session = session
    access_key = env.get("UGNAS_BRIDGE_KEY", "").strip()
    Handler.access_key = access_key
    if access_key:
        log(f"AUTH enabled (key len={len(access_key)})")
    else:
        log("WARN no UGNAS_BRIDGE_KEY: /open/* is open to anyone")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(session, a.heartbeat, stop), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("STOP by SIGINT")
    finally:
        stop.set()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
