"""演示用驱动：不碰真实抖音，用于验证界面、调度、日志这条链路是否通畅。

在 docker-compose 里把 SPARK_DRIVER 设成 mock 即可启用。
扫码流程：点「开始登录」后等 10 秒，状态自动变成已登录。
"""
import struct
import threading
import time
import zlib
from pathlib import Path

from app.config import TMP_DIR
from app.drivers.base import BaseDriver, LoginResult

MOCK_FRIENDS = [
    {"ref": "mock_1001", "nickname": "小张同学", "avatar": ""},
    {"ref": "mock_1002", "nickname": "阿May", "avatar": ""},
    {"ref": "mock_1003", "nickname": "老王", "avatar": ""},
    {"ref": "mock_1004", "nickname": "球球", "avatar": ""},
    {"ref": "mock_1005", "nickname": "Lily", "avatar": ""},
    {"ref": "mock_1006", "nickname": "夜跑搭子", "avatar": ""},
    {"ref": "mock_1007", "nickname": "饭搭子", "avatar": ""},
    {"ref": "mock_1008", "nickname": "摸鱼小分队", "avatar": ""},
]


def _png_chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_placeholder_png(path, size=320, cell=10):
    """不引入 Pillow，手写一张棋盘格 PNG 当占位二维码。"""
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.append(0 if ((x // cell) + (y // cell)) % 2 == 0 else 255)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _png_chunk(b"IEND", b"")
    Path(path).write_bytes(png)


class MockDriver(BaseDriver):
    name = "mock"

    def __init__(self):
        self._state = {}
        self._lock = threading.Lock()

    def _slot(self, account_id):
        with self._lock:
            return self._state.setdefault(account_id, {"status": "offline", "at": 0})

    def start_login(self, account, **kwargs):
        state = self._slot(account.id)
        state["status"] = "pending"
        state["at"] = time.time()
        path = TMP_DIR / f"qr_{account.id}.png"
        write_placeholder_png(path)
        return LoginResult(
            "pending",
            qr_url=f"/files/qr_{account.id}.png?v={int(time.time())}",
            message="演示模式：10 秒后自动变为已登录",
        ).to_dict()

    def query_login(self, account, **kwargs):
        state = self._slot(account.id)
        if state["status"] == "online":
            return LoginResult("success", nickname=f"演示账号{account.slot}").to_dict()
        if state["status"] == "pending" and time.time() - state["at"] > 10:
            state["status"] = "online"
            return LoginResult("success", nickname=f"演示账号{account.slot}").to_dict()
        return LoginResult("pending", message="等待扫码中（演示）").to_dict()

    def cancel_login(self, account):
        self._slot(account.id)["status"] = "offline"
        return {"status": "cancelled"}

    def verify(self, account):
        state = self._slot(account.id)
        if state["status"] == "online":
            return LoginResult("success", nickname=f"演示账号{account.slot}").to_dict()
        return LoginResult("expired", message="演示模式：尚未登录").to_dict()

    def import_cookies(self, account, cookie_text):
        state = self._slot(account.id)
        state["status"] = "online"
        return LoginResult("success", nickname=f"演示账号{account.slot}").to_dict()

    def sms_send_code(self, account, phone):
        return {"status": "code_sent", "message": "验证码已发送（演示模式）"}

    def sms_verify(self, account, code):
        self._slot(account.id)["status"] = "online"
        return LoginResult("success", nickname=f"演示账号{account.slot}").to_dict()

    def fetch_friends(self, account):
        if self._slot(account.id)["status"] != "online":
            raise RuntimeError("演示模式：请先登录")
        return list(MOCK_FRIENDS)

    def warmup(self, account):
        return {"status": "ready", "cold": False}

    def send_message(self, account, friend, text, dry_run=False):
        if self._slot(account.id)["status"] != "online":
            return False, "演示模式：未登录"
        time.sleep(0.3)
        if dry_run:
            return True, "试运行：未真正发送"
        return True, f"已发送「{text[:20]}」（演示）"

    def logout(self, account):
        self._slot(account.id)["status"] = "offline"
        return {"status": "offline"}

    def shutdown(self, account):
        with self._lock:
            self._state.pop(account.id, None)
