#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 mock Sun-Panel OpenAPI：用于离线验证 update_cards.py 的 dry-run/apply/rollback 逻辑。
不连真实面板。默认 --port 19302 避免冲突。
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ITEMS = {
    "ug-openlist": {"onlyName": "ug-openlist", "title": "openlist", "url": "https://<ALIAS>.ug.link/desktop/", "lanUrl": "http://<NAS>:5244"},
    "ug-emby": {"onlyName": "ug-emby", "title": "Emby", "url": "https://<ALIAS>.ug.link/desktop/", "lanUrl": "http://<NAS>:8097"},
    "ug-sub2api": {"onlyName": "ug-sub2api", "title": "sub2api", "url": "https://<ALIAS>.ug.link/desktop/", "lanUrl": "http://<NAS>:8080"},
}
GROUPS = [{"itemGroupID": 13, "onlyName": "ugreen-nas", "title": "绿联NAS"}]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    token = "mocktoken"

    def _j(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.headers.get("token") != self.token:
            return self._j({"code": 1000, "msg": "token expires"})
        p = self.path
        if p.endswith("/version"):
            return self._j({"code": 0, "msg": "OK", "data": "1.8.1-mock"})
        if p.endswith("/itemGroup/getList"):
            return self._j({"code": 0, "msg": "OK", "data": {"count": len(GROUPS), "list": GROUPS}})
        if p.endswith("/item/getInfoByOnlyName"):
            it = ITEMS.get(body.get("onlyName"))
            return self._j({"code": 0, "msg": "OK", "data": it} if it else {"code": 1203, "msg": "item not found"})
        if p.endswith("/item/batchUpdate"):
            succ, fails = 0, []
            for it in body.get("items", []):
                t = ITEMS.get(it["onlyName"])
                if not t:
                    fails.append({"onlyName": it["onlyName"], "error": "item not found"}); continue
                if "url" in it: t["url"] = it["url"]
                if "lanUrl" in it: t["lanUrl"] = it["lanUrl"]
                succ += 1
            return self._j({"code": 0, "msg": "OK", "data": {"successCount": succ, "failCount": len(fails), "failItems": fails}})
        return self._j({"code": 404, "msg": "no route " + p})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19302
    print(f"mock openapi on :{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
