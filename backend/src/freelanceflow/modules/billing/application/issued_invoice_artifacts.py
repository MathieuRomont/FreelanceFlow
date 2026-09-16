"""IssuedInvoice artifact use cases with explicit transaction ownership."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifact,
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
    freeze_issued_invoice_artifact,
)
from freelanceflow.modules.billing.domain.issued_invoices import IssuedInvoice


class IssuedInvoiceArtifactResourceNotFound(LookupError):
    """A workspace-scoped issued invoice or artifact is unavailable."""


class IssuedInvoiceArtifactRenderer(Protocol):
    representation: IssuedInvoiceRepresentation
    renderer_version: str
    media_type: str

    def render(self, invoice: IssuedInvoice) -> bytes: ...


class IssuedInvoiceArtifactStore(Protocol):
    def lock_issued_invoice(self, issued_invoice_id: UUID) -> IssuedInvoice | None: ...
    def issued_invoice_exists(self, issued_invoice_id: UUID) -> bool: ...
    def get_by_generation(
        self,
        issued_invoice_id: UUID,
        representation: IssuedInvoiceRepresentation,
        renderer_version: str,
    ) -> IssuedInvoiceArtifactMetadata | None: ...
    def add(self, value: IssuedInvoiceArtifact) -> None: ...
    def list_metadata(
        self, issued_invoice_id: UUID
    ) -> list[IssuedInvoiceArtifactMetadata]: ...
    def get_metadata(
        self, artifact_id: UUID
    ) -> IssuedInvoiceArtifactMetadata | None: ...
    def get(self, artifact_id: UUID) -> IssuedInvoiceArtifact | None: ...


class IssuedInvoiceArtifactTransaction(Protocol):
    def __call__(
        self, workspace_id: UUID
    ) -> AbstractContextManager[IssuedInvoiceArtifactStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IssuedInvoiceArtifactService:
    def __init__(
        self,
        transaction: IssuedInvoiceArtifactTransaction,
        renderer: IssuedInvoiceArtifactRenderer,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.renderer = renderer
        self.clock = clock

    def generate_pdf(
        self, *, workspace_id: UUID, issued_invoice_id: UUID
    ) -> IssuedInvoiceArtifactMetadata:
        representation = self.renderer.representation
        with self.transaction(workspace_id) as store:
            invoice = store.lock_issued_invoice(issued_invoice_id)
            if invoice is None:
                raise IssuedInvoiceArtifactResourceNotFound(
                    "Issued invoice artifact resource not found"
                )
            existing = store.get_by_generation(
                issued_invoice_id,
                representation,
                self.renderer.renderer_version,
            )
            if existing is not None:
                return existing
            created_at = self.clock()
            if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
                raise ValueError("Issued artifact clock must return a UTC timestamp")
            artifact = freeze_issued_invoice_artifact(
                artifact_id=uuid4(),
                workspace_id=workspace_id,
                issued_invoice_id=invoice.id,
                representation=representation,
                renderer_version=self.renderer.renderer_version,
                media_type=self.renderer.media_type,
                content=self.renderer.render(invoice),
                created_at=created_at,
            )
            store.add(artifact)
        return artifact.metadata

    def list_metadata(
        self, workspace_id: UUID, issued_invoice_id: UUID
    ) -> list[IssuedInvoiceArtifactMetadata]:
        with self.transaction(workspace_id) as store:
            if not store.issued_invoice_exists(issued_invoice_id):
                raise IssuedInvoiceArtifactResourceNotFound(
                    "Issued invoice artifact resource not found"
                )
            return store.list_metadata(issued_invoice_id)

    def get_metadata(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> IssuedInvoiceArtifactMetadata:
        with self.transaction(workspace_id) as store:
            metadata = store.get_metadata(artifact_id)
            if metadata is None:
                raise IssuedInvoiceArtifactResourceNotFound(
                    "Issued invoice artifact resource not found"
                )
        return metadata

    def get_content(
        self, workspace_id: UUID, artifact_id: UUID
    ) -> IssuedInvoiceArtifact:
        with self.transaction(workspace_id) as store:
            artifact = store.get(artifact_id)
            if artifact is None:
                raise IssuedInvoiceArtifactResourceNotFound(
                    "Issued invoice artifact resource not found"
                )
        return artifact
