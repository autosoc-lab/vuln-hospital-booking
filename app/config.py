import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    APP_NAME = os.environ.get("APP_NAME", "Vulnerable Hospital Booking")
    DOCUMENT_STORAGE_ROOT = os.environ.get("DOCUMENT_STORAGE_ROOT", "storage")
    STORAGE_HEALTHCHECK_PATH = os.environ.get("STORAGE_HEALTHCHECK_PATH", ".healthcheck")
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
    DOCUMENT_STORAGE_BUCKET = os.environ.get("DOCUMENT_STORAGE_BUCKET", "")
    AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://hospital:hospital@localhost:5432/hospital",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
