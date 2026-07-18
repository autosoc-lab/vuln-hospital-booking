import click
from flask import current_app
from flask.cli import with_appcontext

from app.db import db


def register_cli_commands(app):
    app.cli.add_command(init_db)


@click.command("init-db")
@with_appcontext
def init_db():
    from app import models  # noqa: F401

    db.create_all()
    current_app.logger.info("Database tables initialized")
    click.echo("Database tables initialized.")
