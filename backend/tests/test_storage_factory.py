"""Fábrica de backends de almacenamiento.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_storage_factory.py`.
Adaptación: `base_saas` → `vendi_core`. Se añade el caso del proveedor en
mayúsculas y el de la propagación de parámetros, que BaseSaaS no cubría.
"""

from __future__ import annotations

import pytest

from vendi_core.errors import ValidationError
from vendi_core.storage import S3CompatBackend, create_storage
from vendi_core.storage.factory import SUPPORTED_PROVIDERS


def test_minio_produce_un_backend_s3_compatible():
    backend = create_storage(
        provider="minio",
        endpoint="minio:9000",
        access_key="clave",
        secret_key="secreto",
    )
    assert isinstance(backend, S3CompatBackend)


def test_s3_de_aws_produce_el_mismo_backend():
    backend = create_storage(
        provider="s3",
        endpoint="s3.amazonaws.com",
        access_key="clave",
        secret_key="secreto",
        region="us-west-2",
        secure=True,
    )
    assert isinstance(backend, S3CompatBackend)


def test_oss_de_alibaba_produce_el_mismo_backend():
    backend = create_storage(
        provider="oss",
        endpoint="oss-cn-hangzhou.aliyuncs.com",
        access_key="clave",
        secret_key="secreto",
        secure=True,
    )
    assert isinstance(backend, S3CompatBackend)


def test_el_nombre_del_proveedor_no_distingue_mayusculas():
    assert isinstance(create_storage("MinIO", "minio:9000", "clave", "secreto"), S3CompatBackend)


def test_un_proveedor_desconocido_falla_con_un_error_tipado():
    """No un `KeyError` ni un backend a medio construir: un error de dominio
    con código, que es lo que el manejador de errores sabe convertir en 4xx."""
    with pytest.raises(ValidationError) as excinfo:
        create_storage(
            provider="gcs",
            endpoint="storage.googleapis.com",
            access_key="clave",
            secret_key="secreto",
        )
    assert excinfo.value.code == "UNSUPPORTED_STORAGE_PROVIDER"


def test_los_proveedores_soportados_son_los_tres_compatibles_con_s3():
    assert SUPPORTED_PROVIDERS == {"minio", "s3", "oss"}
