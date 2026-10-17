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

SECRET_KEY = os.environ.get("SECRET_KEY", "douyin-spark-local-key")

# ---- OTP（TOTP）二次验证 ----
# 设置 SPARK_OTP_SECRET（Base32 密钥）后，访问界面/API 需先输 6 位动态口令。
OTP_SECRET = os.environ.get("SPARK_OTP_SECRET", "").strip()
OTP_SESSION_HOURS = int(os.environ.get("SPARK_OTP_SESSION_HOURS", "12"))

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
