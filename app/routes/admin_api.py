from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from flask import Blueprint, jsonify, render_template, request

from app.auth import admin_required, ensure_aware_utc
from app.db import db
from app.models import (
    Appointment,
    Doctor,
    DoctorAvailabilitySlot,
    MedicalDocument,
    ROLE_ADMIN,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    ROLE_STAFF,
    User,
    UserSession,
    utc_now,
)
from app.routes.api import isoformat, serialize_appointment, serialize_document

admin_api_bp = Blueprint("admin_api", __name__)


def wants_html():
    return (
        request.accept_mimetypes.accept_html
        and request.accept_mimetypes["text/html"]
        >= request.accept_mimetypes["application/json"]
    )


def model_count(model):
    return db.session.scalar(select(func.count()).select_from(model))


def active_session_count():
    return db.session.scalar(
        select(func.count())
        .select_from(UserSession)
        .where(UserSession.revoked_at.is_(None))
        .where(UserSession.expires_at > utc_now())
    )


def serialize_security_event(event_type, occurred_at, user_session):
    user = user_session.user
    return {
        "event_type": event_type,
        "occurred_at": isoformat(occurred_at),
        "source_ip": user_session.source_ip,
        "user_agent_hash": user_session.user_agent_hash,
        "role_snapshot": user_session.role_snapshot,
        "user": {
            "id": user.public_id,
            "username": user.username,
            "role": user.role,
        },
    }


def session_security_events(user_sessions):
    events = []
    now = utc_now()
    for user_session in user_sessions:
        events.append(
            serialize_security_event(
                "SESSION_CREATED",
                user_session.created_at,
                user_session,
            )
        )
        if user_session.revoked_at:
            events.append(
                serialize_security_event(
                    "SESSION_REVOKED",
                    user_session.revoked_at,
                    user_session,
                )
            )
        elif ensure_aware_utc(user_session.expires_at) <= now:
            events.append(
                serialize_security_event(
                    "SESSION_EXPIRED",
                    user_session.expires_at,
                    user_session,
                )
            )

    return sorted(events, key=lambda event: event["occurred_at"], reverse=True)


@admin_api_bp.get("/admin")
@admin_required
def dashboard():
    users_by_role = dict(
        db.session.execute(
            select(User.role, func.count(User.id))
            .group_by(User.role)
            .order_by(User.role.asc())
        ).all()
    )
    counts = {
        "users": model_count(User),
        "patients": users_by_role.get(ROLE_PATIENT, 0),
        "doctors": users_by_role.get(ROLE_DOCTOR, 0),
        "staff": users_by_role.get(ROLE_STAFF, 0),
        "admins": users_by_role.get(ROLE_ADMIN, 0),
        "appointments": model_count(Appointment),
        "documents": model_count(MedicalDocument),
        "active_sessions": active_session_count(),
    }
    if wants_html():
        return render_template("admin/dashboard.html", counts=counts)
    return jsonify({"dashboard": {"counts": counts}})


@admin_api_bp.get("/admin/appointments")
@admin_required
def appointments():
    query = (
        select(Appointment)
        .options(
            joinedload(Appointment.user),
            joinedload(Appointment.availability_slot)
            .joinedload(DoctorAvailabilitySlot.doctor)
            .joinedload(Doctor.department),
        )
        .order_by(Appointment.created_at.desc())
    )
    appointments = db.session.scalars(query).unique().all()
    if wants_html():
        return render_template("admin/appointments.html", appointments=appointments)
    return jsonify({"appointments": [serialize_appointment(item) for item in appointments]})


@admin_api_bp.get("/admin/documents")
@admin_required
def documents():
    query = (
        select(MedicalDocument)
        .options(
            joinedload(MedicalDocument.owner_patient),
            joinedload(MedicalDocument.author_doctor).joinedload(Doctor.department),
        )
        .order_by(MedicalDocument.created_at.desc())
    )
    documents = db.session.scalars(query).unique().all()
    if wants_html():
        return render_template("admin/documents.html", documents=documents)
    return jsonify({"documents": [serialize_document(document) for document in documents]})


@admin_api_bp.get("/admin/security-events")
@admin_required
def security_events():
    query = (
        select(UserSession)
        .options(joinedload(UserSession.user))
        .order_by(UserSession.created_at.desc())
    )
    user_sessions = db.session.scalars(query).unique().all()
    events = session_security_events(user_sessions)
    if wants_html():
        return render_template("admin/security_events.html", events=events)
    return jsonify({"security_events": events})
