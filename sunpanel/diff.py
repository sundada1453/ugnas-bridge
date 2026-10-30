#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四态 diff 引擎（F3-2）

匹配键：only_name = "ugnas-<port>"（与 v1 一致），并校验端口一致。
状态：
  new      发现结果未命中任何既有卡片
  update   命中卡片但 title/icon/group 有差异
  same     命中且字段一致
  expired  既有卡片未命中任何发现结果（也不在手动绑定池）
顺序：new → update → expired → same。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

STATE_ORDER = ("new", "update", "expired", "same")


def only_name(port: int) -> str:
    return f"ugnas-{port}"


@dataclass
class Card:
    only_name: str
    port: int
    title: str = ""
    icon: str = ""
    group_id: str = ""
    url: str = ""
    lan_url: str = ""


@dataclass
class DiscoveredApp:
    name: str
    port: int
    source: str = "portMapping"
    icon: str = ""
    group_id: str = ""

    @property
    def only_name(self) -> str:
        return only_name(self.port)


@dataclass
class DiffRow:
    state: str
    only_name: str
    port: int
    title: str
    old: Dict[str, str] = field(default_factory=dict)
    new: Dict[str, str] = field(default_factory=dict)
    changes: List[str] = field(default_factory=list)
    reason: str = ""


def _diff_fields(card: Card, app: DiscoveredApp) -> List[str]:
    ch = []
    if (card.title or "") != (app.name or ""):
        ch.append("title")
    if app.icon and (card.icon or "") != app.icon:
        ch.append("icon")
    if app.group_id and (card.group_id or "") != app.group_id:
        ch.append("group")
    return ch


def diff(discovered: Iterable[DiscoveredApp], cards: Iterable[Card],
         manual_ports: Optional[Iterable[int]] = None) -> List[DiffRow]:
    """返回四态行列表。manual_ports 为人工绑定/宿主服务端口池（不判 expired）。"""
    manual = set(manual_ports or [])
    by_port: Dict[int, DiscoveredApp] = {a.port: a for a in discovered if a.port}
    cards_by_port: Dict[int, Card] = {c.port: c for c in cards}

    rows: List[DiffRow] = []

    for port, app in by_port.items():
        card = cards_by_port.get(port)
        if card is None:
            rows.append(DiffRow("new", app.only_name, port, app.name,
                                new={"title": app.name, "icon": app.icon, "group": app.group_id},
                                reason="no existing card"))
        else:
            ch = _diff_fields(card, app)
            if ch:
                rows.append(DiffRow("update", card.only_name, port, app.name,
                                    old={"title": card.title, "icon": card.icon, "group": card.group_id},
                                    new={"title": app.name, "icon": app.icon or card.icon,
                                         "group": app.group_id or card.group_id},
                                    changes=ch, reason="fields differ: " + ",".join(ch)))
            else:
                rows.append(DiffRow("same", card.only_name, port, card.title or app.name,
                                    reason="identical"))

    for port, card in cards_by_port.items():
        if port in by_port:
            continue
        if port in manual:
            rows.append(DiffRow("same", card.only_name, port, card.title,
                                reason="manual/host-service binding"))
        else:
            rows.append(DiffRow("expired", card.only_name, port, card.title,
                                old={"title": card.title, "url": card.url},
                                reason="no running app matched (only_name+port)"))

    rows.sort(key=lambda r: (STATE_ORDER.index(r.state), r.port))
    return rows


def summarize(rows: List[DiffRow]) -> Dict[str, int]:
    out = {s: 0 for s in STATE_ORDER}
    for r in rows:
        out[r.state] = out.get(r.state, 0) + 1
    return out
