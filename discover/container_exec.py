#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 UGOS 容器内执行只读命令（容器终端 API + WebSocket）

协议来源：Docker Web 前端 `docker/assets/index-*.js`
  - POST {v1}/docker/container/AddTerminal  body {"id":<containerId>,"exec":"/bin/sh","pageID":"<id>"}
      -> data.result = terminal uuid
  - WS  wss://<host>{v1}/docker/container/Ws?containerId=<id>&uuid=<uuid>&token=<token>
  - 帧：{"type":"docker-terminal","data":{"code":200,"msg":"","text":"<输入>","columns":120,"rows":40}}
  - 输出：同结构，data.text 为终端回显
  - POST .../DelTerminal {"id":<containerId>,"uuid":<uuid>}

只用于只读诊断（ss / cat /proc/...），不做任何写操作或状态变更。
"""
from __future__ import annotations

import json
import re
import ssl
import time
import uuid
from typing import Optional

import websocket

from ugreen.client import UgosClient, UgosError

CONTAINER = "/ugre" + "en/v1/docker/container/"


class ContainerExec:
    def __init__(self, client: UgosClient, cols: int = 1000, rows: int = 80):
        self.c = client
        self.cols = cols
        self.rows = rows

    # ---------- 终端会话 ----------
    def _add(self, container_id: str) -> str:
        r = self.c.request(CONTAINER + "AddTerminal", method="POST",
                           body={"id": container_id, "exec": "/bin/sh", "pageID": f"poc-{uuid.uuid4().hex[:8]}"})
        return (r.get("data") or {}).get("result", "")

    def _del(self, container_id: str, term_id: str) -> None:
        try:
            self.c.request(CONTAINER + "DelTerminal", method="POST", body={"id": container_id, "uuid": term_id})
        except UgosError:
            pass

    def _ws_url(self, container_id: str, term_id: str) -> str:
        host = self.c.base.replace("https://", "wss://").replace("http://", "ws://")
        return (f"{host}{CONTAINER}Ws?containerId={container_id}&uuid={term_id}&token={self.c._token}")

    # ---------- 执行 ----------
    def run(self, container_id: str, command: str, timeout: float = 12.0,
            term_id: Optional[str] = None) -> dict:
        own = term_id is None
        tid = term_id or self._add(container_id)
        if not tid:
            return {"ok": False, "error": "AddTerminal returned empty"}
        cookie = "; ".join(f"{k}={v}" for k, v in self.c.s.cookies.get_dict().items())
        buf = ""
        ws = None
        try:
            ws = websocket.create_connection(
                self._ws_url(container_id, tid),
                header=[f"Origin: {self.c.base}", f"Cookie: {cookie}", "User-Agent: Mozilla/5.0"],
                sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=timeout,
                enable_multithread=False,
            )
            def send(text: str):
                ws.send(json.dumps({"type": "docker-terminal",
                                    "data": {"code": 200, "msg": "", "text": text,
                                             "columns": self.cols, "rows": self.rows}}))
            send("")                      # init
            time.sleep(0.5)
            send(f"export TERM=dumb; {command}; printf '\\n%s\\n' 'EN''DMARK'\n")
            t0 = time.time()
            while time.time() - t0 < timeout:
                try:
                    m = ws.recv()
                except Exception:
                    break
                if not m:
                    continue
                try:
                    txt = json.loads(m).get("data", {}).get("text", "")
                except Exception:
                    txt = ""
                buf += txt
                if "\nENDMARK" in _clean(buf):
                    break
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": buf[-400:]}
        finally:
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass
            if own:
                self._del(container_id, tid)

        out = _clean(buf)
        idx = out.find("\nENDMARK")
        if idx >= 0:
            out = out[:idx]
        # 去掉终端对输入行的回显
        pos = out.find(command)
        if pos >= 0:
            out = out[pos + len(command):]
            out = re.sub(r"^[^\n]*\n", "", out, count=1)
        return {"ok": True, "output": out.strip(), "term": tid}

    # ---------- 归属 ----------
    def listening_ports(self, container_id: str, timeout: float = 15.0) -> dict:
        """在容器内枚举「本容器进程」监听的 TCP 端口。

        容器有独立 PID namespace：/proc/net/tcp 显示的是共享 netns 的全部端口，
        但扫描 /proc/*/fd 只能命中本容器的进程，从而得到归属。
        """
        import base64
        py = r'''
import os,json
def inodes():
    m={}
    for f in ("/proc/net/tcp","/proc/net/tcp6"):
        try: lines=open(f).read().splitlines()[1:]
        except Exception: continue
        for ln in lines:
            p=ln.split()
            if len(p)<10 or p[3]!="0A": continue
            m[p[9]]=int(p[1].split(":")[1],16)
    return m
i2p=inodes(); res={}
for d in os.listdir("/proc"):
    if not d.isdigit(): continue
    try: fds=os.listdir("/proc/%s/fd"%d)
    except Exception: continue
    ports=set()
    for fd in fds:
        try: t=os.readlink("/proc/%s/fd/%s"%(d,fd))
        except Exception: continue
        if t.startswith("socket:["):
            ino=t[8:-1]
            if ino in i2p: ports.add(i2p[ino])
    if ports: res[d]=sorted(ports)
print(json.dumps(res))
'''
        b64 = base64.b64encode(py.encode()).decode()
        probe = self.run(container_id, "command -v python3 || command -v python || echo NOPY", timeout=8)
        out = (probe.get("output") or "")
        pybin = "python3" if "python3" in out else ("python" if "python" in out and "NOPY" not in out else "")
        if pybin:
            cmd = f"{pybin} -c \"import base64;exec(base64.b64decode('{b64}').decode())\""
        else:
            cmd = SH_PORTS
        r2 = self.run(container_id, cmd, timeout=timeout)
        return {"ok": r2.get("ok"), "raw": r2.get("output", ""), "parsed": _parse_ports(r2.get("output", ""))}


def _clean(s: str) -> str:
    s = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)      # ANSI
    s = s.replace("\r", "")
    return s


def _parse_ports(text: str):
    """解析两种输出：
    - python: {"pid": [ports]}
    - shell : "P <pid> <port>" 每行
    """
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    res = {}
    for ln in (text or "").splitlines():
        mm = re.match(r"\s*P\s+(\d+)\s+(\d+)\s*$", ln)
        if mm:
            res.setdefault(mm.group(1), [])
            if int(mm.group(2)) not in res[mm.group(1)]:
                res[mm.group(1)].append(int(mm.group(2)))
    return res or None


SH_PORTS = r""": > /tmp/__i2p; for f in /proc/net/tcp /proc/net/tcp6; do awk 'NR>1&&$4=="0A"{print $2" "$10}' $f 2>/dev/null; done | while read a b; do p=${a##*:}; echo "$b $((0x$p))" ; done > /tmp/__i2p; for d in /proc/[0-9]*; do pid=${d#/proc/}; for fd in $d/fd/*; do t=$(readlink $fd 2>/dev/null)||continue; case "$t" in socket:\[*) ino=${t#socket:[}; ino=${ino%]}; pr=$(awk -v i="$ino" '$1==i{print $2;exit}' /tmp/__i2p); [ -n "$pr" ] && echo "P $pid $pr";; esac; done; done | sort -u; rm -f /tmp/__i2p"""
