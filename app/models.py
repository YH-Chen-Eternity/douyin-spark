import json
from datetime import datetime, timezone

from app.extensions import db


def _utc_to_local_text(value):
    """RunLog.created_at 存的是 UTC，展示时换成容器时区。

    以前直接 strftime，界面上看到的日志时间比 docker logs 少 8 小时，排查问题很误导。
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        from app.config import TZ

        value = value.astimezone(ZoneInfo(TZ))
    except Exception:
        pass
    return value.strftime("%m-%d %H:%M:%S")


def _load_json(raw, default):
    if not raw:
        return list(default)
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return value
    except Exception:
        pass
    return list(default)


class Account(db.Model):
    """一个托管的抖音账号。所有业务数据都以 account_id 隔离。"""

    __tablename__ = "account"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.Integer, unique=True, nullable=False)  # 1 / 2
    label = db.Column(db.String(32), nullable=False, default="")

    # offline | logging_in | online | expired | error
    status = db.Column(db.String(16), nullable=False, default="offline")
    nickname = db.Column(db.String(64), nullable=False, default="")
    avatar = db.Column(db.String(512), nullable=False, default="")
    driver = db.Column(db.String(32), nullable=False, default="playwright")
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=False, default="")

    # ---- 定时任务 ----
    task_enabled = db.Column(db.Boolean, nullable=False, default=False)
    send_times = db.Column(db.Text, nullable=False, default='["21:00"]')
    message_pool = db.Column(db.Text, nullable=False, default='["续个火花~"]')
    # random | rotate
    message_mode = db.Column(db.String(16), nullable=False, default="random")
    rotate_index = db.Column(db.Integer, nullable=False, default=0)
    jitter_seconds = db.Column(db.Integer, nullable=False, default=20)
    dry_run = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    friends = db.relationship(
        "Friend", backref="account", cascade="all, delete-orphan", lazy="dynamic"
    )

    # ---- helpers ----
    @property
    def times(self):
        return _load_json(self.send_times, [])

    @times.setter
    def times(self, value):
        cleaned = []
        for item in value or []:
            item = str(item).strip()
            parts = item.split(":")
            if len(parts) != 2:
                continue
            h, m = parts
            if not (h.isdigit() and m.isdigit()):
                continue
            h, m = int(h), int(m)
            if 0 <= h <= 23 and 0 <= m <= 59:
                text = f"{h:02d}:{m:02d}"
                if text not in cleaned:
                    cleaned.append(text)
        cleaned.sort()
        self.send_times = json.dumps(cleaned, ensure_ascii=False)

    @property
    def messages(self):
        return _load_json(self.message_pool, [])

    @messages.setter
    def messages(self, value):
        cleaned = [str(x).strip() for x in (value or []) if str(x).strip()]
        self.message_pool = json.dumps(cleaned, ensure_ascii=False)

    @property
    def profile_dir(self):
        from app.config import PROFILE_DIR

        return str(PROFILE_DIR / f"account_{self.id}")

    def to_dict(self, include_settings=True):
        data = {
            "id": self.id,
            "slot": self.slot,
            "label": self.label,
            "status": self.status,
            "nickname": self.nickname,
            "avatar": self.avatar,
            "driver": self.driver,
            "last_login_at": (
                self.last_login_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.last_login_at
                else None
            ),
            "last_error": self.last_error,
            "friend_count": self.friends.filter_by(enabled=True).count(),
        }
        if include_settings:
            data.update(
                {
                    "task_enabled": self.task_enabled,
                    "send_times": self.times,
                    "message_pool": self.messages,
                    "message_mode": self.message_mode,
                    "jitter_seconds": self.jitter_seconds,
                    "dry_run": self.dry_run,
                }
            )
        return data


class Friend(db.Model):
    """账号下的好友。唯一约束 (account_id, ref) 保证账号间互不干扰。"""

    __tablename__ = "friend"
    __table_args__ = (db.UniqueConstraint("account_id", "ref", name="uq_account_friend"),)

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    ref = db.Column(db.String(128), nullable=False)  # 抖音侧标识或昵称
    nickname = db.Column(db.String(128), nullable=False, default="")
    avatar = db.Column(db.String(512), nullable=False, default="")
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    custom_message = db.Column(db.Text, nullable=False, default="")
    note = db.Column(db.String(128), nullable=False, default="")

    last_sent_at = db.Column(db.DateTime, nullable=True)
    last_status = db.Column(db.String(16), nullable=False, default="")  # ok | fail | skip
    last_result = db.Column(db.Text, nullable=False, default="")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "ref": self.ref,
            "nickname": self.nickname or self.ref,
            "avatar": self.avatar,
            "enabled": self.enabled,
            "custom_message": self.custom_message,
            "note": self.note,
            "last_sent_at": (
                self.last_sent_at.strftime("%m-%d %H:%M:%S")
                if self.last_sent_at
                else None
            ),
            "last_status": self.last_status,
            "last_result": self.last_result,
        }


class RunLog(db.Model):
    __tablename__ = "run_log"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    level = db.Column(db.String(16), nullable=False, default="info")
    message = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "level": self.level,
            "message": self.message,
            "created_at": _utc_to_local_text(self.created_at),
        }
