"""Smoke tests for the Caddy edge reverse proxy service (Infra 06).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request

import pytest

SSL_CONTEXT = ssl._create_unverified_context()
BASE_URL = "https://localhost"


def test_api_health_proxied() -> None:
    req = urllib.request.Request(f"{BASE_URL}/api/health")
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok"}


def test_openapi_spec_proxied() -> None:
    req = urllib.request.Request(f"{BASE_URL}/openapi.json")
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as response:
        assert response.status == 200
        data = json.load(response)
        assert "openapi" in data


def test_web_proxied() -> None:
    req = urllib.request.Request(f"{BASE_URL}/")
    with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as response:
        assert response.status == 200


def test_flower_proxied_requires_basic_auth() -> None:
    req = urllib.request.Request(f"{BASE_URL}/flower/")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT)
    assert error.value.code == 401


def test_flower_proxied_with_basic_auth() -> None:
    auth = os.environ["FLOWER_BASIC_AUTH"]
    req = urllib.request.Request(f"{BASE_URL}/flower/")
    req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as response:
        assert response.status == 200
        body = response.read().decode()
        assert "Flower" in body


def test_sse_streaming_unbuffered() -> None:
    start = time.monotonic()
    first_chunk_time: float | None = None
    chunks: list[str] = []

    req = urllib.request.Request(f"{BASE_URL}/api/demo/sse")
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as response:
        assert response.status == 200
        assert "text/event-stream" in response.headers.get("Content-Type", "")
        for line in response:
            text = line.decode().strip()
            if text.startswith("data:"):
                chunks.append(text)
                if first_chunk_time is None:
                    first_chunk_time = time.monotonic() - start
            if len(chunks) >= 2:
                break

    assert first_chunk_time is not None
    # First chunk is emitted after 1s; if buffered, it wouldn't arrive until stream completes (5s)
    assert first_chunk_time < 3.0
    assert len(chunks) >= 2
