"""Unit tests for Facebook Page channel integration (encryption, state, adapter logic).

These tests run without requiring a database or external network.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.channels import (
    FacebookError,
    FacebookPage,
    FacebookTokenError,
    GraphAPIAdapter,
    check_facebook_config,
    create_oauth_state,
    decrypt_selection,
    decrypt_token,
    encrypt_selection,
    encrypt_token,
    verify_oauth_state,
)

KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long!")
    monkeypatch.setenv("CHANNEL_TOKEN_KEY", KEY)
    monkeypatch.setenv("FACEBOOK_APP_ID", "fb-app-123")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "fb-secret-456")
    monkeypatch.setenv("FACEBOOK_REDIRECT_URI", "https://localhost/api/channels/facebook/callback")
    monkeypatch.setenv("FACEBOOK_GRAPH_VERSION", "v26.0")


def test_fernet_token_encryption_roundtrip() -> None:
    raw_token = "EAAGm0PX4ZB10BA..."
    encrypted = encrypt_token(raw_token, KEY)
    assert isinstance(encrypted, bytes)
    assert raw_token not in encrypted.decode("ascii", errors="ignore")

    decrypted = decrypt_token(encrypted, KEY)
    assert decrypted == raw_token


def test_oauth_state_creation_and_verification() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    role = "COMPANY_ADMIN"

    state = create_oauth_state(user_id, tenant_id, role)
    claims = verify_oauth_state(state)

    assert claims["sub"] == str(user_id)
    assert claims["tid"] == str(tenant_id)
    assert claims["role"] == role
    assert claims["purpose"] == "facebook_oauth"


def test_oauth_state_expired_raises_400() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(minutes=15)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": "COMPANY_ADMIN",
        "purpose": "facebook_oauth",
        "iat": int(past.timestamp()),
        "exp": int((past + timedelta(minutes=5)).timestamp()),
    }
    expired = jwt.encode(claims, "test-secret-at-least-32-bytes-long!", algorithm="HS256")

    with pytest.raises(HTTPException) as exc:
        verify_oauth_state(expired)
    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail.lower()


def test_oauth_state_invalid_signature_raises_400() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": "COMPANY_ADMIN",
        "purpose": "facebook_oauth",
        "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
    }
    bad = jwt.encode(claims, "different-secret-key-123456789012345", algorithm="HS256")

    with pytest.raises(HTTPException) as exc:
        verify_oauth_state(bad)
    assert exc.value.status_code == 400
    assert "invalid" in exc.value.detail.lower()


def test_check_facebook_config_valid() -> None:
    config = check_facebook_config()
    assert config["app_id"] == "fb-app-123"
    assert config["app_secret"] == "fb-secret-456"
    assert config["redirect_uri"] == "https://localhost/api/channels/facebook/callback"
    assert config["graph_version"] == "v26.0"
    assert config["token_key"] == KEY


def test_check_facebook_config_missing_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FACEBOOK_APP_ID")
    with pytest.raises(HTTPException) as exc:
        check_facebook_config()
    assert exc.value.status_code == 503
    assert "FACEBOOK_APP_ID" in exc.value.detail


def test_page_selection_encryption_roundtrip() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    pages = [
        FacebookPage("p-1", "Page One", "tok-1"),
        FacebookPage("p-2", "Page Two", "tok-2"),
    ]

    encrypted = encrypt_selection(user_id, tenant_id, pages, KEY)
    decrypted = decrypt_selection(encrypted, KEY)

    assert decrypted["sub"] == str(user_id)
    assert decrypted["tid"] == str(tenant_id)
    assert len(decrypted["pages"]) == 2
    assert decrypted["pages"][0]["name"] == "Page One"
    assert decrypted["pages"][1]["access_token"] == "tok-2"


def test_page_selection_expired_raises_400() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    past_exp = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    payload = {"sub": str(user_id), "tid": str(tenant_id), "exp": past_exp, "pages": []}
    fernet = Fernet(KEY.encode())
    import json

    token_str = fernet.encrypt(json.dumps(payload).encode()).decode("ascii")

    with pytest.raises(HTTPException) as exc:
        decrypt_selection(token_str, KEY)
    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail.lower()


def test_graph_api_adapter_distinguishes_code_190() -> None:
    adapter = GraphAPIAdapter()

    # Code 190 -> FacebookTokenError
    error_190 = {"error": {"message": "Session has expired", "code": 190, "error_subcode": 463}}
    with pytest.raises(FacebookTokenError) as exc_token:
        adapter._handle_error(error_190, "Default msg")
    assert exc_token.value.code == 190
    assert exc_token.value.subcode == 463

    # Other error code -> FacebookGraphError
    error_other = {"error": {"message": "Rate limit exceeded", "code": 4}}
    with pytest.raises(FacebookError) as exc_graph:
        adapter._handle_error(error_other, "Default msg")
    assert not isinstance(exc_graph.value, FacebookTokenError)
    assert exc_graph.value.code == 4
