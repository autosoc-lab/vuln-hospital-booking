import os
import shutil
import tempfile
import unittest

from sqlalchemy import select

from app import create_app
from app.db import db
from app.models import CLASSIFICATION_ADMIN_ONLY, ROLE_PATIENT, MedicalDocument, User
from app.seed import ADMIN_ONLY_DOCUMENT_PATH, ADMIN_ONLY_DOCUMENT_TITLE, seed_database


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


class SeedTestCase(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp()
        TestConfig.DOCUMENT_STORAGE_ROOT = self.storage_dir
        self.app = create_app(TestConfig)
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        shutil.rmtree(self.storage_dir, ignore_errors=True)

    def test_seed_database_backfills_admin_only_document_for_existing_seed_data(self):
        with self.app.app_context():
            db.session.add(
                User(
                    username="alice",
                    password_hash="unused",
                    role=ROLE_PATIENT,
                    full_name="김민지",
                    email="alice@example.local",
                )
            )
            db.session.commit()

            created = seed_database()

            document = db.session.scalar(
                select(MedicalDocument).where(MedicalDocument.title == ADMIN_ONLY_DOCUMENT_TITLE)
            )
            self.assertTrue(created)
            self.assertIsNotNone(document)
            self.assertEqual(document.classification, CLASSIFICATION_ADMIN_ONLY)
            self.assertEqual(document.file_path, ADMIN_ONLY_DOCUMENT_PATH)
            self.assertTrue(os.path.isfile(os.path.join(self.storage_dir, ADMIN_ONLY_DOCUMENT_PATH)))


if __name__ == "__main__":
    unittest.main()
