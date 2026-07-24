import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from flask import current_app, g, request


IGNORED_EVENT_PATH_PREFIXES = ("/static/",)


def should_log_app_event(path):
    return not path.startswith(IGNORED_EVENT_PATH_PREFIXES)


def start_app_event_timer():
    if should_log_app_event(request.path):
        g.app_event_started_at = time.perf_counter()


def log_app_event(response):
    if not should_log_app_event(request.path):
        return response

    started_at = getattr(g, "app_event_started_at", None)
    duration_ms = None
    if started_at is not None:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

    current_user = getattr(g, "current_user", None)
    event = {
        "event": "app_request",
        "method": request.method,
        "path": request.path,
        "endpoint": request.endpoint,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_id": current_user.public_id if current_user else None,
        "user_role": current_user.role if current_user else None,
        "content_length": request.content_length,
    }

    request_id = request.headers.get("X-Request-ID")
    if request_id:
        event["request_id"] = request_id

    query_string = request.query_string.decode("utf-8", errors="replace")
    if query_string:
        event["query_string"] = query_string

    current_app.logger.info(
        "app_event %s",
        json.dumps(event, ensure_ascii=False, sort_keys=True),
    )
    return response


def format_access_log_line(response):
    query_string = request.query_string.decode("utf-8", errors="replace")
    path = request.path
    if query_string:
        path = f"{path}?{query_string}"

    remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr) or "-"
    content_length = response.calculate_content_length()
    response_size = content_length if content_length is not None else None
    protocol = request.environ.get("SERVER_PROTOCOL", "HTTP/1.1")
    event = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "event": "access_request",
        "srcip": remote_addr,
        "method": request.method,
        "path": request.path,
        "url": path,
        "http_version": protocol,
        "status": response.status_code,
        "size": response_size,
        "referer": request.referrer or "-",
        "user_agent": request.user_agent.string or "-",
    }

    if query_string:
        event["query_string"] = query_string

    view_args = request.view_args or {}
    document_id = view_args.get("public_id")
    if document_id and request.path.startswith(
        ("/api/storage/download/", "/documents/", "/clinic-guides/")
    ):
        event["document_id"] = document_id

    return json.dumps(event, ensure_ascii=False, sort_keys=True)


def register_file_access_logging(app):
    access_log_path = app.config.get("ACCESS_LOG_PATH")
    if not access_log_path:
        return

    access_log_dir = os.path.dirname(access_log_path)
    if access_log_dir:
        os.makedirs(access_log_dir, exist_ok=True)
    access_logger = logging.getLogger("access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    if not any(
        isinstance(handler, RotatingFileHandler)
        and getattr(handler, "baseFilename", None) == os.path.abspath(access_log_path)
        for handler in access_logger.handlers
    ):
        handler = RotatingFileHandler(
            access_log_path,
            maxBytes=app.config.get("ACCESS_LOG_MAX_BYTES", 10 * 1024 * 1024),
            backupCount=app.config.get("ACCESS_LOG_BACKUP_COUNT", 5),
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        access_logger.addHandler(handler)

    @app.after_request
    def log_access_request(response):
        access_logger.info(format_access_log_line(response))
        return response


def register_request_event_logging(app):
    app.before_request(start_app_event_timer)
    app.after_request(log_app_event)
    register_file_access_logging(app)
