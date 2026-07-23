from vendi_core.errors.domain import ValidationError
from vendi_core.storage.base import StorageBackend
from vendi_core.storage.s3compat import S3CompatBackend

SUPPORTED_PROVIDERS = {"minio", "s3", "oss"}


def create_storage(
    provider: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    secure: bool = False,
) -> StorageBackend:
    """Factory for storage backends. Use STORAGE_PROVIDER env var to toggle.

    All current providers (minio, s3, oss) use the S3-compatible protocol, so
    they share the same backend implementation with different endpoints.
    """
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValidationError(
            f"Unsupported storage provider: {provider!r}. Supported: {sorted(SUPPORTED_PROVIDERS)}",
            code="UNSUPPORTED_STORAGE_PROVIDER",
        )
    return S3CompatBackend(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        secure=secure,
    )
