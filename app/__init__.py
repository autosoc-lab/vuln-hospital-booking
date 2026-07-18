from flask import Flask

from app.auth import load_logged_in_user
from app.cli import register_cli_commands
from app.config import Config
from app.db import db
from app.routes.auth import auth_bp
from app.routes import main_bp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    register_cli_commands(app)
    app.before_request(load_logged_in_user)

    return app
