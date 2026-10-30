#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 连接 + schema 迁移（v2 数据底座）。"""
from __future__ import annotations

import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "state", "ugnas_bridge.db")
DB_PATH = os.environ.get("UGNAS_BRIDGE_DB", DEFAULT_DB)
SCHEMA_VERSION = 1


def db_path() -> str:
    return DB_PATH


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


MIGRATIONS = {
    1: [
        "CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, enc TEXT NOT NULL, salt TEXT NOT NULL, ts INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), pw TEXT NOT NULL, created_at INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS apps(id INTEGER PRIMARY KEY AUTOINCREMENT, container_id TEXT, name TEXT, net TEXT, ports TEXT, source TEXT, state TEXT, discovered_at INTEGER, UNIQUE(container_id,name))",
        "CREATE TABLE IF NOT EXISTS cards(only_name TEXT PRIMARY KEY, item_id TEXT, title TEXT, port INTEGER, url TEXT, lan_url TEXT, icon TEXT, group_id TEXT, synced_at INTEGER)",
        "CREATE TABLE IF NOT EXISTS sync_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, mode TEXT, total INTEGER, ok INTEGER, fail INTEGER, snapshot_path TEXT, detail TEXT)",
        "CREATE TABLE IF NOT EXISTS health(app TEXT PRIMARY KEY, port INTEGER, up INTEGER, latency_ms INTEGER, checked_at INTEGER)",
        "CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, actor TEXT, action TEXT, target TEXT, result TEXT)",
    ],
}


def init_db() -> None:
    c = connect()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        cur = int(row["version"]) if row else 0
        for v in sorted(MIGRATIONS):
            if v > cur:
                for stmt in MIGRATIONS[v]:
                    c.execute(stmt)
                cur = v
        c.execute("DELETE FROM schema_version")
        c.execute("INSERT INTO schema_version(version) VALUES(?)", (cur,))
        c.commit()
    finally:
        c.close()


def audit(action: str, target: str = "", result: str = "ok", actor: str = "admin") -> None:
    import time
    c = connect()
    try:
        with c:
            c.execute("INSERT INTO audit(ts,actor,action,target,result) VALUES(?,?,?,?,?)",
                      (int(time.time()), actor, action, target, result))
    finally:
        c.close()
