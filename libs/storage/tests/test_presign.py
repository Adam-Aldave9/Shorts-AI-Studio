"""Presigned URLs are computed locally, so these run without MinIO."""

from __future__ import annotations

from urllib.parse import unquote

from storage import Storage


def _storage() -> Storage:
    return Storage(endpoint="http://minio:9000", bucket="b", access_key="k", secret_key="s")


def test_presigned_url_is_signed_for_the_public_endpoint(monkeypatch):
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT", "http://localhost:9000")
    url = _storage().presigned_get_url("s3://b/p1/final.mp4")
    assert url.startswith("http://localhost:9000/b/p1/final.mp4?")
    assert "X-Amz-Signature" in url
    assert "response-content-disposition" not in url


def test_presigned_url_falls_back_to_the_endpoint(monkeypatch):
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT", raising=False)
    url = _storage().presigned_get_url("p1/final.mp4")
    assert url.startswith("http://minio:9000/b/p1/final.mp4?")


def test_download_name_sets_content_disposition(monkeypatch):
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT", "http://localhost:9000")
    url = _storage().presigned_get_url("p1/final.mp4", download_name="film-v2.mp4")
    assert "response-content-disposition" in url
    assert 'filename="film-v2.mp4"' in unquote(url)
