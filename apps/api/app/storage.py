"""Object storage for JD and CV Documents (SAD §3); keys start with t/{tenant_id}/ (SAD §4.3)."""

import os
from functools import cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client  # dev-only stubs


@cache
def _s3() -> "S3Client":
    return boto3.client(
        "s3",
        # Empty in production: boto3 then talks to AWS S3.
        endpoint_url=os.environ.get("S3_ENDPOINT") or None,
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
    )


def put(key: str, data: bytes) -> None:
    _s3().put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=data)


def get(key: str) -> bytes:
    return _s3().get_object(Bucket=os.environ["S3_BUCKET"], Key=key)["Body"].read()
