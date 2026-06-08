"""Object storage helper: a thin boto3 wrapper over MinIO/S3 (spec §2.4, §8).

Shared by the Phase 1 sequential driver, the compositor, and the Phase 2 worker so
asset archival is implemented once. Adapters stay storage-agnostic; everything that
needs to push/pull bytes goes through ``Storage``.
"""

from storage.client import Storage

__all__ = ["Storage"]
