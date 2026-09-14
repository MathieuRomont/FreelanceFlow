"""InvoiceArtifact use cases with explicit transactions and no HTTP dependencies."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.invoice_artifacts import (
    InvoiceArtifact,
    InvoiceArtifactMetadata,
    freeze_invoice_artifact,
)


class InvoiceArtifactResourceNotFound(LookupError):
    """A workspace-scoped artifact or target revision is unavailable."""


class InvoiceArtifactStore(Protocol):
    def revision_exists(self, invoice_id: UUID, revision: int) -> bool: ...
    def add(self, value: InvoiceArtifact) -> None: ...
    def list_metadata(self, invoice_id: UUID, revision: int) -> list[InvoiceArtifactMetadata]: ...
    def get_metadata(self, artifact_id: UUID) -> InvoiceArtifactMetadata | None: ...
    def get(self, artifact_id: UUID) -> InvoiceArtifact | None: ...


class InvoiceArtifactTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceArtifactStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvoiceArtifactService:
    def __init__(
        self,
        transaction: InvoiceArtifactTransaction,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def create(
        self,
        *,
        workspace_id: UUID,
        invoice_id: UUID,
        revision: int,
        media_type: str,
        content: bytes,
    ) -> InvoiceArtifactMetadata:
        with self.transaction(workspace_id) as store:
            if not store.revision_exists(invoice_id, revision):
                raise InvoiceArtifactResourceNotFound("Invoice artifact resource not found")
            artifact = freeze_invoice_artifact(
                artifact_id=uuid4(),
                workspace_id=workspace_id,
                invoice_id=invoice_id,
                invoice_revision=revision,
                media_type=media_type,
                content=content,
                created_at=self.clock(),
            )
            store.add(artifact)
        return artifact.metadata

    def list_metadata(
        self, workspace_id: UUID, invoice_id: UUID, revision: int
    ) -> list[InvoiceArtifactMetadata]:
        with self.transaction(workspace_id) as store:
            if not store.revision_exists(invoice_id, revision):
                raise InvoiceArtifactResourceNotFound("Invoice artifact resource not found")
            return store.list_metadata(invoice_id, revision)

    def get_metadata(self, workspace_id: UUID, artifact_id: UUID) -> InvoiceArtifactMetadata:
        with self.transaction(workspace_id) as store:
            metadata = store.get_metadata(artifact_id)
            if metadata is None:
                raise InvoiceArtifactResourceNotFound("Invoice artifact resource not found")
        return metadata

    def get_content(self, workspace_id: UUID, artifact_id: UUID) -> InvoiceArtifact:
        with self.transaction(workspace_id) as store:
            artifact = store.get(artifact_id)
            if artifact is None:
                raise InvoiceArtifactResourceNotFound("Invoice artifact resource not found")
        return artifact
