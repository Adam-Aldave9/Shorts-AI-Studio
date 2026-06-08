"""Storage round-trip against MinIO. Skipped automatically if MinIO is unreachable
(so the suite stays green without `docker compose up -d minio`)."""

from __future__ import annotations

import os
import uuid

import pytest

from storage import Storage


def _storage_or_skip() -> Storage:
    s = Storage(
        endpoint=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        bucket=f"afp-test-{uuid.uuid4().hex[:8]}",
    )
    try:
        s.ensure_bucket()
    except Exception as exc:  # botocore EndpointConnectionError, etc.
        pytest.skip(f"MinIO not reachable: {exc}")
    return s


def test_put_get_exists_roundtrip(tmp_path):
    s = _storage_or_skip()
    key = "round/trip.bin"
    data = b"hello afp storage"

    url = s.put_bytes(key, data, "application/octet-stream")
    assert url == f"s3://{s.bucket}/{key}"
    assert s.exists(key) is True
    assert s.exists("does/not/exist.bin") is False

    dest = tmp_path / "out.bin"
    s.get_to_path(url, dest)  # accepts the full s3:// URL form
    assert dest.read_bytes() == data
