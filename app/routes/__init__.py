import os

from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import safe_join

from app.db import db
from app.models import CLASSIFICATION_PUBLIC
from app.security_events import record_security_event

main_bp = Blueprint("main", __name__)
SEARCH_SQL_ERROR_MESSAGE = "검색어를 처리할 수 없습니다. 검색 조건을 다시 확인해 주세요."


@main_bp.get("/")
def index():
    return render_template("index.html", app_name=current_app.config["APP_NAME"])


@main_bp.get("/clinic-guides")
def clinic_guides():
    search_term = request.args.get("q", "").strip()
    record_security_event(
        "SQLI_CLINIC_GUIDE_SEARCH_USED",
        severity="MEDIUM",
        details={"surface": "page", "query_length": len(search_term)},
        commit=False,
    )

    sql = f"""
        SELECT
            medical_documents.public_id AS id,
            medical_documents.title AS title,
            medical_documents.document_type AS document_type,
            medical_documents.classification AS classification,
            departments.name AS department,
            doctors.name AS doctor
        FROM medical_documents
        LEFT JOIN doctors ON doctors.id = medical_documents.author_doctor_id
        LEFT JOIN departments ON departments.id = doctors.department_id
        WHERE medical_documents.classification = '{CLASSIFICATION_PUBLIC}'
    """
    if search_term:
        sql += (
            " AND (medical_documents.title LIKE '%"
            + search_term
            + "%' OR medical_documents.document_type LIKE '%"
            + search_term
            + "%' OR departments.name LIKE '%"
            + search_term
            + "%' OR doctors.name LIKE '%"
            + search_term
            + "%')"
        )
    sql += " ORDER BY medical_documents.created_at DESC"

    error_message = None
    try:
        guides = db.session.execute(text(sql)).mappings().all()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        record_security_event(
            "SQLI_QUERY_ERROR",
            severity="LOW",
            details={"surface": "clinic_guides_page"},
        )
        guides = []
        error_message = SEARCH_SQL_ERROR_MESSAGE

    return render_template(
        "clinic_guides.html",
        guides=guides,
        search_term=search_term,
        error_message=error_message,
    )


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
