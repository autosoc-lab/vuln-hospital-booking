import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from werkzeug.utils import safe_join

from app.auth import login_required
from app.db import db
from app.models import (
    APPOINTMENT_STATUS_SCHEDULED,
    Appointment,
    AppointmentStatusHistory,
    Doctor,
    DoctorAvailabilitySlot,
    MedicalDocument,
    ROLE_ADMIN,
    ROLE_DOCTOR,
    ROLE_PATIENT,
    ROLE_STAFF,
    utc_now,
)

user_pages_bp = Blueprint("user_pages", __name__)


def can_view_appointment(appointment):
    user = g.current_user
    if user.role in {ROLE_ADMIN, ROLE_STAFF}:
        return True
    if appointment.patient_user_id == user.id:
        return True
    doctor_profile = user.doctor_profile
    return bool(
        doctor_profile
        and appointment.availability_slot
        and appointment.availability_slot.doctor_id == doctor_profile.id
    )


def can_view_document(document):
    user = g.current_user
    if user.role in {ROLE_ADMIN, ROLE_STAFF}:
        return True
    if document.owner_patient_user_id == user.id:
        return True
    doctor_profile = user.doctor_profile
    return bool(doctor_profile and document.author_doctor_id == doctor_profile.id)


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


def document_query():
    return (
        select(MedicalDocument)
        .options(
            joinedload(MedicalDocument.owner_patient),
            joinedload(MedicalDocument.author_doctor).joinedload(Doctor.department),
        )
    )


def get_document_or_404(public_id):
    document = db.session.scalar(document_query().where(MedicalDocument.public_id == public_id))
    if not document:
        abort(404)
    if not can_view_document(document):
        abort(403)
    return document


@user_pages_bp.get("/doctors")
@login_required
def doctors():
    doctors = db.session.scalars(
        select(Doctor)
        .options(joinedload(Doctor.department), joinedload(Doctor.availability_slots))
        .order_by(Doctor.name.asc())
    ).unique()
    return render_template("doctors.html", doctors=doctors)


@user_pages_bp.get("/appointments")
@login_required
def appointments():
    query = appointment_query()

    if g.current_user.role == ROLE_PATIENT:
        query = query.where(Appointment.patient_user_id == g.current_user.id)
    elif g.current_user.role == ROLE_DOCTOR:
        doctor_profile = g.current_user.doctor_profile
        if not doctor_profile:
            appointments = []
            return render_template("appointments.html", appointments=appointments)
        query = query.join(Appointment.availability_slot).where(
            DoctorAvailabilitySlot.doctor_id == doctor_profile.id
        )

    appointments = db.session.scalars(query).unique().all()
    return render_template("appointments.html", appointments=appointments)


@user_pages_bp.route("/appointments/new", methods=["GET", "POST"])
@login_required
def new_appointment():
    if g.current_user.role != ROLE_PATIENT:
        abort(403)

    if request.method == "POST":
        slot_public_id = request.form.get("slot_public_id", "").strip()
        reason = request.form.get("reason", "").strip()
        notes = request.form.get("notes", "").strip()

        slot = db.session.scalar(
            select(DoctorAvailabilitySlot)
            .options(joinedload(DoctorAvailabilitySlot.doctor).joinedload(Doctor.department))
            .where(DoctorAvailabilitySlot.public_id == slot_public_id)
        )
        if not slot or not slot.is_available:
            flash("선택한 예약 시간이 더 이상 가능하지 않습니다.", "error")
            return redirect(url_for("user_pages.new_appointment"))
        if not reason:
            flash("예약 사유를 입력해 주세요.", "error")
            return redirect(url_for("user_pages.new_appointment", slot=slot_public_id))

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
        db.session.commit()

        flash("예약이 생성되었습니다.", "success")
        return redirect(url_for("user_pages.appointment_detail", public_id=appointment.public_id))

    selected_slot = request.args.get("slot", "").strip()
    slots = db.session.scalars(
        select(DoctorAvailabilitySlot)
        .options(joinedload(DoctorAvailabilitySlot.doctor).joinedload(Doctor.department))
        .where(DoctorAvailabilitySlot.is_available.is_(True))
        .where(DoctorAvailabilitySlot.starts_at >= utc_now())
        .order_by(DoctorAvailabilitySlot.starts_at.asc())
    ).unique()
    return render_template(
        "appointment_new.html",
        selected_slot=selected_slot,
        slots=slots,
    )


@user_pages_bp.get("/appointments/<public_id>")
@login_required
def appointment_detail(public_id):
    appointment = db.session.scalar(
        appointment_query().where(Appointment.public_id == public_id)
    )
    if not appointment:
        abort(404)
    if not can_view_appointment(appointment):
        abort(403)

    history = (
        db.session.scalars(
            select(AppointmentStatusHistory)
            .options(joinedload(AppointmentStatusHistory.changed_by_user))
            .where(AppointmentStatusHistory.appointment_id == appointment.id)
            .order_by(AppointmentStatusHistory.created_at.asc())
        )
        .unique()
        .all()
    )
    return render_template("appointment_detail.html", appointment=appointment, history=history)


@user_pages_bp.get("/documents")
@login_required
def documents():
    query = document_query().order_by(MedicalDocument.created_at.desc())

    if g.current_user.role == ROLE_PATIENT:
        query = query.where(MedicalDocument.owner_patient_user_id == g.current_user.id)
    elif g.current_user.role == ROLE_DOCTOR:
        doctor_profile = g.current_user.doctor_profile
        if not doctor_profile:
            documents = []
            return render_template("documents.html", documents=documents)
        query = query.where(MedicalDocument.author_doctor_id == doctor_profile.id)

    documents = db.session.scalars(query).unique().all()
    return render_template("documents.html", documents=documents)


@user_pages_bp.get("/documents/<public_id>")
@login_required
def document_detail(public_id):
    document = get_document_or_404(public_id)
    return render_template("document_detail.html", document=document)


@user_pages_bp.get("/documents/<public_id>/download")
@login_required
def download_document(public_id):
    document = get_document_or_404(public_id)
    storage_root = os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])
    file_path = safe_join(storage_root, document.file_path)
    if not file_path or not os.path.isfile(file_path):
        abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(document.file_path),
    )
