from datetime import timedelta
from io import BytesIO

from miniopy_async import Minio

from vendi_core.storage.base import StorageBackend, StoredObject


class S3CompatBackend(StorageBackend):
    """S3-compatible backend using miniopy-async.

    Works with MinIO, AWS S3, Alibaba OSS, DigitalOcean Spaces, and any other
    S3-compatible object store by pointing `endpoint` at the provider.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = False,
    ):
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )

    @property
    def client(self) -> Minio:
        return self._client

    async def ensure_bucket(self, bucket: str) -> None:
        if not await self._client.bucket_exists(bucket):
            await self._client.make_bucket(bucket)

    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        stream = BytesIO(data)
        await self._client.put_object(bucket, key, stream, length=len(data), content_type=content_type)
        return StoredObject(bucket=bucket, key=key, size=len(data), content_type=content_type)

    async def get(self, bucket: str, key: str) -> bytes:
        response = await self._client.get_object(bucket, key)
        try:
            return await response.read()
        finally:
            response.close()
            await response.release()

    async def get_range(self, bucket: str, key: str, *, offset: int, length: int) -> bytes:
        """Stream only ``[offset, offset+length)`` from the object store.

        miniopy-async's ``get_object`` supports ``offset`` + ``length`` which
        maps to an S3 ``Range: bytes=offset-(offset+length-1)`` request. The
        object store transfers only the requested slice — for a 500MB file
        that the client wants the first 1 KB of, we avoid pulling the full
        500MB over the wire.
        """
        if length <= 0:
            return b""
        response = await self._client.get_object(bucket, key, offset=offset, length=length)
        try:
            return await response.read()
        finally:
            response.close()
            await response.release()

    async def delete(self, bucket: str, key: str) -> None:
        await self._client.remove_object(bucket, key)

    async def get_presigned_url(
        self,
        bucket: str,
        key: str,
        expires_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        expires = timedelta(seconds=expires_seconds)
        if method.upper() == "PUT":
            return await self._client.presigned_put_object(bucket, key, expires=expires)
        return await self._client.presigned_get_object(bucket, key, expires=expires)

    async def list_objects(self, bucket: str, prefix: str = "") -> list[StoredObject]:
        result: list[StoredObject] = []
        objects = await self._client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            result.append(
                StoredObject(
                    bucket=bucket,
                    key=obj.object_name or "",
                    size=obj.size or 0,
                    content_type=obj.content_type or "application/octet-stream",
                    last_modified=obj.last_modified,
                    etag=(obj.etag or "").strip('"'),
                )
            )
        return result

    async def stat(self, bucket: str, key: str) -> StoredObject:
        obj = await self._client.stat_object(bucket, key)
        return StoredObject(
            bucket=bucket,
            key=key,
            size=obj.size or 0,
            content_type=obj.content_type or "application/octet-stream",
            last_modified=obj.last_modified,
            etag=(obj.etag or "").strip('"'),
        )
