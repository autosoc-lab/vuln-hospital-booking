from flask import Blueprint, current_app, render_template

auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/login")
def login_form():
    return render_template("login.html", app_name=current_app.config["APP_NAME"])
