"""Smoke tests for the flower service (Infra 03).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import base64
import os
import urllib.error
import urllib.request

import pytest

# Served under /flower so Caddy (Infra 06) can proxy it as-is.
URL = "http://127.0.0.1:5555/flower/"


def get(auth: str | None) -> str:
    request = urllib.request.Request(URL)
    if auth is not None:
        request.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(request, timeout=10) as response:
        body: str = response.read().decode()
        return body


def test_dashboard_requires_basic_auth() -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        get(auth=None)
    assert error.value.code == 401


def test_dashboard_loads_under_url_prefix() -> None:
    body = get(auth=os.environ["FLOWER_BASIC_AUTH"])
    assert "Flower" in body
    assert "/flower/static/" in body
