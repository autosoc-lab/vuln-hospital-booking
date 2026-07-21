import os
from uuid import uuid4

from flask import Blueprint, abort, current_app, g, jsonify, request, send_file
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename, safe_join

from app.auth import ensure_aware_utc, login_required
from app.db import db
from app.models import (
    APPOINTMENT_STATUS_SCHEDULED,
    CLASSIFICATION_ADMIN_ONLY,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_PUBLIC,
    Appointment,
    AppointmentStatusHistory,
    Doctor,
    DoctorAvailabilitySlot,
    GeneratedPdf,
    MedicalDocument,
    ROLE_ADMIN,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    ROLE_STAFF,
    User,
    utc_now,
)
from app.pdf import render_text_pdf
from app.security_events import detect_bulk_document_download, record_security_event

api_bp = Blueprint("api", __name__, url_prefix="/api")
SEARCH_SQL_ERROR_MESSAGE = "검색어를 처리할 수 없습니다. 검색 조건을 다시 확인해 주세요."


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


def serialize_document(document):
    author = document.author_doctor
    return {
        "id": document.public_id,
        "title": document.title,
        "document_type": document.document_type,
        "classification": document.classification,
        "file_size": document.file_size,
        "created_at": isoformat(document.created_at),
        "updated_at": isoformat(document.updated_at),
        "owner_patient": serialize_user(document.owner_patient),
        "author_doctor": serialize_doctor(author) if author else None,
    }


def serialize_generated_pdf(generated_pdf):
    return {
        "id": generated_pdf.public_id,
        "filename": generated_pdf.filename,
        "created_at": isoformat(generated_pdf.created_at),
        "updated_at": isoformat(generated_pdf.updated_at),
    }


def serialize_doctor_search_result(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "specialty": row["specialty"],
        "bio": row["bio"],
        "department": {
            "id": row["department_id"],
            "name": row["department_name"],
            "description": row["department_description"],
        },
    }


def serialize_public_guide(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "document_type": row["document_type"],
        "classification": row["classification"],
        "department": row["department"],
        "doctor": row["doctor"],
    }


def storage_root():
    return os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])


def can_view_document(document):
    if g.current_user.role == ROLE_ADMIN:
        return True
    if document.classification == CLASSIFICATION_ADMIN_ONLY:
        return False
    if g.current_user.role == ROLE_STAFF:
        return True
    if document.owner_patient_user_id == g.current_user.id:
        return True
    doctor_profile = g.current_user.doctor_profile
    return bool(doctor_profile and document.author_doctor_id == doctor_profile.id)


def can_download_pdf(generated_pdf):
    if g.current_user.role in {ROLE_STAFF, ROLE_ADMIN}:
        return True
    return generated_pdf.generated_by_user_id == g.current_user.id


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


def scoped_document_query():
    query = (
        select(MedicalDocument)
        .options(
            joinedload(MedicalDocument.owner_patient),
            joinedload(MedicalDocument.author_doctor).joinedload(Doctor.department),
        )
        .order_by(MedicalDocument.created_at.desc())
    )

    if g.current_user.role == ROLE_ADMIN:
        return query
    query = query.where(MedicalDocument.classification != CLASSIFICATION_ADMIN_ONLY)
    if g.current_user.role == ROLE_PATIENT:
        return query.where(MedicalDocument.owner_patient_user_id == g.current_user.id)
    if g.current_user.role == ROLE_DOCTOR:
        doctor_profile = g.current_user.doctor_profile
        if not doctor_profile:
            return None
        return query.where(MedicalDocument.author_doctor_id == doctor_profile.id)
    if g.current_user.role == ROLE_STAFF:
        return query

    abort(403)


def owner_from_upload_payload():
    if g.current_user.role == ROLE_PATIENT:
        return g.current_user

    patient_public_id = request.form.get("patient_public_id", "").strip()
    if not patient_public_id:
        return None

    return db.session.scalar(
        select(User).where(
            User.public_id == patient_public_id,
            User.role == ROLE_PATIENT,
        )
    )


@api_bp.get("/profile")
@login_required
def profile():
    data = serialize_user(g.current_user)
    if g.current_user.doctor_profile:
        data["doctor_profile"] = serialize_doctor(g.current_user.doctor_profile)
    return jsonify({"profile": data})


@api_bp.get("/doctors/search")
def search_doctors():
    search_term = request.args.get("q", "").strip()
    department = request.args.get("department", "").strip()
    record_security_event(
        "SQLI_DOCTOR_SEARCH_USED",
        severity="MEDIUM",
        details={
            "query_length": len(search_term),
            "department_length": len(department),
        },
        commit=False,
    )

    sql = """
        SELECT
            doctors.public_id AS id,
            doctors.name AS name,
            doctors.specialty AS specialty,
            doctors.bio AS bio,
            departments.id AS department_id,
            departments.name AS department_name,
            departments.description AS department_description
        FROM doctors
        JOIN departments ON departments.id = doctors.department_id
        WHERE 1 = 1
    """
    if search_term:
        sql += (
            " AND (doctors.name LIKE '%"
            + search_term
            + "%' OR doctors.specialty LIKE '%"
            + search_term
            + "%' OR doctors.bio LIKE '%"
            + search_term
            + "%')"
        )
    if department:
        sql += " AND departments.name = '" + department + "'"
    sql += " ORDER BY doctors.name ASC"

    try:
        rows = db.session.execute(text(sql)).mappings().all()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        record_security_event(
            "SQLI_QUERY_ERROR",
            severity="LOW",
            details={"surface": "doctor_search_api"},
        )
        return jsonify({"error": SEARCH_SQL_ERROR_MESSAGE}), 400

    return jsonify(
        {
            "doctors": [
                serialize_doctor_search_result(row)
                for row in rows
            ]
        }
    )


@api_bp.get("/public/clinic-guides/search")
def search_public_clinic_guides():
    search_term = request.args.get("q", "").strip()
    record_security_event(
        "SQLI_CLINIC_GUIDE_SEARCH_USED",
        severity="MEDIUM",
        details={"query_length": len(search_term)},
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

    try:
        rows = db.session.execute(text(sql)).mappings().all()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        record_security_event(
            "SQLI_QUERY_ERROR",
            severity="LOW",
            details={"surface": "clinic_guides_api"},
        )
        return jsonify({"error": SEARCH_SQL_ERROR_MESSAGE}), 400

    return jsonify({"clinic_guides": [serialize_public_guide(row) for row in rows]})


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


@api_bp.get("/documents/search")
@login_required
def search_documents():
    query = scoped_document_query()
    if query is None:
        return jsonify({"documents": []})

    search_term = request.args.get("q", "").strip()
    document_type = request.args.get("document_type", "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        query = query.where(
            or_(
                MedicalDocument.title.ilike(pattern),
                MedicalDocument.document_type.ilike(pattern),
            )
        )
    if document_type:
        query = query.where(MedicalDocument.document_type == document_type)

    documents = db.session.scalars(query).unique().all()
    return jsonify({"documents": [serialize_document(document) for document in documents]})


@api_bp.post("/pdf/render")
@login_required
def render_pdf():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "generated-document")).strip()[:120]
    body = str(payload.get("body", "")).strip()
    if not body:
        return jsonify({"error": "body is required"}), 400

    filename_base = secure_filename(title) or "generated-document"
    filename = f"{filename_base[:80]}-{uuid4().hex}.pdf"
    relative_dir = safe_join("generated_pdfs", g.current_user.public_id)
    relative_path = safe_join(relative_dir, filename)
    absolute_dir = safe_join(storage_root(), relative_dir)
    absolute_path = safe_join(storage_root(), relative_path)
    os.makedirs(absolute_dir, exist_ok=True)

    render_text_pdf(absolute_path, title, body)

    generated_pdf = GeneratedPdf(
        generated_by_user=g.current_user,
        filename=filename,
        storage_path=relative_path,
    )
    db.session.add(generated_pdf)
    db.session.commit()

    return jsonify({"pdf": serialize_generated_pdf(generated_pdf)}), 201


@api_bp.get("/pdf/download/<public_id>")
@login_required
def download_pdf(public_id):
    generated_pdf = db.session.scalar(
        select(GeneratedPdf).where(GeneratedPdf.public_id == public_id)
    )
    if not generated_pdf:
        abort(404)
    if not can_download_pdf(generated_pdf):
        abort(403)

    file_path = safe_join(storage_root(), generated_pdf.storage_path)
    if not file_path or not os.path.isfile(file_path):
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=generated_pdf.filename)


@api_bp.post("/storage/upload")
@login_required
def upload_document():
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "file is required"}), 400

    owner = owner_from_upload_payload()
    if not owner:
        return jsonify({"error": "patient_public_id is required for this role"}), 400

    original_filename = secure_filename(uploaded_file.filename)
    if not original_filename:
        return jsonify({"error": "filename is invalid"}), 400

    stored_filename = f"{uuid4().hex}-{original_filename}"
    relative_dir = safe_join("uploads", owner.public_id)
    relative_path = safe_join(relative_dir, stored_filename)
    absolute_dir = safe_join(storage_root(), relative_dir)
    absolute_path = safe_join(storage_root(), relative_path)
    os.makedirs(absolute_dir, exist_ok=True)
    uploaded_file.save(absolute_path)

    document = MedicalDocument(
        owner_patient=owner,
        author_doctor=g.current_user.doctor_profile if g.current_user.role == ROLE_DOCTOR else None,
        title=request.form.get("title", "").strip() or original_filename,
        document_type=request.form.get("document_type", "").strip() or "테스트 문서",
        classification=request.form.get("classification", "").strip() or CLASSIFICATION_INTERNAL,
        file_path=relative_path,
        file_size=os.path.getsize(absolute_path),
    )
    db.session.add(document)
    db.session.commit()

    return jsonify({"document": serialize_document(document)}), 201


@api_bp.get("/storage/download/<public_id>")
@login_required
def download_document(public_id):
    document = db.session.scalar(
        select(MedicalDocument)
        .options(
            joinedload(MedicalDocument.owner_patient),
            joinedload(MedicalDocument.author_doctor).joinedload(Doctor.department),
        )
        .where(MedicalDocument.public_id == public_id)
    )
    if not document:
        abort(404)
    if not can_view_document(document):
        abort(403)

    file_path = safe_join(storage_root(), document.file_path)
    if not file_path or not os.path.isfile(file_path):
        abort(404)

    detect_bulk_document_download(document)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(document.file_path),
    )
