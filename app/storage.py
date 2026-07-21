import io
import os

from flask import abort, current_app, send_file
from werkzeug.utils import safe_join


def is_s3_backend():
    return current_app.config["STORAGE_BACKEND"] == "s3"


def _s3_client():
    import boto3

    return boto3.client("s3", region_name=current_app.config["AWS_REGION"])


def _s3_bucket():
    return current_app.config["DOCUMENT_STORAGE_BUCKET"]


def _local_root():
    return os.path.abspath(current_app.config["DOCUMENT_STORAGE_ROOT"])


def _local_path(relative_path):
    return safe_join(_local_root(), relative_path)


def save_upload(relative_path, file_storage):
    if is_s3_backend():
        _s3_client().upload_fileobj(file_storage, _s3_bucket(), relative_path)
        return

    absolute_path = _local_path(relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    file_storage.save(absolute_path)


def save_bytes(relative_path, data):
    if is_s3_backend():
        _s3_client().put_object(Bucket=_s3_bucket(), Key=relative_path, Body=data)
        return

    absolute_path = _local_path(relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    with open(absolute_path, "wb") as fh:
        fh.write(data)


def stored_file_size(relative_path):
    if is_s3_backend():
        response = _s3_client().head_object(Bucket=_s3_bucket(), Key=relative_path)
        return response["ContentLength"]

    return os.path.getsize(_local_path(relative_path))


def send_stored_file(relative_path, download_name, as_attachment=True):
    if is_s3_backend():
        client = _s3_client()
        try:
            obj = client.get_object(Bucket=_s3_bucket(), Key=relative_path)
        except client.exceptions.NoSuchKey:
            abort(404)
        return send_file(
            io.BytesIO(obj["Body"].read()),
            as_attachment=as_attachment,
            download_name=download_name,
        )

    absolute_path = _local_path(relative_path)
    if not absolute_path or not os.path.isfile(absolute_path):
        abort(404)
    return send_file(absolute_path, as_attachment=as_attachment, download_name=download_name)


def check_storage_health():
    if is_s3_backend():
        _s3_client().head_bucket(Bucket=_s3_bucket())
        return

    root = _local_root()
    healthcheck_path = _local_path(current_app.config["STORAGE_HEALTHCHECK_PATH"])
    os.makedirs(root, exist_ok=True)
    with open(healthcheck_path, "a", encoding="utf-8"):
        os.utime(healthcheck_path, None)
