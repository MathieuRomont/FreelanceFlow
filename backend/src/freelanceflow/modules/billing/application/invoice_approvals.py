"""InvoiceApproval use cases with explicit transactions and no HTTP dependencies."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.invoice_approvals import (
    InvoiceApproval,
    approve_invoice_artifact,
)
from freelanceflow.modules.billing.domain.invoice_artifacts import InvoiceArtifactMetadata


class InvoiceApprovalResourceNotFound(LookupError):
    """A workspace-scoped revision, artifact, or approval is unavailable."""


class InvoiceApprovalConflictError(ValueError):
    """A revision is already approved against a different immutable artifact."""


class InvoiceApprovalStore(Protocol):
    def lock_revision(self, invoice_id: UUID, revision: int) -> bool: ...
    def revision_exists(self, invoice_id: UUID, revision: int) -> bool: ...
    def get_artifact_for_revision(
        self, invoice_id: UUID, revision: int, artifact_id: UUID
    ) -> InvoiceArtifactMetadata | None: ...
    def get(self, invoice_id: UUID, revision: int) -> InvoiceApproval | None: ...
    def add(self, value: InvoiceApproval) -> None: ...


class InvoiceApprovalTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[InvoiceApprovalStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvoiceApprovalService:
    def __init__(
        self,
        transaction: InvoiceApprovalTransaction,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def approve(
        self,
        *,
        workspace_id: UUID,
        invoice_id: UUID,
        revision: int,
        artifact_id: UUID,
    ) -> InvoiceApproval:
        with self.transaction(workspace_id) as store:
            if not store.lock_revision(invoice_id, revision):
                raise InvoiceApprovalResourceNotFound("Invoice approval resource not found")
            artifact = store.get_artifact_for_revision(invoice_id, revision, artifact_id)
            if artifact is None:
                raise InvoiceApprovalResourceNotFound("Invoice approval resource not found")
            existing = store.get(invoice_id, revision)
            if existing is not None:
                if (
                    existing.artifact_id == artifact.id
                    and existing.artifact_sha256 == artifact.sha256
                ):
                    return existing
                raise InvoiceApprovalConflictError(
                    "Invoice revision is already approved with a different artifact"
                )
            approval = approve_invoice_artifact(
                approval_id=uuid4(), artifact=artifact, approved_at=self.clock()
            )
            store.add(approval)
        return approval

    def get(self, workspace_id: UUID, invoice_id: UUID, revision: int) -> InvoiceApproval:
        with self.transaction(workspace_id) as store:
            if not store.revision_exists(invoice_id, revision):
                raise InvoiceApprovalResourceNotFound("Invoice approval resource not found")
            approval = store.get(invoice_id, revision)
            if approval is None:
                raise InvoiceApprovalResourceNotFound("Invoice approval resource not found")
        return approval
