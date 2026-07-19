import os

from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import text
from werkzeug.utils import safe_join

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
    checks = {"database": "ok", "storage": "ok"}

    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Database readiness check failed: %s", exc)
        checks["database"] = "error"
        return jsonify({"status": "not_ready", "checks": checks}), 503
    finally:
        db.session.remove()

    storage_root = os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])
    healthcheck_path = safe_join(storage_root, current_app.config["STORAGE_HEALTHCHECK_PATH"])
    if not healthcheck_path:
        checks["storage"] = "error"
        return jsonify({"status": "not_ready", "checks": checks}), 503
    try:
        os.makedirs(storage_root, exist_ok=True)
        with open(healthcheck_path, "a", encoding="utf-8"):
            os.utime(healthcheck_path, None)
    except OSError as exc:
        current_app.logger.warning("Storage readiness check failed: %s", exc)
        checks["storage"] = "error"
        return jsonify({"status": "not_ready", "checks": checks}), 503

    return jsonify({"status": "ready", "checks": checks})
