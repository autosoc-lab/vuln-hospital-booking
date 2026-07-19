import io
import json
import shutil
import tempfile
import unittest

from sqlalchemy import select

from app import create_app
from app.db import db
from app.models import Appointment, DoctorAvailabilitySlot, GeneratedPdf, MedicalDocument, User
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

    def test_doctors_search_filters_by_name_or_specialty(self):
        self.login("alice", "PatientPass123!")

        response = self.client.get("/api/doctors/search?q=소화기")

        self.assertEqual(response.status_code, 200)
        doctors = response.get_json()["doctors"]
        self.assertEqual(len(doctors), 1)
        self.assertEqual(doctors[0]["name"], "김도현")
        self.assertEqual(doctors[0]["department"]["name"], "내과")

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
            self.assertEqual(db.session.query(MedicalDocument).count(), 4)

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
