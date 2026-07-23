from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from flask import Blueprint, jsonify, render_template, request

from app.auth import admin_required
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
