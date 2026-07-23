import os
from uuid import uuid4

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
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.utils import safe_join, secure_filename

from app.auth import login_required
from app.db import db
from app.models import (
    APPOINTMENT_STATUS_SCHEDULED,
    CLASSIFICATION_ADMIN_ONLY,
    CLASSIFICATION_INTERNAL,
    Appointment,
    AppointmentStatusHistory,
    Department,
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

user_pages_bp = Blueprint("user_pages", __name__)
SEARCH_SQL_ERROR_MESSAGE = "검색어를 처리할 수 없습니다. 검색 조건을 다시 확인해 주세요."


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
    if user.role == ROLE_ADMIN:
        return True
    if document.classification == CLASSIFICATION_ADMIN_ONLY:
        return False
    if user.role == ROLE_STAFF:
        return True
    if document.owner_patient_user_id == user.id:
        return True
    doctor_profile = user.doctor_profile
    return bool(doctor_profile and document.author_doctor_id == doctor_profile.id)


def can_view_generated_pdf(generated_pdf):
    if g.current_user.role in {ROLE_ADMIN, ROLE_STAFF}:
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


def storage_root():
    return os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])


def owner_from_upload_form():
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


@user_pages_bp.get("/doctors")
@login_required
def doctors():
    search_term = request.args.get("q", "").strip()
    department_name = request.args.get("department", "").strip()

    sql = """
        SELECT doctors.id AS id
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
    if department_name:
        sql += " AND departments.name = '" + department_name + "'"
    sql += " ORDER BY doctors.name ASC"

    error_message = None
    try:
        doctor_ids = [
            row["id"]
            for row in db.session.execute(text(sql)).mappings().all()
        ]
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        doctor_ids = []
        error_message = SEARCH_SQL_ERROR_MESSAGE

    doctors = []
    if doctor_ids:
        doctors = (
            db.session.scalars(
                select(Doctor)
                .options(
                    joinedload(Doctor.department),
                    joinedload(Doctor.availability_slots),
                )
                .where(Doctor.id.in_(doctor_ids))
                .order_by(Doctor.name.asc())
            )
            .unique()
            .all()
        )
    departments = db.session.scalars(select(Department).order_by(Department.name.asc())).all()
    return render_template(
        "doctors.html",
        doctors=doctors,
        departments=departments,
        search_term=search_term,
        department_name=department_name,
        error_message=error_message,
    )


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
    search_term = request.args.get("q", "").strip()
    document_type = request.args.get("document_type", "").strip()

    if g.current_user.role == ROLE_ADMIN:
        pass
    else:
        query = query.where(MedicalDocument.classification != CLASSIFICATION_ADMIN_ONLY)

    if g.current_user.role == ROLE_PATIENT:
        query = query.where(MedicalDocument.owner_patient_user_id == g.current_user.id)
    elif g.current_user.role == ROLE_DOCTOR:
        doctor_profile = g.current_user.doctor_profile
        if not doctor_profile:
            documents = []
            return render_template(
                "documents.html",
                documents=documents,
                search_term=search_term,
                document_type=document_type,
            )
        query = query.where(MedicalDocument.author_doctor_id == doctor_profile.id)

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
    return render_template(
        "documents.html",
        documents=documents,
        search_term=search_term,
        document_type=document_type,
    )


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


@user_pages_bp.get("/profile")
@login_required
def profile():
    return render_template("profile.html")


@user_pages_bp.route("/documents/upload", methods=["GET", "POST"])
@login_required
def upload_document():
    if request.method == "POST":
        uploaded_file = request.files.get("file")
        if not uploaded_file or not uploaded_file.filename:
            flash("업로드할 파일을 선택해 주세요.", "error")
            return redirect(url_for("user_pages.upload_document"))

        owner = owner_from_upload_form()
        if not owner:
            flash("환자 ID를 입력해 주세요.", "error")
            return redirect(url_for("user_pages.upload_document"))

        original_filename = secure_filename(uploaded_file.filename)
        if not original_filename:
            flash("파일명이 올바르지 않습니다.", "error")
            return redirect(url_for("user_pages.upload_document"))

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

        flash("문서가 업로드되었습니다.", "success")
        return redirect(url_for("user_pages.document_detail", public_id=document.public_id))

    patients = []
    if g.current_user.role in {ROLE_ADMIN, ROLE_STAFF, ROLE_DOCTOR}:
        patients = db.session.scalars(
            select(User)
            .where(User.role == ROLE_PATIENT)
            .order_by(User.full_name.asc())
        ).all()
    return render_template("document_upload.html", patients=patients)


@user_pages_bp.get("/pdfs")
@login_required
def pdfs():
    query = select(GeneratedPdf).options(joinedload(GeneratedPdf.generated_by_user))
    if g.current_user.role not in {ROLE_ADMIN, ROLE_STAFF}:
        query = query.where(GeneratedPdf.generated_by_user_id == g.current_user.id)
    generated_pdfs = db.session.scalars(query.order_by(GeneratedPdf.created_at.desc())).all()
    return render_template("pdfs.html", generated_pdfs=generated_pdfs)


@user_pages_bp.route("/pdfs/new", methods=["GET", "POST"])
@login_required
def new_pdf():
    if request.method == "POST":
        title = request.form.get("title", "generated-document").strip()[:120]
        body = request.form.get("body", "").strip()
        if not body:
            flash("PDF 본문을 입력해 주세요.", "error")
            return redirect(url_for("user_pages.new_pdf"))

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

        flash("PDF가 생성되었습니다.", "success")
        return redirect(url_for("user_pages.pdfs"))

    return render_template("pdf_new.html")


@user_pages_bp.get("/pdfs/<public_id>/download")
@login_required
def download_pdf(public_id):
    generated_pdf = db.session.scalar(
        select(GeneratedPdf).where(GeneratedPdf.public_id == public_id)
    )
    if not generated_pdf:
        abort(404)
    if not can_view_generated_pdf(generated_pdf):
        abort(403)

    file_path = safe_join(storage_root(), generated_pdf.storage_path)
    if not file_path or not os.path.isfile(file_path):
        abort(404)

    return send_file(file_path, as_attachment=True, download_name=generated_pdf.filename)
