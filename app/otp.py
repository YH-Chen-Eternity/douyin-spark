# -*- coding: utf-8 -*-
"""TOTP（RFC 6238）动态口令校验 —— 纯标准库实现，无第三方依赖。

用法：
    from app.otp import verify as verify_totp
    if verify_totp(SECRET, "123456"): ...
"""
import base64
import hashlib
import hmac
import struct
import time


def _b32decode(s):
    s = s.strip().upper().replace(" ", "")
    pad = (-len(s)) % 8
    return base64.b32decode(s + "=" * pad)


def totp_at(secret, counter, digits=6):
    key = _b32decode(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF)
    return str(binary % (10 ** digits)).zfill(digits)


def verify(secret, code, window=1):
    """校验 6 位 TOTP，容忍 ±window 个时间窗口（时钟偏移）。"""
    code = str(code or "").strip()
    if not code.isdigit():
        return False
    now = int(time.time()) // 30
    for i in range(-window, window + 1):
        if hmac.compare_digest(totp_at(secret, now + i), code):
            return True
    return False
