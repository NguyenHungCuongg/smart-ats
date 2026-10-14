"""Smoke tests for the redis service (Infra 03).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import os
import uuid

import redis


def connect() -> redis.Redis:
    return redis.Redis(
        host="127.0.0.1",  # the address Compose publishes on
        port=int(os.environ.get("REDIS_HOST_PORT", "6379")),
        decode_responses=True,
    )


def test_ping() -> None:
    assert connect().ping() is True


def test_set_get_round_trip() -> None:
    r = connect()
    key = f"smoke:{uuid.uuid4().hex}"
    r.set(key, "value", ex=60)
    try:
        assert r.get(key) == "value"
    finally:
        r.delete(key)


def test_persistence_is_disabled() -> None:
    """Redis is transport only (SAD §1): no RDB snapshots, no append-only file."""
    r = connect()
    assert r.config_get("save") == {"save": ""}
    assert r.config_get("appendonly") == {"appendonly": "no"}
