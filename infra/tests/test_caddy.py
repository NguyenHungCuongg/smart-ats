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
from http.client import HTTPResponse

import pytest

# Caddy signs localhost with its own CA; these tests check routing, not certificate trust.
TLS = ssl.create_default_context()
TLS.check_hostname = False
TLS.verify_mode = ssl.CERT_NONE


def get(path: str, auth: str | None = None) -> HTTPResponse:
    request = urllib.request.Request(f"https://localhost{path}")
    if auth is not None:
        request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    # The web dev server compiles a page on its first request.
    response: HTTPResponse = urllib.request.urlopen(request, timeout=60, context=TLS)
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


def test_sse_events_arrive_before_stream_ends() -> None:
    # /api/demo/sse sends five events, one per second, starting immediately.
    with get("/api/demo/sse") as response:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        response.readline()
        first_event = time.monotonic()
        response.read()
    # A buffering proxy would deliver every event at once when the stream closes.
    assert time.monotonic() - first_event > 3
