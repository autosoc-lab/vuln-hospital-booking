import os

import click
from flask import current_app
from flask.cli import with_appcontext

from app.db import db


def register_cli_commands(app):
    app.cli.add_command(init_db)
    app.cli.add_command(seed_db)
    app.cli.add_command(migrate_storage_to_s3)


@click.command("init-db")
@with_appcontext
def init_db():
    from app import models  # noqa: F401

    db.create_all()
    current_app.logger.info("Database tables initialized")
    click.echo("Database tables initialized.")


@click.command("seed-db")
@with_appcontext
def seed_db():
    from app import models  # noqa: F401
    from app.seed import seed_database

    db.create_all()
    created = seed_database()
    if created:
        current_app.logger.info("Database seed data inserted")
        click.echo("Database seed data inserted.")
        return

    click.echo("Database already has seed data; skipped.")


@click.command("migrate-storage-to-s3")
@with_appcontext
def migrate_storage_to_s3():
    """로컬 디스크에 저장된 문서/생성 PDF를 STORAGE_BACKEND=s3로 설정된 대상 버킷에 업로드한다."""
    from app import storage
    from app.models import GeneratedPdf, MedicalDocument

    if not storage.is_s3_backend():
        click.echo("STORAGE_BACKEND=s3, DOCUMENT_STORAGE_BUCKET을 먼저 설정하세요.")
        return

    local_root = os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])
    relative_paths = [doc.file_path for doc in MedicalDocument.query.all()]
    relative_paths += [pdf.storage_path for pdf in GeneratedPdf.query.all()]

    migrated = 0
    for relative_path in relative_paths:
        local_path = os.path.join(local_root, relative_path)
        if not os.path.isfile(local_path):
            click.echo(f"건너뜀 (파일 없음): {relative_path}")
            continue
        with open(local_path, "rb") as fh:
            storage.save_bytes(relative_path, fh.read())
        migrated += 1
        click.echo(f"업로드 완료: {relative_path}")

    click.echo(f"총 {migrated}개 파일을 S3로 마이그레이션했습니다.")
