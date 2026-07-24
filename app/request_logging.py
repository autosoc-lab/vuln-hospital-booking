import json
import logging
import os
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

    current_app.logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))
    return response


def register_file_logging(app):
    # 로그 파일이 지정된 경우(EC2 배포 환경) app.logger에 순수 JSON 라인만 쓰는
    # FileHandler를 추가한다. Wazuh 에이전트가 이 파일을 log_format=json으로
    # 직접 읽어가려면 줄마다 다른 텍스트가 섞이지 않은 순수 JSON이어야 한다.
    log_file = app.config.get("APP_LOG_FILE")
    if not log_file:
        return

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def register_request_event_logging(app):
    register_file_logging(app)
    app.before_request(start_app_event_timer)
    app.after_request(log_app_event)
