import threading
from datetime import datetime

from app.extensions import db
from app.models import RunLog

_lock = threading.Lock()


def add_log(account_id, message, level="info"):
    """写运行日志。同时输出到 stdout，方便 docker logs 查看。"""
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}][acct:{account_id}][{level}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass

    with _lock:
        try:
            db.session.add(
                RunLog(account_id=account_id, level=level, message=str(message))
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def cleanup_logs(keep=500):
    """每个账号最多保留 keep 条日志，避免 SQLite 无限膨胀。"""
    from sqlalchemy import func

    try:
        rows = db.session.query(RunLog.account_id, func.count(RunLog.id)).group_by(
            RunLog.account_id
        ).all()
        for account_id, count in rows:
            if count and count > keep:
                excess = count - keep
                ids = (
                    db.session.query(RunLog.id)
                    .filter(RunLog.account_id == account_id)
                    .order_by(RunLog.id.asc())
                    .limit(excess)
                    .all()
                )
                id_list = [i[0] for i in ids]
                if id_list:
                    db.session.query(RunLog).filter(RunLog.id.in_(id_list)).delete(
                        synchronize_session=False
                    )
        db.session.commit()
    except Exception:
        db.session.rollback()
