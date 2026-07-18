from flask import Blueprint, current_app, jsonify, render_template

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html", app_name=current_app.config["APP_NAME"])


@main_bp.get("/health/live")
def health_live():
    return jsonify({"status": "live"})
