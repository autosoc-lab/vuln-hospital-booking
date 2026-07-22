import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.auth import authenticate_user, create_user_session, login_required, revoke_current_session
from app.db import db
from app.models import ROLE_PATIENT, User

auth_bp = Blueprint("auth", __name__)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
MIN_PASSWORD_LENGTH = 6


def registration_form_context(form=None, error=None):
    return {
        "app_name": current_app.config["APP_NAME"],
        "form": form or {},
        "error": error,
    }


def is_valid_email(email):
    return bool(EMAIL_PATTERN.fullmatch(email))


def is_valid_username(username):
    return bool(USERNAME_PATTERN.fullmatch(username))


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


@auth_bp.get("/register")
def register_form():
    return render_template("register.html", **registration_form_context())


@auth_bp.post("/register")
def register():
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    form = {
        "username": username,
        "full_name": full_name,
        "email": email,
    }

    if not username or not full_name or not email or not password:
        return (
            render_template(
                "register.html",
                **registration_form_context(form, "모든 항목을 입력해 주세요."),
            ),
            400,
        )
    if not is_valid_username(username):
        return (
            render_template(
                "register.html",
                **registration_form_context(
                    form,
                    "아이디는 영문으로 시작하고 영문 또는 숫자만 사용할 수 있습니다.",
                ),
            ),
            400,
        )
    if not is_valid_email(email):
        return (
            render_template(
                "register.html",
                **registration_form_context(form, "이메일 형식이 올바르지 않습니다."),
            ),
            400,
        )
    if password != password_confirm:
        return (
            render_template(
                "register.html",
                **registration_form_context(form, "비밀번호 확인이 일치하지 않습니다."),
            ),
            400,
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        return (
            render_template(
                "register.html",
                **registration_form_context(form, "비밀번호는 6자 이상이어야 합니다."),
            ),
            400,
        )

    existing_user = db.session.scalar(
        select(User).where(or_(User.username == username, User.email == email))
    )
    if existing_user:
        return (
            render_template(
                "register.html",
                **registration_form_context(
                    form,
                    "이미 사용 중인 아이디 또는 이메일입니다.",
                ),
            ),
            409,
        )

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=ROLE_PATIENT,
        full_name=full_name,
        email=email,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return (
            render_template(
                "register.html",
                **registration_form_context(
                    form,
                    "이미 사용 중인 아이디 또는 이메일입니다.",
                ),
            ),
            409,
        )

    create_user_session(user, request)
    flash("회원가입이 완료되었습니다.", "success")
    return redirect(url_for("main.index"))


@auth_bp.post("/logout")
@login_required
def logout():
    revoke_current_session()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("main.index"))
