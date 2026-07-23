"""Retention hook for the ``files`` table.

Makes ``files`` a true soft-delete: ``FileService.delete`` only sets
``deleted_at``. The object stays in the bucket until the retention runner's
grace period (30 days by default) elapses, at which point this hook removes
the binary and the runner then drops the database row.

The hook is permissive: if an object has already been deleted manually (or the
bucket is gone), the delete call emits a warning and the row is still allowed
to disappear. The alternative — failing the whole policy — would leave orphan
rows forever.
"""

from __future__ import annotations

from collections.abc import Mapping

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from vendi_core.retention.runner import PrePurgeHook
from vendi_core.storage.base import StorageBackend

logger = structlog.get_logger()


def make_storage_cleanup_hook(storage: StorageBackend) -> PrePurgeHook:
    async def _hook(session: AsyncSession, rows: list[Mapping]) -> None:
        for row in rows:
            bucket, key = row["bucket"], row["key"]
            try:
                await storage.delete(bucket, key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "files_storage_delete_failed",
                    bucket=bucket,
                    key=key,
                    error=str(exc),
                )

    return _hook
