import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    APP_NAME = os.environ.get("APP_NAME", "Vulnerable Hospital Booking")
    DOCUMENT_STORAGE_ROOT = os.environ.get("DOCUMENT_STORAGE_ROOT", "storage")
    STORAGE_HEALTHCHECK_PATH = os.environ.get("STORAGE_HEALTHCHECK_PATH", ".healthcheck")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://hospital:hospital@localhost:5432/hospital",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BULK_DOWNLOAD_WINDOW_SECONDS = int(os.environ.get("BULK_DOWNLOAD_WINDOW_SECONDS", "60"))
    BULK_DOWNLOAD_THRESHOLD = int(os.environ.get("BULK_DOWNLOAD_THRESHOLD", "5"))
