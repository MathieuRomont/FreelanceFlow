"""Immutable approval of one exact issued-invoice artifact."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from re import fullmatch
from uuid import UUID

from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
)


class IssuedInvoiceApprovalError(ValueError):
    """Base error for invalid issued-invoice approvals."""


class InvalidIssuedInvoiceApprovalError(IssuedInvoiceApprovalError):
    """An approval does not identify one exact final artifact."""


@dataclass(frozen=True)
class IssuedInvoiceApproval:
    """Historical approval of exact immutable final representation bytes."""

    id: UUID
    workspace_id: UUID
    issued_invoice_id: UUID
    issued_invoice_artifact_id: UUID
    artifact_sha256: str
    representation: IssuedInvoiceRepresentation
    renderer_version: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.id,
                self.workspace_id,
                self.issued_invoice_id,
                self.issued_invoice_artifact_id,
            )
        ):
            raise InvalidIssuedInvoiceApprovalError("Issued approval identity values must be UUIDs")
        if fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None:
            raise InvalidIssuedInvoiceApprovalError(
                "Issued approval artifact SHA-256 must be lowercase hexadecimal"
            )
        if not isinstance(self.representation, IssuedInvoiceRepresentation):
            raise InvalidIssuedInvoiceApprovalError("Issued approval representation is invalid")
        if not isinstance(self.renderer_version, str) or not self.renderer_version.strip():
            raise InvalidIssuedInvoiceApprovalError(
                "Issued approval renderer version must be nonblank"
            )
        if not isinstance(self.approved_at, datetime) or self.approved_at.utcoffset() != timedelta(
            0
        ):
            raise InvalidIssuedInvoiceApprovalError("Issued approval time must be UTC")


def approve_issued_invoice_artifact(
    *,
    approval_id: UUID,
    artifact: IssuedInvoiceArtifactMetadata,
    approved_at: datetime,
) -> IssuedInvoiceApproval:
    """Derive an approval only from trusted final-artifact metadata."""
    if not isinstance(artifact, IssuedInvoiceArtifactMetadata):
        raise InvalidIssuedInvoiceApprovalError("Issued approval requires frozen artifact metadata")
    return IssuedInvoiceApproval(
        id=approval_id,
        workspace_id=artifact.workspace_id,
        issued_invoice_id=artifact.issued_invoice_id,
        issued_invoice_artifact_id=artifact.id,
        artifact_sha256=artifact.sha256,
        representation=artifact.representation,
        renderer_version=artifact.renderer_version,
        approved_at=approved_at,
    )
