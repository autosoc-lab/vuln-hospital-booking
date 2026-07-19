from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.auth import ensure_aware_utc, login_required
from app.db import db
from app.models import (
    APPOINTMENT_STATUS_SCHEDULED,
    Appointment,
    AppointmentStatusHistory,
    Doctor,
    DoctorAvailabilitySlot,
    ROLE_ADMIN,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    ROLE_STAFF,
    utc_now,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def isoformat(value):
    return value.isoformat() if value else None


def serialize_department(department):
    return {
        "id": department.id,
        "name": department.name,
        "description": department.description,
    }


def serialize_user(user):
    return {
        "id": user.public_id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "email": user.email,
        "created_at": isoformat(user.created_at),
        "updated_at": isoformat(user.updated_at),
    }


def serialize_doctor(doctor, include_slots=False):
    data = {
        "id": doctor.public_id,
        "name": doctor.name,
        "specialty": doctor.specialty,
        "bio": doctor.bio,
        "department": serialize_department(doctor.department),
    }
    if include_slots:
        slots = sorted(doctor.availability_slots, key=lambda slot: slot.starts_at)
        data["availability_slots"] = [
            {
                "id": slot.public_id,
                "starts_at": isoformat(slot.starts_at),
                "ends_at": isoformat(slot.ends_at),
                "is_available": slot.is_available,
            }
            for slot in slots
        ]
    return data


def serialize_appointment(appointment):
    slot = appointment.availability_slot
    doctor = slot.doctor
    return {
        "id": appointment.public_id,
        "status": appointment.status,
        "reason": appointment.reason,
        "notes": appointment.notes,
        "created_at": isoformat(appointment.created_at),
        "updated_at": isoformat(appointment.updated_at),
        "patient": serialize_user(appointment.user),
        "doctor": serialize_doctor(doctor),
        "slot": {
            "id": slot.public_id,
            "starts_at": isoformat(slot.starts_at),
            "ends_at": isoformat(slot.ends_at),
            "is_available": slot.is_available,
        },
    }


def appointment_query():
    return (
        select(Appointment)
        .options(
            joinedload(Appointment.user),
            joinedload(Appointment.availability_slot)
            .joinedload(DoctorAvailabilitySlot.doctor)
            .joinedload(Doctor.department),
        )
        .order_by(Appointment.created_at.desc())
    )


def scoped_appointment_query():
    query = appointment_query()

    if g.current_user.role == ROLE_PATIENT:
        return query.where(Appointment.patient_user_id == g.current_user.id)
    if g.current_user.role == ROLE_DOCTOR:
        doctor_profile = g.current_user.doctor_profile
        if not doctor_profile:
            return None
        return query.join(Appointment.availability_slot).where(
            DoctorAvailabilitySlot.doctor_id == doctor_profile.id
        )
    if g.current_user.role in {ROLE_STAFF, ROLE_ADMIN}:
        return query

    abort(403)


@api_bp.get("/profile")
@login_required
def profile():
    data = serialize_user(g.current_user)
    if g.current_user.doctor_profile:
        data["doctor_profile"] = serialize_doctor(g.current_user.doctor_profile)
    return jsonify({"profile": data})


@api_bp.get("/doctors/search")
@login_required
def search_doctors():
    search_term = request.args.get("q", "").strip()
    department = request.args.get("department", "").strip()
    include_slots = request.args.get("include_slots", "").lower() in {"1", "true", "yes"}

    query = select(Doctor).options(joinedload(Doctor.department))
    if include_slots:
        query = query.options(joinedload(Doctor.availability_slots))
    if search_term:
        pattern = f"%{search_term}%"
        query = query.where(
            or_(
                Doctor.name.ilike(pattern),
                Doctor.specialty.ilike(pattern),
                Doctor.bio.ilike(pattern),
            )
        )
    if department:
        query = query.where(Doctor.department.has(name=department))

    doctors = (
        db.session.scalars(query.order_by(Doctor.name.asc()))
        .unique()
        .all()
    )
    return jsonify(
        {
            "doctors": [
                serialize_doctor(doctor, include_slots=include_slots)
                for doctor in doctors
            ]
        }
    )


@api_bp.get("/appointments")
@login_required
def list_appointments():
    query = scoped_appointment_query()
    appointments = [] if query is None else db.session.scalars(query).unique().all()
    return jsonify({"appointments": [serialize_appointment(item) for item in appointments]})


@api_bp.post("/appointments")
@login_required
def create_appointment():
    if g.current_user.role != ROLE_PATIENT:
        abort(403)

    payload = request.get_json(silent=True) or {}
    slot_public_id = str(payload.get("slot_public_id", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    notes = str(payload.get("notes", "")).strip()

    if not slot_public_id:
        return jsonify({"error": "slot_public_id is required"}), 400
    if not reason:
        return jsonify({"error": "reason is required"}), 400

    slot = db.session.scalar(
        select(DoctorAvailabilitySlot)
        .options(joinedload(DoctorAvailabilitySlot.doctor).joinedload(Doctor.department))
        .where(DoctorAvailabilitySlot.public_id == slot_public_id)
    )
    if not slot:
        return jsonify({"error": "availability slot not found"}), 404
    if not slot.is_available or ensure_aware_utc(slot.starts_at) < utc_now():
        return jsonify({"error": "availability slot is not available"}), 409

    appointment = Appointment(
        user=g.current_user,
        availability_slot=slot,
        reason=reason,
        notes=notes,
        status=APPOINTMENT_STATUS_SCHEDULED,
    )
    slot.is_available = False
    db.session.add(appointment)
    db.session.flush()
    db.session.add(
        AppointmentStatusHistory(
            appointment=appointment,
            changed_by_user=g.current_user,
            from_status=None,
            to_status=APPOINTMENT_STATUS_SCHEDULED,
            reason="환자 예약 생성",
        )
    )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "availability slot is not available"}), 409

    return jsonify({"appointment": serialize_appointment(appointment)}), 201
