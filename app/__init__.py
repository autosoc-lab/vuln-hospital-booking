from flask import Flask

from app.config import Config
from app.db import db
from app.routes import main_bp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)

    app.register_blueprint(main_bp)

    return app
