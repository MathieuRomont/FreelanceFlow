"""Immutable frozen invoice artifacts bound to exact draft revisions."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from re import fullmatch
from uuid import UUID


class InvoiceArtifactError(ValueError):
    """Base error for invalid frozen invoice artifacts."""


class InvalidInvoiceArtifactError(InvoiceArtifactError):
    """An artifact does not satisfy the frozen-content contract."""


@dataclass(frozen=True)
class InvoiceArtifactMetadata:
    """Immutable identity and integrity metadata, excluding the byte payload."""

    id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    media_type: str
    sha256: str
    byte_size: int
    created_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.workspace_id, self.invoice_id)
        ):
            raise InvalidInvoiceArtifactError("Artifact identity values must be UUIDs")
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise InvalidInvoiceArtifactError(
                "Artifact invoice revision must be a positive integer"
            )
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise InvalidInvoiceArtifactError("Artifact media type must be nonblank")
        if not isinstance(self.sha256, str) or fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise InvalidInvoiceArtifactError("Artifact SHA-256 must be lowercase hexadecimal")
        if type(self.byte_size) is not int or self.byte_size < 1:
            raise InvalidInvoiceArtifactError("Artifact payload must not be empty")
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise InvalidInvoiceArtifactError("Artifact creation time must be timezone-aware")


@dataclass(frozen=True)
class InvoiceArtifact:
    """Exact immutable bytes and their validated integrity metadata."""

    metadata: InvoiceArtifactMetadata
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, InvoiceArtifactMetadata):
            raise InvalidInvoiceArtifactError("Artifact metadata is invalid")
        if not isinstance(self.content, bytes):
            raise InvalidInvoiceArtifactError("Artifact content must be bytes")
        if len(self.content) != self.metadata.byte_size:
            raise InvalidInvoiceArtifactError("Artifact byte size is inconsistent")
        if sha256(self.content).hexdigest() != self.metadata.sha256:
            raise InvalidInvoiceArtifactError("Artifact SHA-256 is inconsistent")


def freeze_invoice_artifact(
    *,
    artifact_id: UUID,
    workspace_id: UUID,
    invoice_id: UUID,
    invoice_revision: int,
    media_type: str,
    content: bytes,
    created_at: datetime,
) -> InvoiceArtifact:
    """Freeze exact bytes while deriving all authoritative integrity metadata."""
    if not isinstance(content, bytes):
        raise InvalidInvoiceArtifactError("Artifact content must be bytes")
    metadata = InvoiceArtifactMetadata(
        id=artifact_id,
        workspace_id=workspace_id,
        invoice_id=invoice_id,
        invoice_revision=invoice_revision,
        media_type=media_type,
        sha256=sha256(content).hexdigest(),
        byte_size=len(content),
        created_at=created_at,
    )
    return InvoiceArtifact(metadata=metadata, content=content)
