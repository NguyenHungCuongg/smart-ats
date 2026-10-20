"""Smoke tests for the caddy service (Infra 06).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from http.client import HTTPResponse

import jwt
import pytest
import redis

# Caddy signs localhost with its own CA; these tests check routing, not certificate trust.
TLS = ssl.create_default_context()
TLS.check_hostname = False
TLS.verify_mode = ssl.CERT_NONE


def get(path: str, auth: str | None = None, timeout: float = 60) -> HTTPResponse:
    request = urllib.request.Request(f"https://localhost{path}")
    if auth is not None:
        request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    # The web dev server compiles a page on its first request.
    response: HTTPResponse = urllib.request.urlopen(request, timeout=timeout, context=TLS)
    return response


def test_api_paths_route_to_api() -> None:
    with get("/api/health") as response:
        assert json.load(response) == {"status": "ok"}
    with get("/openapi.json") as response:
        assert json.load(response)["info"]["title"] == "Smart ATS API"
    with get("/docs") as response:
        assert "swagger-ui" in response.read().decode()


def test_other_paths_route_to_web() -> None:
    with get("/") as response:
        assert response.status == 200


def test_flower_requires_basic_auth() -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        get("/flower/")
    assert error.value.code == 401


def test_flower_routes_to_flower() -> None:
    with get("/flower/", auth=os.environ["FLOWER_BASIC_AUTH"]) as response:
        assert "/flower/static/" in response.read().decode()


def test_sse_events_pass_through_unbuffered() -> None:
    # Any user will do: the stream needs only a valid access token, signed with the stack's secret.
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    token = jwt.encode(
        {"sub": user_id, "tid": tenant_id, "role": "RECRUITER", "exp": time.time() + 60},
        os.environ["JWT_SECRET"],
        "HS256",
    )
    request = urllib.request.Request(
        "https://localhost/api/events/ticket",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=10, context=TLS) as response:
        ticket = json.load(response)["ticket"]

    channel = f"sse:{tenant_id}:{user_id}"
    r = redis.Redis(host="127.0.0.1", port=int(os.environ.get("REDIS_HOST_PORT", "6379")))
    # The stream never ends on its own: a buffering proxy would never deliver this event.
    with get(f"/api/events?ticket={ticket}", timeout=10) as response:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        while r.publish(channel, json.dumps({"event": "smoke", "data": 1})) == 0:
            time.sleep(0.05)
        assert response.readline() == b"event: smoke\n"


# The limits of FR-A1.2, as MAX_DOCUMENT_BYTES in apps/api/app/jobs.py and MAX_BATCH_FILES in
# apps/api/app/uploads.py.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_BATCH_FILES = 50


def post_file(path: str, size: int) -> int:
    """The status of an unauthenticated multipart upload of a `size`-byte file."""
    head = b'--smoke\r\nContent-Disposition: form-data; name="file"; filename="cv.pdf"\r\n\r\n'
    request = urllib.request.Request(
        f"https://localhost{path}",
        data=head + b"0" * size + b"\r\n--smoke--\r\n",
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=smoke"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60, context=TLS) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        ("/api/jobs", MAX_DOCUMENT_BYTES),
        (f"/api/jobs/{uuid.uuid4()}/uploads", MAX_BATCH_FILES * MAX_DOCUMENT_BYTES),
    ],
    ids=["JD Document", "Upload Batch"],
)
def test_upload_routes_refuse_an_oversized_body_before_the_api(path: str, limit: int) -> None:
    # The API answers an unauthenticated upload with 401, so a 413 can only come from Caddy.
    assert post_file(path, limit) == 401
    assert post_file(path, limit + 1024 * 1024) == 413
