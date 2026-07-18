from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import text

from app.db import db

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html", app_name=current_app.config["APP_NAME"])


@main_bp.get("/health/live")
def health_live():
    return jsonify({"status": "live"})


@main_bp.get("/health/ready")
def health_ready():
    checks = {"database": "ok"}

    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Database readiness check failed: %s", exc)
        checks["database"] = "error"
        return jsonify({"status": "not_ready", "checks": checks}), 503
    finally:
        db.session.remove()

    return jsonify({"status": "ready", "checks": checks})
