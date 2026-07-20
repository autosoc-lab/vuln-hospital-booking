import json
from datetime import timedelta

from flask import current_app, g, request
from sqlalchemy import func, select

from app.auth import ensure_aware_utc
from app.db import db
from app.models import SecurityEvent, utc_now


def source_ip_from_request():
    return request.headers.get("X-Forwarded-For", request.remote_addr)


def record_security_event(event_type, severity="INFO", details=None, commit=True):
    current_user = getattr(g, "current_user", None)
    current_session = getattr(g, "current_session", None)
    event = SecurityEvent(
        event_type=event_type,
        severity=severity,
        source_ip=source_ip_from_request(),
        user=current_user,
        user_session=current_session,
        path=request.path,
        detail_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    )
    db.session.add(event)
    if commit:
        db.session.commit()
    return event


def recent_event_count(event_type, source_ip, user_session_id=None):
    window_started_at = utc_now() - timedelta(
        seconds=current_app.config["BULK_DOWNLOAD_WINDOW_SECONDS"]
    )
    query = (
        select(func.count())
        .select_from(SecurityEvent)
        .where(SecurityEvent.event_type == event_type)
        .where(SecurityEvent.source_ip == source_ip)
        .where(SecurityEvent.created_at >= window_started_at)
    )
    if user_session_id:
        query = query.where(SecurityEvent.user_session_id == user_session_id)
    return db.session.scalar(query)


def detect_bulk_document_download(document):
    current_session = getattr(g, "current_session", None)
    if not current_session:
        return

    source_ip = source_ip_from_request()
    record_security_event(
        "DOCUMENT_DOWNLOAD",
        details={
            "document_id": document.public_id,
            "classification": document.classification,
            "title": document.title,
        },
        commit=False,
    )
    download_count = recent_event_count(
        "DOCUMENT_DOWNLOAD",
        source_ip,
        user_session_id=current_session.id,
    )
    if download_count < current_app.config["BULK_DOWNLOAD_THRESHOLD"]:
        db.session.commit()
        return

    now = utc_now()
    current_session.revoked_at = now
    record_security_event(
        "BULK_DOCUMENT_DOWNLOAD",
        severity="HIGH",
        details={
            "download_count": download_count,
            "window_seconds": current_app.config["BULK_DOWNLOAD_WINDOW_SECONDS"],
        },
        commit=False,
    )
    record_security_event(
        "SOAR_IP_BLOCK_SIMULATED",
        severity="HIGH",
        details={"action": "IP 차단 시뮬레이션", "blocked_ip": source_ip},
        commit=False,
    )
    record_security_event(
        "SOAR_SESSION_REVOKED",
        severity="HIGH",
        details={
            "action": "공격 의심 세션 폐기",
            "session_id": current_session.id,
            "revoked_at": ensure_aware_utc(now).isoformat(),
        },
        commit=False,
    )
    record_security_event(
        "SOAR_EVIDENCE_COLLECTED",
        severity="INFO",
        details={
            "artifacts": ["recent_request_logs", "security_events", "session_record"],
        },
        commit=False,
    )
    db.session.commit()
