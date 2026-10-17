"""每日定点任务调度。

每个账号的每个时间点对应一个独立的 APScheduler cron job，
job id 形如 acct1_2100，账号之间不会互相影响。
"""
import random
import threading
import time
from datetime import datetime

from flask import has_app_context

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import TZ
from app.drivers import get_driver
from app.extensions import db
from app.logstore import add_log, cleanup_logs
from app.models import Account, Friend

scheduler = BackgroundScheduler(timezone=TZ, daemon=True)

# Flask app 引用（由 web.init_app 注入），供 APScheduler 后台线程建立 application context
_flask_app = None


def init_scheduler(app):
    """注入 Flask app，供后台线程建立 application context。"""
    global _flask_app
    _flask_app = app


_run_lock = threading.Lock()
_running = {}  # account_id -> True
_suspended_warned = set()  # 已经提醒过「未登录导致任务挂起」的账号


def job_id(account_id, hhmm):
    hour, minute = hhmm.split(":")
    return f"acct{account_id}_{int(hour):02d}{int(minute):02d}"


def render_message(template, friend, index):
    now = datetime.now()
    return (
        (template or "")
        .replace("{nickname}", friend.nickname or friend.ref)
        .replace("{index}", str(index))
        .replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H:%M"))
    )


def pick_message(account, friend, index):
    pool = account.messages
    if not pool:
        return ""
    if friend.custom_message.strip():
        return render_message(friend.custom_message, friend, index)
    if account.message_mode == "rotate":
        return render_message(pool[account.rotate_index % len(pool)], friend, index)
    return render_message(random.choice(pool), friend, index)


def _set_friend_result(friend, status, result):
    friend.last_status = status
    friend.last_result = result[:500]
    friend.last_sent_at = datetime.now()


def _jitter_seconds(account):
    base = max(0, int(account.jitter_seconds or 0))
    return base + random.randint(0, max(1, base // 2))


def _send_to_friend(account, friend, index):
    """给一位好友发一条消息，并把结果写进日志和好友状态。"""
    text = pick_message(account, friend, index)
    try:
        ok, message = get_driver().send_message(
            account, friend, text, dry_run=account.dry_run
        )
    except Exception as exc:  # noqa: BLE001
        ok, message = False, str(exc)

    if ok:
        _set_friend_result(friend, "ok", message)
        add_log(account.id, f"→ {friend.nickname}：{message}")
    else:
        _set_friend_result(friend, "fail", message)
        add_log(account.id, f"→ {friend.nickname}：{message}", "error")
    return ok, message


def run_account_task(account_id, reason="定时"):
    """带 application context 的入口，供 APScheduler 后台线程调用。"""
    if _flask_app is not None and not has_app_context():
        with _flask_app.app_context():
            return _run_account_task_impl(account_id, reason)
    return _run_account_task_impl(account_id, reason)


def _run_account_task_impl(account_id, reason="定时"):
    """执行一次「给所有已勾选好友发消息」。

    并发保护用 try/finally 落地：以前账号未登录 / 没有勾选好友等情况会直接 return，
    把 _running 里的标记永久留在内存里，之后每次定时都会「上一次任务还在执行，本次跳过」，
    直到重启容器为止。
    """
    with _run_lock:
        if _running.get(account_id):
            add_log(account_id, "上一次任务还在执行，本次跳过", "warn")
            return
        _running[account_id] = True

    try:
        _do_run_account_task(account_id, reason)
    except Exception as exc:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:
            pass
        add_log(account_id, f"任务异常终止：{exc}", "error")
    finally:
        with _run_lock:
            _running.pop(account_id, None)
        try:
            cleanup_logs()
        except Exception:
            pass


def _do_run_account_task(account_id, reason="定时"):
    account = db.session.get(Account, account_id)
    if account is None:
        return

    if account.status != "online":
        add_log(account_id, f"{reason}任务跳过：账号未登录（{account.status}）", "warn")
        return

    friends = (
        Friend.query.filter_by(account_id=account_id, enabled=True)
        .order_by(Friend.id.asc())
        .all()
    )
    if not friends:
        add_log(account_id, f"{reason}任务跳过：没有勾选任何好友", "warn")
        return

    pool = account.messages
    if not pool:
        add_log(account_id, f"{reason}任务跳过：消息内容为空", "warn")
        return

    driver = get_driver()

    # 动手之前先确认抖音登录态还在。
    # 掉登录时抖音页面上只有登录弹窗，私信面板永远加载不出来，旧逻辑会把这份开销
    # 变成「每位好友都报私信面板加载超时」，白跑二十分钟还看不出是掉登录。
    # 这里只是中止本次任务并写一条明确日志，不改账号状态、不动定时任务，
    # 以免预检偶发失败把正常调度也停掉。
    try:
        login_state = driver.verify(account)
    except Exception as exc:  # noqa: BLE001
        login_state = None
        add_log(account_id, f"登录态预检失败（继续尝试）：{exc}", "warn")
    if login_state is not None and login_state.get("status") != "success":
        add_log(
            account_id,
            f"{reason}任务中止：抖音登录态已失效，请打开界面重新扫码登录",
            "error",
        )
        return

    add_log(
        account_id,
        f"{reason}任务开始（{len(friends)} 位好友，{'试运行' if account.dry_run else '正式发送'}）",
    )

    # 先把浏览器 + 私信面板预热好。抖音前端冷启动要十几秒才下发 im 模块，
    # 不预热的话这份开销全压在列表里的第一个人身上，它就是那个「有时发不出去」的好友。
    try:
        warmup = getattr(driver, "warmup", None)
        if warmup is not None:
            warmup(account)
    except Exception as exc:  # noqa: BLE001
        add_log(account_id, f"预热失败（不影响后续逐个尝试）：{exc}", "warn")

    ok_count = 0
    fail_count = 0
    failed = []
    for index, friend in enumerate(friends, start=1):
        ok, message = _send_to_friend(account, friend, index)
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            failed.append((friend, index))
        if account.message_mode == "rotate":
            account.rotate_index = (account.rotate_index + 1) % len(pool)
        db.session.commit()
        if index < len(friends):
            time.sleep(_jitter_seconds(account))

    # 前面失败的好友补一次：此时浏览器已经预热完成，成功率明显更高
    if failed:
        add_log(
            account_id,
            f"有 {len(failed)} 位好友没发成功，浏览器已预热，重试一次",
            "warn",
        )
        time.sleep(_jitter_seconds(account) + 5)
        for pos, (friend, index) in enumerate(failed, start=1):
            ok, _ = _send_to_friend(account, friend, index)
            if ok:
                ok_count += 1
                fail_count -= 1
            if account.message_mode == "rotate":
                account.rotate_index = (account.rotate_index + 1) % len(pool)
            db.session.commit()
            if pos < len(failed):
                time.sleep(_jitter_seconds(account))

    add_log(account_id, f"任务结束：成功 {ok_count}，失败 {fail_count}")


def sync_account_jobs(account=None):
    """把数据库里的定时设置同步到调度器。"""
    accounts = [account] if account is not None else Account.query.all()

    for acc in accounts:
        desired = {}
        if acc.task_enabled and acc.status == "online":
            _suspended_warned.discard(acc.id)
            for hhmm in acc.times:
                desired[job_id(acc.id, hhmm)] = hhmm
        elif acc.task_enabled and acc.status != "online":
            # 每次保存设置都提醒一遍太吵，只在状态变化时记一条
            if acc.id not in _suspended_warned:
                _suspended_warned.add(acc.id)
                add_log(acc.id, "定时任务已启用但账号未登录，任务暂挂起", "warn")

        existing = {
            job.id for job in scheduler.get_jobs() if job.id.startswith(f"acct{acc.id}_")
        }

        for stale in existing - set(desired):
            scheduler.remove_job(stale)

        for jid, hhmm in desired.items():
            hour, minute = hhmm.split(":")
            trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=TZ)
            if jid in existing:
                scheduler.reschedule_job(jid, trigger=trigger)
            else:
                scheduler.add_job(
                    run_account_task,
                    trigger=trigger,
                    id=jid,
                    args=[acc.id],
                    kwargs={"reason": "定时"},
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                add_log(acc.id, f"已注册每日 {hhmm} 的定时任务")


def next_run_text(account):
    times = []
    for job in scheduler.get_jobs():
        if job.id.startswith(f"acct{account.id}_"):
            nxt = getattr(job, "next_run_time", None)
            if nxt:
                times.append(nxt.strftime("%m-%d %H:%M"))
    return min(times) if times else None


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
