from datetime import datetime, timezone

from sqlalchemy import func, select
from werkzeug.security import generate_password_hash

from app.db import db
from app.models import (
    APPOINTMENT_STATUS_SCHEDULED,
    CLASSIFICATION_ADMIN_ONLY,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_PUBLIC,
    CLASSIFICATION_SENSITIVE,
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
)


def seed_database():
    existing_users = db.session.scalar(select(func.count()).select_from(User))
    if existing_users:
        return False

    users = {
        "admin": User(
            username="admin",
            password_hash=generate_password_hash("AdminPass123!"),
            role=ROLE_ADMIN,
            full_name="관리자",
            email="admin@hospital.local",
        ),
        "staff": User(
            username="staff",
            password_hash=generate_password_hash("StaffPass123!"),
            role=ROLE_STAFF,
            full_name="원무과 직원",
            email="staff@hospital.local",
        ),
        "patient_alice": User(
            username="alice",
            password_hash=generate_password_hash("PatientPass123!"),
            role=ROLE_PATIENT,
            full_name="김민지",
            email="alice@example.local",
        ),
        "patient_bob": User(
            username="bob",
            password_hash=generate_password_hash("PatientPass123!"),
            role=ROLE_PATIENT,
            full_name="박준호",
            email="bob@example.local",
        ),
        "doctor_kim": User(
            username="dr.kim",
            password_hash=generate_password_hash("DoctorPass123!"),
            role=ROLE_DOCTOR,
            full_name="김도현",
            email="dr.kim@hospital.local",
        ),
        "doctor_lee": User(
            username="dr.lee",
            password_hash=generate_password_hash("DoctorPass123!"),
            role=ROLE_DOCTOR,
            full_name="이서연",
            email="dr.lee@hospital.local",
        ),
        "doctor_park": User(
            username="dr.park",
            password_hash=generate_password_hash("DoctorPass123!"),
            role=ROLE_DOCTOR,
            full_name="박지훈",
            email="dr.park@hospital.local",
        ),
    }

    departments = {
        "internal": Department(name="내과", description="일반 내과 진료와 만성질환 상담"),
        "orthopedics": Department(name="정형외과", description="관절, 척추, 근골격계 진료"),
        "dermatology": Department(name="피부과", description="피부 질환과 알레르기 진료"),
    }

    doctors = {
        "kim": Doctor(
            user=users["doctor_kim"],
            department=departments["internal"],
            name="김도현",
            specialty="소화기내과",
            bio="위장관 질환과 건강검진 상담을 담당합니다.",
        ),
        "lee": Doctor(
            user=users["doctor_lee"],
            department=departments["orthopedics"],
            name="이서연",
            specialty="무릎 관절",
            bio="스포츠 손상과 관절 통증 진료를 담당합니다.",
        ),
        "park": Doctor(
            user=users["doctor_park"],
            department=departments["dermatology"],
            name="박지훈",
            specialty="아토피 피부염",
            bio="만성 피부질환과 알레르기성 피부염 진료를 담당합니다.",
        ),
    }

    base_day = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    slots = {
        "kim_0900": DoctorAvailabilitySlot(
            doctor=doctors["kim"],
            starts_at=base_day.replace(hour=9),
            ends_at=base_day.replace(hour=9, minute=30),
            is_available=False,
        ),
        "kim_1000": DoctorAvailabilitySlot(
            doctor=doctors["kim"],
            starts_at=base_day.replace(hour=10),
            ends_at=base_day.replace(hour=10, minute=30),
        ),
        "lee_1100": DoctorAvailabilitySlot(
            doctor=doctors["lee"],
            starts_at=base_day.replace(hour=11),
            ends_at=base_day.replace(hour=11, minute=30),
            is_available=False,
        ),
        "park_1400": DoctorAvailabilitySlot(
            doctor=doctors["park"],
            starts_at=base_day.replace(hour=14),
            ends_at=base_day.replace(hour=14, minute=30),
        ),
    }

    appointments = {
        "alice_kim": Appointment(
            user=users["patient_alice"],
            availability_slot=slots["kim_0900"],
            reason="복통 및 소화불량 상담",
            notes="최근 2주간 증상이 반복됨",
            status=APPOINTMENT_STATUS_SCHEDULED,
        ),
        "bob_lee": Appointment(
            user=users["patient_bob"],
            availability_slot=slots["lee_1100"],
            reason="무릎 통증 상담",
            notes="운동 후 통증 증가",
            status=APPOINTMENT_STATUS_SCHEDULED,
        ),
    }

    status_history = [
        AppointmentStatusHistory(
            appointment=appointments["alice_kim"],
            changed_by_user=users["patient_alice"],
            from_status=None,
            to_status=APPOINTMENT_STATUS_SCHEDULED,
            reason="초기 예약 생성",
        ),
        AppointmentStatusHistory(
            appointment=appointments["bob_lee"],
            changed_by_user=users["patient_bob"],
            from_status=None,
            to_status=APPOINTMENT_STATUS_SCHEDULED,
            reason="초기 예약 생성",
        ),
    ]

    documents = {
        "alice_referral": MedicalDocument(
            owner_patient=users["patient_alice"],
            author_doctor=doctors["kim"],
            title="소화기내과 진료의뢰서",
            document_type="진료의뢰서",
            classification=CLASSIFICATION_SENSITIVE,
            file_path="documents/patient-alice/referral-gi.pdf",
            file_size=245760,
        ),
        "alice_intake": MedicalDocument(
            owner_patient=users["patient_alice"],
            title="초진 문진표",
            document_type="문진표",
            classification=CLASSIFICATION_INTERNAL,
            file_path="documents/patient-alice/intake-form.pdf",
            file_size=98304,
        ),
        "bob_notice": MedicalDocument(
            owner_patient=users["patient_bob"],
            author_doctor=doctors["lee"],
            title="정형외과 안내문",
            document_type="안내문",
            classification=CLASSIFICATION_PUBLIC,
            file_path="documents/patient-bob/orthopedics-guide.pdf",
            file_size=65536,
        ),
        "admin_audit_export": MedicalDocument(
            owner_patient=users["patient_alice"],
            title="관리자 전용 의료문서 반출 감사자료",
            document_type="감사자료",
            classification=CLASSIFICATION_ADMIN_ONLY,
            file_path="documents/admin/audit-export-summary.pdf",
            file_size=131072,
        ),
    }

    generated_pdfs = [
        GeneratedPdf(
            generated_by_user=users["patient_alice"],
            appointment=appointments["alice_kim"],
            filename="alice-appointment-confirmation.pdf",
            storage_path="generated_pdfs/alice/appointment-confirmation.pdf",
        ),
        GeneratedPdf(
            generated_by_user=users["staff"],
            medical_document=documents["alice_referral"],
            filename="alice-referral-copy.pdf",
            storage_path="generated_pdfs/staff/alice-referral-copy.pdf",
        ),
    ]

    db.session.add_all(users.values())
    db.session.add_all(departments.values())
    db.session.add_all(doctors.values())
    db.session.add_all(slots.values())
    db.session.add_all(appointments.values())
    db.session.add_all(status_history)
    db.session.add_all(documents.values())
    db.session.add_all(generated_pdfs)
    db.session.commit()

    return True
