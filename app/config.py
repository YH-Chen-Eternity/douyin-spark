import os
from pathlib import Path


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = DATA_DIR / "profiles"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

TMP_DIR = DATA_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "spark.db"

# playwright | mock
DRIVER = os.environ.get("SPARK_DRIVER", "playwright").strip().lower()

# 抖音对无头浏览器有严格风控，会返回"验证码中间页"而非二维码。
# 因此默认用有头模式，配合容器内的 Xvfb 虚拟显示（见 entrypoint.sh）。
# 仅在本地有真实显示器的场景才建议设成 false 之外的值。
HEADLESS = _as_bool(os.environ.get("HEADLESS", "false"), False)

TZ = os.environ.get("TZ", "Asia/Shanghai")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))

# ---- OTP（TOTP）二次验证 ----
# 设置 SPARK_OTP_SECRET（Base32 密钥）后，访问界面/API 需先输 6 位动态口令。
OTP_SECRET = os.environ.get("SPARK_OTP_SECRET", "").strip()
OTP_SESSION_HOURS = int(os.environ.get("SPARK_OTP_SESSION_HOURS", "12"))

# Flask 会话签名密钥。
# 这里不能使用固定的默认值：会话 Cookie 里保存着「OTP 已通过」的标记，
# 密钥一旦是源码里公开的常量，任何人都能伪造会话绕过 OTP（2026-10 安全审计确认过）。
# - 启用 OTP 时必须显式设置 SECRET_KEY，否则直接拒绝启动（fail closed）；
# - 未启用 OTP 时生成随机临时密钥，重启后旧会话失效，避免带着固定密钥裸奔。
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if OTP_SECRET:
        raise RuntimeError(
            "启用了 SPARK_OTP_SECRET 但没有设置 SECRET_KEY，拒绝启动。"
            "请生成随机密钥并写入环境变量，例如：openssl rand -hex 32"
        )
    import secrets as _secrets

    SECRET_KEY = _secrets.token_hex(32)
    print(
        "警告：未设置 SECRET_KEY，已生成随机临时密钥（重启后现有登录会话会失效）",
        flush=True,
    )

# 单次驱动操作的默认超时（秒）
OP_TIMEOUT = int(os.environ.get("OP_TIMEOUT", "90"))

# 扫码登录等待上限（秒）
LOGIN_TIMEOUT = int(os.environ.get("LOGIN_TIMEOUT", "300"))

SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)
