from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.auth import authenticate_user, create_user_session, login_required, revoke_current_session

auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/login")
def login_form():
    return render_template("login.html", app_name=current_app.config["APP_NAME"])


@auth_bp.post("/login")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = authenticate_user(username, password)
    if not user:
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return render_template("login.html", app_name=current_app.config["APP_NAME"]), 401

    create_user_session(user, request)
    flash("로그인되었습니다.", "success")
    return redirect(url_for("main.index"))


@auth_bp.post("/logout")
@login_required
def logout():
    revoke_current_session()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("main.index"))
