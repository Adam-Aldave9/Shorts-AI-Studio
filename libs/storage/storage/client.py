"""A thin boto3 wrapper over MinIO/S3.

Configured from the same env vars the rest of the stack uses (``S3_ENDPOINT``,
``S3_BUCKET``, ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``). Path-style
addressing + an explicit endpoint make it work against MinIO locally and real S3
in production with no code change.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import BinaryIO

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError

# Generous read timeout: provider outputs (video) can be tens of MB.
_HTTP_TIMEOUT = httpx.Timeout(30.0, read=600.0)
# Spool downloads in memory up to this size, then transparently fall to a temp file.
_SPOOL_MAX_BYTES = 32 * 1024 * 1024


class Storage:
    """Object-storage facade. One instance per process is plenty."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ) -> None:
        self.endpoint = endpoint or os.environ.get("S3_ENDPOINT", "http://localhost:9000")
        self.bucket = bucket or os.environ.get("S3_BUCKET", "film-assets")
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=access_key or os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
            aws_secret_access_key=secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
            region_name=region,
            # Path-style ("endpoint/bucket/key") is what MinIO speaks.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # -- keys / urls --------------------------------------------------------
    def _url(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    @staticmethod
    def _key(key_or_s3url: str) -> str:
        """Accept either a bare key or a full ``s3://bucket/key`` URL."""
        if key_or_s3url.startswith("s3://"):
            # Drop the scheme + bucket, keep everything after the first slash.
            _, _, rest = key_or_s3url.partition("s3://")
            return rest.split("/", 1)[1] if "/" in rest else ""
        return key_or_s3url

    # -- operations ---------------------------------------------------------
    def ensure_bucket(self) -> None:
        """Create ``self.bucket`` if it does not already exist (idempotent)."""
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._s3.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        """Upload raw bytes; return the ``s3://bucket/key`` URL."""
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self._url(key)

    def put_from_url(self, key: str, url: str, content_type: str | None = None) -> str:
        """Stream-download an http(s) URL and upload it (used for fal outputs)."""
        spool: BinaryIO = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES)
        with httpx.stream("GET", url, follow_redirects=True, timeout=_HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            content_type = content_type or resp.headers.get("content-type", "application/octet-stream")
            for chunk in resp.iter_bytes():
                spool.write(chunk)
        spool.seek(0)
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=spool, ContentType=content_type)
        spool.close()
        return self._url(key)

    def get_to_path(self, key_or_s3url: str, dest: str | Path) -> Path:
        """Download an object to a local path (compositor pulls clips this way)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self.bucket, self._key(key_or_s3url), str(dest))
        return dest

    def exists(self, key_or_s3url: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key_or_s3url))
            return True
        except ClientError:
            return False
