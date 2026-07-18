from datetime import datetime, timezone
from uuid import uuid4

from app.db import db

ROLE_PATIENT = "PATIENT"
ROLE_DOCTOR = "DOCTOR"
ROLE_STAFF = "STAFF"
ROLE_ADMIN = "ADMIN"

CLASSIFICATION_PUBLIC = "PUBLIC"
CLASSIFICATION_INTERNAL = "INTERNAL"
CLASSIFICATION_SENSITIVE = "SENSITIVE"

APPOINTMENT_STATUS_SCHEDULED = "SCHEDULED"
APPOINTMENT_STATUS_CANCELLED = "CANCELLED"
APPOINTMENT_STATUS_COMPLETED = "COMPLETED"


def utc_now():
    return datetime.now(timezone.utc)


def new_public_id():
    return str(uuid4())


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default=ROLE_PATIENT, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    appointments = db.relationship("Appointment", back_populates="user")
    sessions = db.relationship("UserSession", back_populates="user")
    doctor_profile = db.relationship("Doctor", back_populates="user", uselist=False)
    owned_documents = db.relationship("MedicalDocument", back_populates="owner_patient")
    generated_pdfs = db.relationship("GeneratedPdf", back_populates="generated_by_user")


class UserSession(db.Model):
    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    session_token_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)
    role_snapshot = db.Column(db.String(30), nullable=False)
    source_ip = db.Column(db.String(64), nullable=True, index=True)
    user_agent_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    user = db.relationship("User", back_populates="sessions")


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    doctors = db.relationship("Doctor", back_populates="department")


class Doctor(db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    specialty = db.Column(db.String(160), nullable=False)
    bio = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = db.relationship("User", back_populates="doctor_profile")
    department = db.relationship("Department", back_populates="doctors")
    availability_slots = db.relationship("DoctorAvailabilitySlot", back_populates="doctor")
    authored_documents = db.relationship("MedicalDocument", back_populates="author_doctor")


class DoctorAvailabilitySlot(db.Model):
    __tablename__ = "doctor_availability_slots"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False, index=True)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    is_available = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    doctor = db.relationship("Doctor", back_populates="availability_slots")
    appointment = db.relationship("Appointment", back_populates="availability_slot", uselist=False)

    __table_args__ = (
        db.UniqueConstraint("doctor_id", "starts_at", name="uq_doctor_slot_start"),
    )


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    patient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    availability_slot_id = db.Column(
        db.Integer,
        db.ForeignKey("doctor_availability_slots.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    reason = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")
    status = db.Column(
        db.String(30),
        nullable=False,
        default=APPOINTMENT_STATUS_SCHEDULED,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = db.relationship("User", back_populates="appointments")
    availability_slot = db.relationship("DoctorAvailabilitySlot", back_populates="appointment")
    status_history = db.relationship("AppointmentStatusHistory", back_populates="appointment")


class AppointmentStatusHistory(db.Model):
    __tablename__ = "appointment_status_history"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(
        db.Integer,
        db.ForeignKey("appointments.id"),
        nullable=False,
        index=True,
    )
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=False, index=True)
    reason = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    appointment = db.relationship("Appointment", back_populates="status_history")
    changed_by_user = db.relationship("User")


class MedicalDocument(db.Model):
    __tablename__ = "medical_documents"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    owner_patient_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    author_doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    document_type = db.Column(db.String(80), nullable=False, index=True)
    classification = db.Column(
        db.String(30),
        nullable=False,
        default=CLASSIFICATION_SENSITIVE,
        index=True,
    )
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    owner_patient = db.relationship("User", back_populates="owned_documents")
    author_doctor = db.relationship("Doctor", back_populates="authored_documents")


class GeneratedPdf(db.Model):
    __tablename__ = "generated_pdfs"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=new_public_id)
    generated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True, index=True)
    medical_document_id = db.Column(
        db.Integer,
        db.ForeignKey("medical_documents.id"),
        nullable=True,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    generated_by_user = db.relationship("User", back_populates="generated_pdfs")
    appointment = db.relationship("Appointment")
    medical_document = db.relationship("MedicalDocument")
