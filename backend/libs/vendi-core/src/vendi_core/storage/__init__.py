"""Almacenamiento de objetos.

Cosechado de `base_saas.storage` **sin** `policy.py`. Decisión de Fase 0
(ADR-016): un solo bucket por región (`vendi-co-media`) con prefijo
`{tenant_id}/` por tenant, en vez de un bucket por tenant. Motivo: decenas de
miles de negocios freemium no caben en el límite práctico de buckets de S3 ni
de MinIO, y la política de bucket-por-tenant de BaseSaaS (`policy.py`,
`bucket_is_world_readable`, `fetch_bucket_policy`) deja de tener sentido cuando
el bucket es compartido: el aislamiento lo da el prefijo y la firma de URLs,
no una política por bucket.
"""

from vendi_core.storage.base import StorageBackend, StoredObject
from vendi_core.storage.factory import create_storage
from vendi_core.storage.minio import ObjectStorage
from vendi_core.storage.s3compat import S3CompatBackend

__all__ = [
    "ObjectStorage",
    "S3CompatBackend",
    "StorageBackend",
    "StoredObject",
    "create_storage",
]
