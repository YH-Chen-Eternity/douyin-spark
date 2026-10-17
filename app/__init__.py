from flask import Flask

from app.config import SQLALCHEMY_DATABASE_URI, SECRET_KEY
from app.extensions import db


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False

    db.init_app(app)

    from app.models import Account  # noqa: F401

    with app.app_context():
        db.create_all()
        _seed_accounts()

    from app import web  # noqa: E402

    web.init_app(app)
    return app


def _seed_accounts():
    from app.models import Account

    presets = {1: "账号 A", 2: "账号 B"}
    for slot, label in presets.items():
        exists = Account.query.filter_by(slot=slot).first()
        if exists is None:
            db.session.add(Account(slot=slot, label=label))
    db.session.commit()
