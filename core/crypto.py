#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机器绑定密钥 + AES-GCM 配置加密（凭据落盘用，绝不明文）。"""
from __future__ import annotations
import base64, hashlib, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def machine_seed() -> bytes:
    parts = []
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            parts.append(open(p, "rb").read().strip())
        except Exception:
            pass
    parts.append(os.uname().nodename.encode())
    return b"|".join(parts) or b"ugnas-bridge-fallback"


def derive_key(salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", machine_seed(), salt, 200_000, dklen=32)


def encrypt(plaintext: str, salt: bytes) -> str:
    key = derive_key(salt)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    return base64.b64encode(iv + ct).decode()


def decrypt(blob: str, salt: bytes) -> str:
    raw = base64.b64decode(blob)
    iv, ct = raw[:12], raw[12:]
    return AESGCM(derive_key(salt)).decrypt(iv, ct, None).decode()
