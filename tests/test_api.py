import io
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import select

from app import create_app
from app.db import db
from app.models import (
    Appointment,
    CLASSIFICATION_ADMIN_ONLY,
    DoctorAvailabilitySlot,
    GeneratedPdf,
    MedicalDocument,
    SecurityEvent,
    User,
    UserSession,
)
from app.pdf import KOREAN_FONT_NAME
from app.seed import seed_database


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    APP_NAME = "Test Hospital"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DOCUMENT_STORAGE_ROOT = ""
    STORAGE_HEALTHCHECK_PATH = ".healthcheck"
    BULK_DOWNLOAD_WINDOW_SECONDS = 60
    BULK_DOWNLOAD_THRESHOLD = 3


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp()
        TestConfig.DOCUMENT_STORAGE_ROOT = self.storage_dir
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            seed_database()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        shutil.rmtree(self.storage_dir, ignore_errors=True)

    def login(self, username, password):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_profile_returns_current_user(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/api/profile")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["profile"]["username"], "alice")
        self.assertEqual(payload["profile"]["role"], "PATIENT")

    def test_app_requests_emit_structured_event_log(self):
        self.login("alice", "PatientPass123!")

        with self.assertLogs(self.app.logger.name, level="INFO") as captured:
            response = self.client.get(
                "/api/profile",
                headers={"X-Request-ID": "test-request-1"},
            )

        self.assertEqual(response.status_code, 200)
        log_line = next(line for line in captured.output if "app_event " in line)
        event = json.loads(log_line.split("app_event ", 1)[1])
        self.assertEqual(event["event"], "app_request")
        self.assertEqual(event["method"], "GET")
        self.assertEqual(event["path"], "/api/profile")
        self.assertEqual(event["endpoint"], "api.profile")
        self.assertEqual(event["status_code"], 200)
        self.assertEqual(event["user_role"], "PATIENT")
        self.assertEqual(event["request_id"], "test-request-1")
        self.assertIsInstance(event["duration_ms"], float)

    def test_page_requests_emit_structured_event_log(self):
        self.login("alice", "PatientPass123!")

        with self.assertLogs(self.app.logger.name, level="INFO") as captured:
            response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        log_line = next(line for line in captured.output if "app_event " in line)
        event = json.loads(log_line.split("app_event ", 1)[1])
        self.assertEqual(event["event"], "app_request")
        self.assertEqual(event["path"], "/profile")
        self.assertEqual(event["endpoint"], "user_pages.profile")
        self.assertEqual(event["user_role"], "PATIENT")

    def test_static_assets_do_not_emit_app_event_log(self):
        with self.assertNoLogs(self.app.logger.name, level="INFO"):
            response = self.client.get("/static/css/app.css")

        self.assertIn(response.status_code, {200, 304})

    def test_index_page_renders_service_home(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("예약부터 진료까지 더 쉽고 편리하게".encode(), response.data)
        self.assertIn("빠른 예약".encode(), response.data)
        self.assertIn("주요 진료과".encode(), response.data)
        self.assertIn("공개 진료 안내문".encode(), response.data)

    def test_clinic_guides_page_supports_public_search(self):
        response = self.client.get("/clinic-guides?q=정형외과")

        self.assertEqual(response.status_code, 200)
        self.assertIn("진료 안내문".encode(), response.data)
        self.assertIn("정형외과 안내문".encode(), response.data)
        self.assertIn("/clinic-guides/".encode(), response.data)
        self.assertNotIn("소화기내과 진료의뢰서".encode(), response.data)

    def test_public_clinic_guide_document_can_be_viewed(self):
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(MedicalDocument.title == "정형외과 안내문")
            )
            document_id = document.public_id
            absolute_path = os.path.join(self.storage_dir, document.file_path)
            os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            with open(absolute_path, "wb") as handle:
                handle.write(b"%PDF public guide")

        response = self.client.get(f"/clinic-guides/{document_id}/document")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.data, b"%PDF public guide")
        response.close()

    def test_sensitive_document_cannot_be_viewed_as_public_clinic_guide(self):
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(MedicalDocument.title == "소화기내과 진료의뢰서")
            )
            document_id = document.public_id

        response = self.client.get(f"/clinic-guides/{document_id}/document")

        self.assertEqual(response.status_code, 404)

    def test_clinic_guides_page_search_is_intentionally_vulnerable(self):
        response = self.client.get("/clinic-guides?q=%25%27)%20OR%201=1%20--%20")

        self.assertEqual(response.status_code, 200)
        self.assertIn("정형외과 안내문".encode(), response.data)
        self.assertIn("소화기내과 진료의뢰서".encode(), response.data)

    def test_clinic_guides_page_shows_message_for_sql_errors(self):
        response = self.client.get("/clinic-guides?q=%25%27)%20UNION%20SELECT%20%27only-one%27%20--%20")

        self.assertEqual(response.status_code, 200)
        self.assertIn("검색어를 처리할 수 없습니다".encode(), response.data)

    def test_profile_page_is_available_to_logged_in_users(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn("내 프로필".encode(), response.data)
        self.assertIn("alice".encode(), response.data)

    def test_doctors_page_supports_search(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/doctors?q=소화기")

        self.assertEqual(response.status_code, 200)
        self.assertIn("김도현".encode(), response.data)
        self.assertNotIn("이서연".encode(), response.data)

    def test_doctors_page_search_is_intentionally_vulnerable(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/doctors?q=%25%27)%20OR%201=1%20--%20")

        self.assertEqual(response.status_code, 200)
        self.assertIn("김도현".encode(), response.data)
        self.assertIn("이서연".encode(), response.data)
        self.assertIn("박지훈".encode(), response.data)

    def test_doctors_page_shows_message_for_sql_errors(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/doctors?q=%25%27)%20UNION%20SELECT%201,2%20--%20")

        self.assertEqual(response.status_code, 200)
        self.assertIn("검색어를 처리할 수 없습니다".encode(), response.data)

    def test_doctors_search_filters_by_name_or_specialty(self):
        response = self.client.get("/api/doctors/search?q=소화기")

        self.assertEqual(response.status_code, 200)
        doctors = response.get_json()["doctors"]
        self.assertEqual(len(doctors), 1)
        self.assertEqual(doctors[0]["name"], "김도현")
        self.assertEqual(doctors[0]["department"]["name"], "내과")

    def test_doctors_search_is_public_without_login(self):
        response = self.client.get("/api/doctors/search")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["doctors"]), 3)

    def test_doctors_search_is_intentionally_vulnerable(self):
        response = self.client.get("/api/doctors/search?q=%25%27)%20OR%201=1%20--")

        self.assertEqual(response.status_code, 200)
        doctors = response.get_json()["doctors"]
        self.assertEqual(len(doctors), 3)

    def test_vulnerable_doctors_search_records_security_event(self):
        response = self.client.get("/api/doctors/search?q=정형외과")

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            event = db.session.scalar(
                select(SecurityEvent).where(
                    SecurityEvent.event_type == "SQLI_DOCTOR_SEARCH_USED"
                )
            )
            self.assertIsNotNone(event)

    def test_public_clinic_guides_search_lists_only_public_documents(self):
        response = self.client.get("/api/public/clinic-guides/search?q=정형외과")

        self.assertEqual(response.status_code, 200)
        guides = response.get_json()["clinic_guides"]
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0]["title"], "정형외과 안내문")
        self.assertEqual(guides[0]["classification"], "PUBLIC")

    def test_public_clinic_guides_search_is_intentionally_vulnerable(self):
        response = self.client.get("/api/public/clinic-guides/search?q=%25%27)%20OR%201=1%20--%20")

        self.assertEqual(response.status_code, 200)
        guides = response.get_json()["clinic_guides"]
        classifications = {guide["classification"] for guide in guides}
        self.assertGreaterEqual(len(guides), 4)
        self.assertIn("SENSITIVE", classifications)
        self.assertIn(CLASSIFICATION_ADMIN_ONLY, classifications)

    def test_public_clinic_guide_download_returns_public_document(self):
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(MedicalDocument.title == "정형외과 안내문")
            )
            document_id = document.public_id
            absolute_path = os.path.join(self.storage_dir, document.file_path)
            os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            with open(absolute_path, "wb") as handle:
                handle.write(b"%PDF public guide download")

        response = self.client.get(
            "/api/public/clinic-guides/download",
            query_string={"document_id": document_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.data, b"%PDF public guide download")
        response.close()

    def test_public_clinic_guide_download_is_intentionally_vulnerable(self):
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(
                    MedicalDocument.classification == CLASSIFICATION_ADMIN_ONLY
                )
            )
            document_id = document.public_id
            absolute_path = os.path.join(self.storage_dir, document.file_path)
            os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            with open(absolute_path, "wb") as handle:
                handle.write(b"%PDF admin only through sqli")

        response = self.client.get(
            "/api/public/clinic-guides/download",
            query_string={
                "document_id": f"' OR medical_documents.public_id = '{document_id}' -- "
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.data, b"%PDF admin only through sqli")
        response.close()

    def test_vulnerable_public_clinic_guides_search_records_security_event(self):
        response = self.client.get("/api/public/clinic-guides/search?q=정형외과")

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            event = db.session.scalar(
                select(SecurityEvent).where(
                    SecurityEvent.event_type == "SQLI_CLINIC_GUIDE_SEARCH_USED"
                )
            )
            self.assertIsNotNone(event)

    def test_public_clinic_guides_search_returns_message_for_sql_errors(self):
        response = self.client.get(
            "/api/public/clinic-guides/search?q=%25%27)%20UNION%20SELECT%20%27only-one%27%20--%20"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("검색어를 처리할 수 없습니다", response.get_json()["error"])

    def test_doctors_search_returns_message_for_sql_errors(self):
        response = self.client.get("/api/doctors/search?q=%25%27)%20UNION%20SELECT%201%20--%20")

        self.assertEqual(response.status_code, 400)
        self.assertIn("검색어를 처리할 수 없습니다", response.get_json()["error"])

    def test_patient_appointments_are_scoped_to_self(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/api/appointments")

        self.assertEqual(response.status_code, 200)
        appointments = response.get_json()["appointments"]
        self.assertEqual(len(appointments), 1)
        self.assertEqual(appointments[0]["patient"]["username"], "alice")

    def test_doctor_appointments_are_scoped_to_doctor_profile(self):
        self.login("dr.lee", "DoctorPass123!")

        response = self.client.get("/api/appointments")

        self.assertEqual(response.status_code, 200)
        appointments = response.get_json()["appointments"]
        self.assertEqual(len(appointments), 1)
        self.assertEqual(appointments[0]["doctor"]["name"], "이서연")

    def test_staff_can_view_all_appointments(self):
        self.login("staff", "StaffPass123!")

        response = self.client.get("/api/appointments")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["appointments"]), 2)

    def test_admin_dashboard_requires_admin_role(self):
        self.login("staff", "StaffPass123!")

        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_returns_summary_counts(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        counts = response.get_json()["dashboard"]["counts"]
        self.assertEqual(counts["users"], 7)
        self.assertEqual(counts["patients"], 2)
        self.assertEqual(counts["doctors"], 3)
        self.assertEqual(counts["staff"], 1)
        self.assertEqual(counts["admins"], 1)
        self.assertEqual(counts["appointments"], 2)
        self.assertEqual(counts["documents"], 4)
        self.assertEqual(counts["active_sessions"], 1)

    def test_admin_can_view_all_appointments_from_admin_api(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/appointments")

        self.assertEqual(response.status_code, 200)
        appointments = response.get_json()["appointments"]
        self.assertEqual(len(appointments), 2)
        self.assertEqual(
            {appointment["patient"]["username"] for appointment in appointments},
            {"alice", "bob"},
        )

    def test_admin_can_view_all_documents_from_admin_api(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/documents")

        self.assertEqual(response.status_code, 200)
        documents = response.get_json()["documents"]
        self.assertEqual(len(documents), 4)
        self.assertEqual(
            {document["owner_patient"]["username"] for document in documents},
            {"alice", "bob"},
        )
        self.assertIn(CLASSIFICATION_ADMIN_ONLY, {document["classification"] for document in documents})

    def test_only_admin_can_download_admin_only_document(self):
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(
                    MedicalDocument.classification == CLASSIFICATION_ADMIN_ONLY
                )
            )
            document_id = document.public_id
            absolute_path = os.path.join(self.storage_dir, document.file_path)
            os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            with open(absolute_path, "wb") as handle:
                handle.write(b"%PDF admin only")

        self.login("staff", "StaffPass123!")
        response = self.client.get(f"/api/storage/download/{document_id}")
        self.assertEqual(response.status_code, 403)

        self.client.post("/logout")
        self.login("alice", "PatientPass123!")
        response = self.client.get(f"/api/storage/download/{document_id}")
        self.assertEqual(response.status_code, 403)

        self.client.post("/logout")
        self.login("admin", "AdminPass123!")
        response = self.client.get(f"/api/storage/download/{document_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF admin only")
        response.close()

    def test_admin_can_view_security_events(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/security-events")

        self.assertEqual(response.status_code, 200)
        events = response.get_json()["security_events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "SESSION_CREATED")
        self.assertEqual(events[0]["user"]["username"], "admin")
        self.assertEqual(events[0]["user"]["role"], "ADMIN")
        self.assertIsNotNone(events[0]["source_ip"])

    def test_admin_dashboard_renders_html_for_browser_requests(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin", headers={"Accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("관리자 대시보드".encode(), response.data)
        self.assertIn("전체 예약".encode(), response.data)

    def test_admin_appointments_render_html_for_browser_requests(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/appointments", headers={"Accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("전체 예약".encode(), response.data)
        self.assertIn("김민지".encode(), response.data)

    def test_admin_documents_render_html_for_browser_requests(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/documents", headers={"Accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("전체 문서".encode(), response.data)
        self.assertIn("소화기내과 진료의뢰서".encode(), response.data)

    def test_admin_security_events_render_html_for_browser_requests(self):
        self.login("admin", "AdminPass123!")

        response = self.client.get("/admin/security-events", headers={"Accept": "text/html"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("보안 이벤트".encode(), response.data)
        self.assertIn("SESSION_CREATED".encode(), response.data)

    def test_patient_can_create_appointment(self):
        self.login("alice", "PatientPass123!")
        with self.app.app_context():
            slot = db.session.scalar(
                select(DoctorAvailabilitySlot)
                .where(DoctorAvailabilitySlot.is_available.is_(True))
                .order_by(DoctorAvailabilitySlot.starts_at.asc())
            )
            slot_public_id = slot.public_id

        response = self.client.post(
            "/api/appointments",
            json={
                "slot_public_id": slot_public_id,
                "reason": "API 예약 테스트",
                "notes": "오전 방문 희망",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["appointment"]["reason"], "API 예약 테스트")
        self.assertEqual(payload["appointment"]["patient"]["username"], "alice")
        with self.app.app_context():
            slot = db.session.scalar(
                select(DoctorAvailabilitySlot)
                .where(DoctorAvailabilitySlot.public_id == slot_public_id)
            )
            self.assertFalse(slot.is_available)
            self.assertEqual(db.session.query(Appointment).count(), 3)

    def test_doctor_cannot_create_appointment(self):
        self.login("dr.kim", "DoctorPass123!")

        response = self.client.post(
            "/api/appointments",
            json={"slot_public_id": "unused", "reason": "권한 없음"},
        )

        self.assertEqual(response.status_code, 403)

    def test_documents_search_is_scoped_to_patient(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/api/documents/search")

        self.assertEqual(response.status_code, 200)
        documents = response.get_json()["documents"]
        self.assertEqual(len(documents), 2)
        self.assertEqual({item["owner_patient"]["username"] for item in documents}, {"alice"})

    def test_documents_search_filters_by_title(self):
        self.login("staff", "StaffPass123!")

        response = self.client.get("/api/documents/search?q=정형외과")

        self.assertEqual(response.status_code, 200)
        documents = response.get_json()["documents"]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["owner_patient"]["username"], "bob")

    def test_staff_document_search_excludes_admin_only_documents(self):
        self.login("staff", "StaffPass123!")

        response = self.client.get("/api/documents/search")

        self.assertEqual(response.status_code, 200)
        documents = response.get_json()["documents"]
        self.assertEqual(len(documents), 3)
        self.assertNotIn(CLASSIFICATION_ADMIN_ONLY, {document["classification"] for document in documents})

    def test_pdf_render_and_download(self):
        self.login("alice", "PatientPass123!")

        render_response = self.client.post(
            "/api/pdf/render",
            json={"title": "진료 메모", "body": "복통 상담 내용\n검사 예약 안내"},
        )

        self.assertEqual(render_response.status_code, 201)
        pdf_id = render_response.get_json()["pdf"]["id"]
        download_response = self.client.get(f"/api/pdf/download/{pdf_id}")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.mimetype, "application/pdf")
        self.assertTrue(download_response.data.startswith(b"%PDF"))
        self.assertIn(KOREAN_FONT_NAME.encode(), download_response.data)
        download_response.close()
        with self.app.app_context():
            self.assertEqual(db.session.query(GeneratedPdf).count(), 3)

    def test_storage_upload_and_download(self):
        self.login("alice", "PatientPass123!")

        upload_response = self.client.post(
            "/api/storage/upload",
            data={
                "file": (io.BytesIO(b"sample document"), "sample.txt"),
                "title": "샘플 업로드",
                "document_type": "테스트 문서",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(upload_response.status_code, 201)
        document_id = upload_response.get_json()["document"]["id"]
        download_response = self.client.get(f"/api/storage/download/{document_id}")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.data, b"sample document")
        download_response.close()
        with self.app.app_context():
            self.assertEqual(db.session.query(MedicalDocument).count(), 5)

    def test_bulk_document_download_triggers_soar_response(self):
        self.login("alice", "PatientPass123!")
        document_ids = []
        for index in range(3):
            upload_response = self.client.post(
                "/api/storage/upload",
                data={
                    "file": (io.BytesIO(f"sample document {index}".encode()), f"sample-{index}.txt"),
                    "title": f"샘플 업로드 {index}",
                    "document_type": "테스트 문서",
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(upload_response.status_code, 201)
            document_ids.append(upload_response.get_json()["document"]["id"])

        for document_id in document_ids:
            download_response = self.client.get(f"/api/storage/download/{document_id}")
            self.assertEqual(download_response.status_code, 200)
            download_response.close()

        with self.app.app_context():
            event_types = {
                event.event_type
                for event in db.session.scalars(select(SecurityEvent)).all()
            }
            self.assertIn("BULK_DOCUMENT_DOWNLOAD", event_types)
            self.assertIn("SOAR_IP_BLOCK_SIMULATED", event_types)
            self.assertIn("SOAR_SESSION_REVOKED", event_types)
            self.assertIn("SOAR_EVIDENCE_COLLECTED", event_types)
            session_record = db.session.scalar(
                select(UserSession).order_by(UserSession.created_at.desc())
            )
            self.assertIsNotNone(session_record.revoked_at)

        response = self.client.get("/api/profile")
        self.assertEqual(response.status_code, 302)

    def test_staff_upload_requires_patient_public_id(self):
        self.login("staff", "StaffPass123!")

        response = self.client.post(
            "/api/storage/upload",
            data={"file": (io.BytesIO(b"sample document"), "sample.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)

    def test_staff_can_upload_for_patient(self):
        self.login("staff", "StaffPass123!")
        with self.app.app_context():
            patient = db.session.scalar(select(User).where(User.username == "alice"))
            patient_public_id = patient.public_id

        response = self.client.post(
            "/api/storage/upload",
            data={
                "file": (io.BytesIO(b"staff upload"), "staff.txt"),
                "patient_public_id": patient_public_id,
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["document"]["owner_patient"]["username"], "alice")

    def test_health_ready_checks_database_and_storage(self):
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["checks"],
            {"database": "ok", "storage": "ok"},
        )

    def test_documents_page_supports_search(self):
        self.login("staff", "StaffPass123!")

        response = self.client.get("/documents?q=정형외과")

        self.assertEqual(response.status_code, 200)
        self.assertIn("정형외과 안내문".encode(), response.data)
        self.assertNotIn("소화기내과 진료의뢰서".encode(), response.data)

    def test_document_upload_page_creates_document(self):
        self.login("alice", "PatientPass123!")

        response = self.client.post(
            "/documents/upload",
            data={
                "file": (io.BytesIO(b"screen upload"), "screen.txt"),
                "title": "화면 업로드",
                "document_type": "테스트 문서",
                "classification": "INTERNAL",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            document = db.session.scalar(
                select(MedicalDocument).where(MedicalDocument.title == "화면 업로드")
            )
            self.assertIsNotNone(document)

    def test_pdf_pages_create_and_list_pdf(self):
        self.login("alice", "PatientPass123!")

        create_response = self.client.post(
            "/pdfs/new",
            data={"title": "화면 PDF", "body": "화면에서 생성한 PDF"},
            follow_redirects=False,
        )

        self.assertEqual(create_response.status_code, 302)
        list_response = self.client.get("/pdfs")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("PDF 생성".encode(), list_response.data)
        with self.app.app_context():
            self.assertEqual(db.session.query(GeneratedPdf).count(), 3)


if __name__ == "__main__":
    unittest.main()
