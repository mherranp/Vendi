from io import BytesIO

from miniopy_async import Minio


class ObjectStorage:
    """Async MinIO object storage wrapper."""

    def __init__(self, client: Minio, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    async def connect(
        cls, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False
    ) -> "ObjectStorage":
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        if not await client.bucket_exists(bucket):
            await client.make_bucket(bucket)
        return cls(client, bucket)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        stream = BytesIO(data)
        await self._client.put_object(self._bucket, key, stream, length=len(data), content_type=content_type)
        return key

    async def get(self, key: str) -> bytes:
        response = await self._client.get_object(self._bucket, key)
        data = await response.read()
        response.close()
        await response.release()
        return data

    async def delete(self, key: str) -> None:
        await self._client.remove_object(self._bucket, key)

    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        from datetime import timedelta

        return await self._client.presigned_get_object(self._bucket, key, expires=timedelta(seconds=expires))
