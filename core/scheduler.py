#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简后台调度：周期性执行健康探测（守护线程）。"""
from __future__ import annotations
import threading


class PeriodicRunner:
    def __init__(self, fn, interval: int = 300, name: str = "periodic"):
        self.fn = fn
        self.interval = max(30, int(interval))
        self.name = name
        self._stop = threading.Event()
        self._t = None

    def start(self):
        if self._t and self._t.is_alive():
            return

        def loop():
            while not self._stop.is_set():
                try:
                    self.fn()
                except Exception:
                    pass
                self._stop.wait(self.interval)

        self._t = threading.Thread(target=loop, name=self.name, daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()
