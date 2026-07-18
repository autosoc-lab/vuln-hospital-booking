from datetime import timezone, timedelta
from functools import wraps
from hashlib import sha256
import secrets

from flask import g, redirect, session, url_for
from werkzeug.security import check_password_hash

from app.db import db
from app.models import User, UserSession, utc_now

SESSION_DAYS = 1


def hash_value(value):
    return sha256(value.encode("utf-8")).hexdigest()


def ensure_aware_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def authenticate_user(username, password):
    user = User.query.filter_by(username=username).one_or_none()
    if not user or not check_password_hash(user.password_hash, password):
        return None
    return user


def create_user_session(user, request):
    token = secrets.token_urlsafe(32)
    user_session = UserSession(
        user=user,
        session_token_hash=hash_value(token),
        role_snapshot=user.role,
        source_ip=request.headers.get("X-Forwarded-For", request.remote_addr),
        user_agent_hash=hash_value(request.headers.get("User-Agent", "")),
        expires_at=utc_now() + timedelta(days=SESSION_DAYS),
    )
    db.session.add(user_session)
    db.session.commit()

    session.clear()
    session["user_id"] = user.id
    session["user_public_id"] = user.public_id
    session["role"] = user.role
    session["session_id"] = user_session.id
    session["session_token"] = token

    return user_session


def revoke_current_session():
    if g.current_session:
        g.current_session.revoked_at = utc_now()
        db.session.commit()
    session.clear()


def load_logged_in_user():
    g.current_user = None
    g.current_session = None

    session_id = session.get("session_id")
    session_token = session.get("session_token")
    user_id = session.get("user_id")
    if not session_id or not session_token or not user_id:
        return

    user_session = UserSession.query.filter_by(id=session_id, user_id=user_id).one_or_none()
    if not user_session:
        session.clear()
        return

    now = utc_now()
    token_matches = user_session.session_token_hash == hash_value(session_token)
    expires_at = ensure_aware_utc(user_session.expires_at)
    if user_session.revoked_at or expires_at <= now or not token_matches:
        session.clear()
        return

    g.current_session = user_session
    g.current_user = user_session.user


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if not g.current_user:
            return redirect(url_for("auth.login_form"))
        return view(**kwargs)

    return wrapped_view
