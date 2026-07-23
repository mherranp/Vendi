from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StoredObject:
    """Metadata for a stored object."""

    bucket: str
    key: str
    size: int
    content_type: str
    last_modified: datetime | None = None
    etag: str = ""


class StorageBackend(ABC):
    """Abstract storage backend. Implementations must be async."""

    @abstractmethod
    async def ensure_bucket(self, bucket: str) -> None:
        """Create the bucket if it does not exist."""

    @abstractmethod
    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Upload bytes to bucket/key."""

    @abstractmethod
    async def get(self, bucket: str, key: str) -> bytes:
        """Download bytes from bucket/key."""

    async def get_range(self, bucket: str, key: str, *, offset: int, length: int) -> bytes:
        """Download a byte-range slice of ``bucket/key``.

        Default implementation reads the full object and slices in Python so
        backends without native range support still satisfy the contract.
        S3-compatible backends override this to use ``get_object(offset=,
        length=)`` which streams only the requested bytes.

        ``offset`` is 0-based inclusive; ``length`` is the number of bytes
        to return. Callers enforce ``length >= 0``; an empty slice returns
        ``b''`` without hitting the backend.
        """
        if length <= 0:
            return b""
        data = await self.get(bucket, key)
        return data[offset : offset + length]

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None:
        """Remove bucket/key."""

    @abstractmethod
    async def get_presigned_url(
        self,
        bucket: str,
        key: str,
        expires_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        """Generate a presigned URL for GET or PUT."""

    @abstractmethod
    async def list_objects(self, bucket: str, prefix: str = "") -> list[StoredObject]:
        """List objects in a bucket, optionally filtered by prefix."""

    @abstractmethod
    async def stat(self, bucket: str, key: str) -> StoredObject:
        """Return metadata for a single object."""
