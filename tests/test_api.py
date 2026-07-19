import tempfile
import unittest

from sqlalchemy import select

from app import create_app
from app.db import db
from app.models import Appointment, DoctorAvailabilitySlot
from app.seed import seed_database


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    APP_NAME = "Test Hospital"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DOCUMENT_STORAGE_ROOT = tempfile.mkdtemp()


class ApiTestCase(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
