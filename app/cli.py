import click
from flask import current_app
from flask.cli import with_appcontext

from app.db import db


def register_cli_commands(app):
    app.cli.add_command(init_db)
    app.cli.add_command(seed_db)


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
