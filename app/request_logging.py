import json
import time

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


def register_request_event_logging(app):
    app.before_request(start_app_event_timer)
    app.after_request(log_app_event)
