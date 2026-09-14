"""Immutable approval of one exact invoice revision and frozen artifact."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from re import fullmatch
from uuid import UUID

from freelanceflow.modules.billing.domain.invoice_artifacts import InvoiceArtifactMetadata


class InvoiceApprovalError(ValueError):
    """Base error for invalid invoice approvals."""


class InvalidInvoiceApprovalError(InvoiceApprovalError):
    """An approval does not identify one valid immutable target."""


@dataclass(frozen=True)
class InvoiceApproval:
    """Historical approval bound to an exact revision, artifact, and digest."""

    id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    artifact_id: UUID
    artifact_sha256: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.id,
                self.workspace_id,
                self.invoice_id,
                self.artifact_id,
            )
        ):
            raise InvalidInvoiceApprovalError("Approval identity values must be UUIDs")
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise InvalidInvoiceApprovalError(
                "Approval invoice revision must be a positive integer"
            )
        if (
            not isinstance(self.artifact_sha256, str)
            or fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None
        ):
            raise InvalidInvoiceApprovalError(
                "Approval artifact SHA-256 must be lowercase hexadecimal"
            )
        if (
            not isinstance(self.approved_at, datetime)
            or self.approved_at.utcoffset() != timedelta(0)
        ):
            raise InvalidInvoiceApprovalError("Approval time must be UTC")


def approve_invoice_artifact(
    *,
    approval_id: UUID,
    artifact: InvoiceArtifactMetadata,
    approved_at: datetime,
) -> InvoiceApproval:
    """Create approval metadata solely from one trusted frozen artifact target."""
    if not isinstance(artifact, InvoiceArtifactMetadata):
        raise InvalidInvoiceApprovalError("Approval requires frozen artifact metadata")
    return InvoiceApproval(
        id=approval_id,
        workspace_id=artifact.workspace_id,
        invoice_id=artifact.invoice_id,
        invoice_revision=artifact.invoice_revision,
        artifact_id=artifact.id,
        artifact_sha256=artifact.sha256,
        approved_at=approved_at,
    )
