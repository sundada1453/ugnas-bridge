#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宿主端口探测解析单测（P0 四态兜底）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from discover.host_probe import parse_listen_ports  # noqa: E402


def test_parse_proc_net_tcp():
    text = """00000000:1F90
00000000:11D7
0100007F:0016
00000000000000000000000000000000:147C
"""
    assert parse_listen_ports(text) == [22, 4567, 5244, 8080], parse_listen_ports(text)
    print("test_parse_proc_net_tcp PASS")


if __name__ == "__main__":
    test_parse_proc_net_tcp()
