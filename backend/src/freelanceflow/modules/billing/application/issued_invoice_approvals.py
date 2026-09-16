"""IssuedInvoiceApproval use cases with explicit transaction ownership."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from freelanceflow.modules.billing.domain.issued_invoice_approvals import (
    IssuedInvoiceApproval,
    approve_issued_invoice_artifact,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactMetadata,
)


class IssuedInvoiceApprovalResourceNotFound(LookupError):
    """A workspace-scoped issued invoice, artifact, or approval is unavailable."""


class IssuedInvoiceApprovalConflictError(ValueError):
    """The issued invoice is already approved against another final artifact."""


class IssuedInvoiceApprovalStore(Protocol):
    def lock_issued_invoice(self, issued_invoice_id: UUID) -> bool: ...
    def issued_invoice_exists(self, issued_invoice_id: UUID) -> bool: ...
    def get_artifact(
        self, issued_invoice_id: UUID, artifact_id: UUID
    ) -> IssuedInvoiceArtifactMetadata | None: ...
    def get(self, issued_invoice_id: UUID) -> IssuedInvoiceApproval | None: ...
    def add(self, value: IssuedInvoiceApproval) -> None: ...


class IssuedInvoiceApprovalTransaction(Protocol):
    def __call__(
        self, workspace_id: UUID
    ) -> AbstractContextManager[IssuedInvoiceApprovalStore]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IssuedInvoiceApprovalService:
    def __init__(
        self,
        transaction: IssuedInvoiceApprovalTransaction,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.transaction = transaction
        self.clock = clock

    def approve(
        self,
        *,
        workspace_id: UUID,
        issued_invoice_id: UUID,
        artifact_id: UUID,
    ) -> IssuedInvoiceApproval:
        with self.transaction(workspace_id) as store:
            if not store.lock_issued_invoice(issued_invoice_id):
                raise IssuedInvoiceApprovalResourceNotFound(
                    "Issued invoice approval resource not found"
                )
            artifact = store.get_artifact(issued_invoice_id, artifact_id)
            if artifact is None:
                raise IssuedInvoiceApprovalResourceNotFound(
                    "Issued invoice approval resource not found"
                )
            existing = store.get(issued_invoice_id)
            if existing is not None:
                if (
                    existing.issued_invoice_artifact_id == artifact.id
                    and existing.artifact_sha256 == artifact.sha256
                    and existing.representation == artifact.representation
                    and existing.renderer_version == artifact.renderer_version
                ):
                    return existing
                raise IssuedInvoiceApprovalConflictError(
                    "Issued invoice is already approved with a different artifact"
                )
            approved_at = self.clock()
            if approved_at.tzinfo is None or approved_at.utcoffset() != timedelta(0):
                raise ValueError("Issued approval clock must return a UTC timestamp")
            approval = approve_issued_invoice_artifact(
                approval_id=uuid4(), artifact=artifact, approved_at=approved_at
            )
            store.add(approval)
        return approval

    def get(self, workspace_id: UUID, issued_invoice_id: UUID) -> IssuedInvoiceApproval:
        with self.transaction(workspace_id) as store:
            if not store.issued_invoice_exists(issued_invoice_id):
                raise IssuedInvoiceApprovalResourceNotFound(
                    "Issued invoice approval resource not found"
                )
            approval = store.get(issued_invoice_id)
            if approval is None:
                raise IssuedInvoiceApprovalResourceNotFound(
                    "Issued invoice approval resource not found"
                )
        return approval
