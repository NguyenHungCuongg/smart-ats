"""Readiness: can the API reach PostgreSQL, Redis and object storage (NFR-REL-05, SAD §8)."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from functools import cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from redis.asyncio import Redis
from sqlalchemy import text

from app.db import async_engine

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client  # dev-only stubs

log = logging.getLogger(__name__)

type Check = Callable[[], Awaitable[None]]

# Per dependency, so a hung one cannot hold the response past an orchestrator's own timeout.
TIMEOUT_SECONDS = 3.0


async def _database() -> None:
    # SELECT 1 reads no tenant table, so it needs no tenant context.
    async with async_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _redis() -> None:
    client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        await client.ping()
    finally:
        await client.aclose()


@cache
def _s3() -> "S3Client":
    return boto3.client(
        "s3",
        # Empty in production: boto3 then talks to AWS S3.
        endpoint_url=os.environ.get("S3_ENDPOINT") or None,
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        # Short and unretried: the thread behind a timed-out check cannot be cancelled.
        config=Config(
            signature_version="s3v4", connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}
        ),
    )


async def _object_storage() -> None:
    # boto3 is blocking; head_bucket also proves the credentials and the bucket.
    await asyncio.to_thread(_s3().head_bucket, Bucket=os.environ["S3_BUCKET"])


CHECKS: dict[str, Check] = {
    "database": _database,
    "redis": _redis,
    "object_storage": _object_storage,
}


async def _passes(name: str, check: Check) -> bool:
    try:
        await asyncio.wait_for(check(), TIMEOUT_SECONDS)
    except Exception:
        # The traceback may name hosts and credentials: it goes to the log, not the response.
        log.exception("readiness check failed: %s", name)
        return False
    return True


async def failed_dependencies() -> list[str]:
    """Names of the dependencies that did not answer; empty when all did."""
    results = await asyncio.gather(*(_passes(name, check) for name, check in CHECKS.items()))
    return [name for name, passed in zip(CHECKS, results, strict=True) if not passed]
