#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标三级回退（F3-3）：dashboard-icons → 应用 favicon（本地缓存）→ 手动。"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional, Tuple

CDN = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{slug}.svg"
ALIASES = {
    "emby": "emby", "openlist": "openlist", "alist": "alist", "siyuan": "siyuan",
    "vaultwarden": "vaultwarden", "jellyfin": "jellyfin", "plex": "plex",
    "nextcloud": "nextcloud", "immich": "immich", "gitea": "gitea",
    "claude": "claude", "openai": "openai", "telegram": "telegram",
}


def kebab(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return ALIASES.get(s, s)


def resolve(name: str, port: int,
            cdn_exists: Optional[Callable[[str], bool]] = None,
            favicon_fetch: Optional[Callable[[int], Optional[bytes]]] = None,
            cache_dir: str = "") -> Tuple[str, str]:
    """返回 (icon_url, source)。source in dashboard|favicon|manual。"""
    slug = kebab(name)
    if slug and cdn_exists and cdn_exists(slug):
        return CDN.format(slug=slug), "dashboard"
    if favicon_fetch:
        data = favicon_fetch(port)
        if data:
            d = cache_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "icons")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, f"app-{port}.png")
            with open(p, "wb") as f:
                f.write(data)
            return f"file://{p}", "favicon"
    return "", "manual"
