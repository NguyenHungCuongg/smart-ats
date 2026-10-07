"""Smoke tests for the seaweedfs service (Infra 04).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import os
import urllib.request
import uuid

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from types_boto3_s3 import S3Client


# The address Compose publishes on; the API itself uses S3_ENDPOINT on the Compose network.
def connect(endpoint: str = "http://127.0.0.1:8333") -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
    )


def test_default_bucket_exists() -> None:
    buckets = [b["Name"] for b in connect().list_buckets()["Buckets"]]
    assert os.environ["S3_BUCKET"] in buckets


def test_put_get_round_trip() -> None:
    s3, bucket, key = connect(), os.environ["S3_BUCKET"], f"smoke/{uuid.uuid4().hex}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=b"value")
    try:
        assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == b"value"
    finally:
        s3.delete_object(Bucket=bucket, Key=key)


def test_presigned_get_opens_from_the_browser_host() -> None:
    """Signed against S3_PUBLIC_ENDPOINT, the URL works with no credentials (NFR-SEC-09)."""
    s3, bucket, key = connect(), os.environ["S3_BUCKET"], f"smoke/{uuid.uuid4().hex}.txt"
    s3.put_object(Bucket=bucket, Key=key, Body=b"value")
    try:
        url = connect(os.environ["S3_PUBLIC_ENDPOINT"]).generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=300
        )
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.read() == b"value"
    finally:
        s3.delete_object(Bucket=bucket, Key=key)


def test_wrong_secret_is_rejected() -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:8333",
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key="wrong",
    )
    with pytest.raises(ClientError) as error:
        s3.list_buckets()
    assert error.value.response["Error"]["Code"] == "SignatureDoesNotMatch"
