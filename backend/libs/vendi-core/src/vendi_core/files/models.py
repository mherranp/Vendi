from typing import Any

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from vendi_core.db.base import Base, SoftDeleteMixin, TenantModel

# JSON type that is JSONB on Postgres and plain JSON on SQLite (tests).
# ``with_variant`` lets Alembic + the ORM pick the right flavour per dialect.
_JsonType = JSON().with_variant(JSONB(), "postgresql")


class File(Base, TenantModel, SoftDeleteMixin):
    """Tenant-scoped file metadata. The bytes live in the object store.

    Soft-delete: ``deleted_at`` flags a file as removed from the listing. The
    retention runner physically removes the row (and asks the storage layer to
    drop the object) after the configured grace period.

    Lifecycle states (``status`` column):
      - ``draft``  — chunked upload init succeeded; bytes not yet assembled.
      - ``active`` — fully uploaded, available for download. This is the
        default for non-chunked single-shot uploads.
    """

    __tablename__ = "files"

    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    etag: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # ``metadata`` is reserved by SQLAlchemy's declarative ``Base`` (points at
    # the MetaData object), so we expose the column under ``extra_metadata`` at
    # the Python level while keeping the on-disk column name ``metadata``
    # — matches the spec body shape and JSONB filter queries.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", _JsonType, nullable=True)
    thumbnails: Mapped[dict[str, Any] | None] = mapped_column(_JsonType, nullable=True)
