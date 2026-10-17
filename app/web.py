import threading
import time
from datetime import datetime

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import desc

from app.config import DRIVER, OTP_SECRET, OTP_SESSION_HOURS, TMP_DIR, TZ
from app.drivers import get_driver
from app.extensions import db
from app.logstore import add_log
from app.models import Account, Friend, RunLog
from app.otp import verify as verify_totp
from app.services.scheduler import (
    init_scheduler,
    next_run_text,
    run_account_task,
    start_scheduler,
    sync_account_jobs,
)

bp = Blueprint("web", __name__)

# ---------------------------------------------------------------- OTP 认证
@bp.before_request
def require_otp():
    """启用 OTP 后，所有请求（除登录页/静态资源）都要先通过二次验证。"""
    if not OTP_SECRET:
        return None
    if request.path == "/otp_login":
        return None
    # 会话仍有效
    if session.get("otp_ok"):
        ts = session.get("otp_time", 0)
        if int(time.time()) - int(ts) < OTP_SESSION_HOURS * 3600:
            return None
        session.pop("otp_ok", None)
        session.pop("otp_time", None)
    # API / 文件请求返回 401，页面请求重定向到登录页
    if request.path.startswith("/api/") or request.path.startswith("/files/"):
        return jsonify({"ok": False, "message": "需要 OTP 认证"}), 401
    return redirect(url_for("web.otp_login"))


@bp.route("/otp_login", methods=["GET", "POST"])
def otp_login():
    if not OTP_SECRET:
        return redirect(url_for("web.index"))
    error = ""
    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        if verify_totp(OTP_SECRET, code):
            session["otp_ok"] = True
            session["otp_time"] = int(time.time())
            return redirect(url_for("web.index"))
        error = "口令错误或已过期，请重试"
    return render_template("otp_login.html", error=error)

STATUS_TEXT = {
    "offline": "未登录",
    "logging_in": "等待扫码",
    "online": "已登录",
    "expired": "登录失效",
    "error": "异常",
}


def ok(data=None, **kwargs):
    payload = {"ok": True, "data": data}
    payload.update(kwargs)
    return jsonify(payload)


def fail(message, code=400):
    return jsonify({"ok": False, "message": message}), code


def get_account(account_id):
    account = db.session.get(Account, account_id)
    if account is None:
        return None
    return account


# ---------------------------------------------------------------- 页面
@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/files/<path:filename>")
def files(filename):
    return send_from_directory(str(TMP_DIR), filename)


@bp.route("/api/system")
def system():
    return ok(
        {
            "driver": DRIVER,
            "timezone": TZ,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


# ---------------------------------------------------------------- 账号
@bp.route("/api/accounts")
def list_accounts():
    accounts = Account.query.order_by(Account.slot.asc()).all()
    data = []
    for acc in accounts:
        item = acc.to_dict()
        item["status_text"] = STATUS_TEXT.get(acc.status, acc.status)
        item["next_run"] = next_run_text(acc)
        data.append(item)
    return ok(data)


@bp.route("/api/accounts/<int:account_id>", methods=["POST"])
def update_account(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    if "label" in body:
        account.label = str(body["label"])[:32]
    db.session.commit()
    return ok(account.to_dict())


# ---------------------------------------------------------------- 登录
@bp.route("/api/accounts/<int:account_id>/login/start", methods=["POST"])
def login_start(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)

    try:
        result = get_driver().start_login(account)
    except Exception as exc:  # noqa: BLE001
        account.status = "error"
        account.last_error = str(exc)[:500]
        db.session.commit()
        return fail(str(exc))

    if result.get("status") == "success":
        account.status = "online"
        account.nickname = result.get("nickname", "")
        account.last_login_at = datetime.now()
        account.last_error = ""
        db.session.commit()
        sync_account_jobs(account)
        add_log(account_id, "登录成功（复用了本地会话）")
    else:
        account.status = "logging_in"
        db.session.commit()

    return ok(
        {
            "status": account.status,
            "status_text": STATUS_TEXT.get(account.status, account.status),
            "qr_url": result.get("qr_url"),
            "message": result.get("message", ""),
        }
    )


@bp.route("/api/accounts/<int:account_id>/login/poll")
def login_poll(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)

    try:
        result = get_driver().query_login(account)
    except Exception as exc:  # noqa: BLE001
        return ok({"status": "pending", "message": str(exc)})

    if result.get("status") == "success":
        first = account.status != "online"
        account.status = "online"
        account.nickname = result.get("nickname") or account.nickname
        account.last_login_at = datetime.now()
        account.last_error = ""
        db.session.commit()
        sync_account_jobs(account)
        if first:
            add_log(account_id, f"登录成功：{account.nickname or '未获取到昵称'}")
        result["status_text"] = "已登录"
    elif result.get("status") == "expired":
        account.status = "expired"
        db.session.commit()
        result["status_text"] = "登录失效"
    else:
        result["status_text"] = "等待扫码"

    return ok(result)


@bp.route("/api/accounts/<int:account_id>/login/cancel", methods=["POST"])
def login_cancel(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    try:
        get_driver().cancel_login(account)
    except Exception:
        pass
    account.status = "offline"
    db.session.commit()
    return ok({"status": account.status, "status_text": "未登录"})


@bp.route("/api/accounts/<int:account_id>/login/cookies", methods=["POST"])
def login_cookies(account_id):
    """扫码不可用时的兜底：从浏览器复制 Cookie 粘进来。"""
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    cookie_text = str(body.get("cookie", "")).strip()
    if not cookie_text:
        return fail("Cookie 不能为空")

    try:
        result = get_driver().import_cookies(account, cookie_text)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))

    if result.get("status") == "success":
        account.status = "online"
        account.nickname = result.get("nickname", "")
        account.last_login_at = datetime.now()
        account.last_error = ""
        db.session.commit()
        sync_account_jobs(account)
        add_log(account_id, "通过 Cookie 登录成功")
    return ok(result)


@bp.route("/api/accounts/<int:account_id>/login/sms/send", methods=["POST"])
def login_sms_send(account_id):
    """验证码登录第一步：填手机号并发送验证码。"""
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip()
    if not phone:
        return fail("请输入手机号")

    try:
        result = get_driver().sms_send_code(account, phone)
    except Exception as exc:  # noqa: BLE001
        account.status = "error"
        account.last_error = str(exc)[:500]
        db.session.commit()
        return fail(str(exc))

    account.status = "logging_in"
    account.last_error = ""
    db.session.commit()
    return ok(result)


@bp.route("/api/accounts/<int:account_id>/login/sms/verify", methods=["POST"])
def login_sms_verify(account_id):
    """验证码登录第二步：填验证码并登录，成功后 Cookie 自动落盘。"""
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    code = str(body.get("code", "")).strip()
    if not code:
        return fail("请输入验证码")

    try:
        result = get_driver().sms_verify(account, code)
    except Exception as exc:  # noqa: BLE001
        account.status = "error"
        account.last_error = str(exc)[:500]
        db.session.commit()
        return fail(str(exc))

    if result.get("status") == "success":
        account.status = "online"
        account.nickname = result.get("nickname", "")
        account.last_login_at = datetime.now()
        account.last_error = ""
        db.session.commit()
        sync_account_jobs(account)
        add_log(account_id, f"验证码登录成功：{account.nickname or '已登录'}")
        return ok(result)
    return ok(result)


@bp.route("/api/accounts/<int:account_id>/verify", methods=["POST"])
def verify(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    try:
        result = get_driver().verify(account)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))

    if result.get("status") == "success":
        account.status = "online"
        account.nickname = result.get("nickname") or account.nickname
        account.last_error = ""
    else:
        account.status = "expired"
    db.session.commit()
    sync_account_jobs(account)
    return ok(result)


@bp.route("/api/accounts/<int:account_id>/logout", methods=["POST"])
def logout(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    try:
        get_driver().logout(account)
    except Exception:
        pass
    account.status = "offline"
    account.nickname = ""
    account.task_enabled = False
    db.session.commit()
    sync_account_jobs(account)
    add_log(account_id, "已登出")
    return ok({"status": account.status, "status_text": "未登录"})


# ---------------------------------------------------------------- 好友
@bp.route("/api/accounts/<int:account_id>/friends")
def list_friends(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    friends = Friend.query.filter_by(account_id=account_id).order_by(Friend.id.asc()).all()
    return ok([f.to_dict() for f in friends])


@bp.route("/api/accounts/<int:account_id>/friends/refresh", methods=["POST"])
def refresh_friends(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    if account.status != "online":
        return fail("请先登录该账号")

    try:
        items = get_driver().fetch_friends(account)
    except Exception as exc:  # noqa: BLE001
        add_log(account_id, f"刷新好友失败：{exc}", "error")
        return fail(str(exc))

    added = 0
    for item in items:
        ref = str(item.get("ref") or item.get("nickname") or "").strip()
        if not ref:
            continue
        existing = Friend.query.filter_by(account_id=account_id, ref=ref).first()
        if existing is None:
            db.session.add(
                Friend(
                    account_id=account_id,
                    ref=ref,
                    nickname=str(item.get("nickname") or ref)[:128],
                    avatar=str(item.get("avatar") or "")[:512],
                )
            )
            added += 1
        else:
            existing.nickname = str(item.get("nickname") or existing.nickname)[:128]
            existing.avatar = str(item.get("avatar") or existing.avatar)[:512]
    db.session.commit()
    add_log(account_id, f"刷新好友列表完成，新增 {added} 位")
    return ok({"added": added, "total": len(items)})


@bp.route("/api/accounts/<int:account_id>/friends", methods=["POST"])
def add_friend(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    ref = str(body.get("ref") or "").strip()
    if not ref:
        return fail("请输入好友昵称或标识")

    existing = Friend.query.filter_by(account_id=account_id, ref=ref).first()
    if existing:
        return fail("该好友已存在")

    friend = Friend(
        account_id=account_id,
        ref=ref,
        nickname=str(body.get("nickname") or ref)[:128],
        enabled=bool(body.get("enabled", False)),
    )
    db.session.add(friend)
    db.session.commit()
    return ok(friend.to_dict())


@bp.route("/api/friends/<int:friend_id>", methods=["POST", "DELETE"])
def modify_friend(friend_id):
    friend = db.session.get(Friend, friend_id)
    if friend is None:
        return fail("好友不存在", 404)

    if request.method == "DELETE":
        account_id = friend.account_id
        db.session.delete(friend)
        db.session.commit()
        return ok({"deleted": friend_id, "account_id": account_id})

    body = request.get_json(silent=True) or {}
    if "enabled" in body:
        friend.enabled = bool(body["enabled"])
    if "custom_message" in body:
        friend.custom_message = str(body["custom_message"])[:1000]
    if "nickname" in body:
        friend.nickname = str(body["nickname"])[:128]
    db.session.commit()
    return ok(friend.to_dict())


@bp.route("/api/accounts/<int:account_id>/friends/toggle-all", methods=["POST"])
def toggle_all_friends(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))
    Friend.query.filter_by(account_id=account_id).update({"enabled": enabled})
    db.session.commit()
    return ok({"enabled": enabled})


# ---------------------------------------------------------------- 设置
@bp.route("/api/accounts/<int:account_id>/settings", methods=["POST"])
def update_settings(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}

    if "send_times" in body:
        account.times = body["send_times"] or []
    if "message_pool" in body:
        account.messages = body["message_pool"] or []
    if "message_mode" in body:
        account.message_mode = str(body["message_mode"]) if body["message_mode"] in (
            "random",
            "rotate",
        ) else "random"
    if "jitter_seconds" in body:
        account.jitter_seconds = max(0, min(3600, int(body["jitter_seconds"] or 0)))
    if "dry_run" in body:
        account.dry_run = bool(body["dry_run"])
    if "task_enabled" in body:
        account.task_enabled = bool(body["task_enabled"])
        if account.task_enabled and account.status != "online":
            db.session.commit()
            sync_account_jobs(account)
            return ok(
                account.to_dict(),
                message="任务已保存，但账号未登录，登录后才会真正执行",
            )

    db.session.commit()
    sync_account_jobs(account)
    return ok(account.to_dict())


@bp.route("/api/accounts/<int:account_id>/task/toggle", methods=["POST"])
def toggle_task(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", not account.task_enabled))

    if enabled and account.status != "online":
        return fail("账号未登录，无法启用定时任务")

    account.task_enabled = enabled
    db.session.commit()
    sync_account_jobs(account)
    add_log(account_id, f"定时任务已{'启用' if enabled else '停用'}")
    return ok({"task_enabled": enabled, "next_run": next_run_text(account)})


@bp.route("/api/accounts/<int:account_id>/run-now", methods=["POST"])
def run_now(account_id):
    account = get_account(account_id)
    if account is None:
        return fail("账号不存在", 404)
    if account.status != "online":
        return fail("账号未登录")

    from flask import current_app

    app = current_app._get_current_object()

    def _worker():
        with app.app_context():
            run_account_task(account_id, reason="手动")

    threading.Thread(target=_worker, daemon=True).start()
    return ok({"started": True})


# ---------------------------------------------------------------- 日志
@bp.route("/api/accounts/<int:account_id>/logs")
def list_logs(account_id):
    logs = (
        RunLog.query.filter_by(account_id=account_id)
        .order_by(desc(RunLog.id))
        .limit(200)
        .all()
    )
    return ok([log.to_dict() for log in reversed(logs)])


@bp.route("/api/accounts/<int:account_id>/logs", methods=["DELETE"])
def clear_logs(account_id):
    RunLog.query.filter_by(account_id=account_id).delete()
    db.session.commit()
    return ok({"cleared": True})


def init_app(app):
    app.register_blueprint(bp)
    init_scheduler(app)
    start_scheduler()
    with app.app_context():
        sync_account_jobs()
