"""Immutable representations generated from legally issued invoice snapshots."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from re import fullmatch
from uuid import UUID


class IssuedInvoiceArtifactError(ValueError):
    """Base error for invalid issued-invoice artifacts."""


class InvalidIssuedInvoiceArtifactError(IssuedInvoiceArtifactError):
    """An artifact does not satisfy the immutable representation contract."""


class IssuedInvoiceRepresentation(StrEnum):
    """Stable representation identities; future formats receive new values."""

    PDF = "pdf"


@dataclass(frozen=True)
class IssuedInvoiceArtifactMetadata:
    """Immutable artifact identity and integrity metadata without its payload."""

    id: UUID
    workspace_id: UUID
    issued_invoice_id: UUID
    representation: IssuedInvoiceRepresentation
    renderer_version: str
    media_type: str
    sha256: str
    byte_size: int
    created_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.id, self.workspace_id, self.issued_invoice_id)
        ):
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact identity values must be UUIDs"
            )
        if not isinstance(self.representation, IssuedInvoiceRepresentation):
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact representation is invalid"
            )
        if not isinstance(self.renderer_version, str) or not self.renderer_version.strip():
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact renderer version must be nonblank"
            )
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact media type must be nonblank"
            )
        if fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact SHA-256 must be lowercase hexadecimal"
            )
        if type(self.byte_size) is not int or self.byte_size < 1:
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact payload must not be empty"
            )
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.utcoffset() != timedelta(0)
        ):
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact creation time must be UTC"
            )


@dataclass(frozen=True)
class IssuedInvoiceArtifact:
    """Exact immutable representation bytes with verified integrity metadata."""

    metadata: IssuedInvoiceArtifactMetadata
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, IssuedInvoiceArtifactMetadata):
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact metadata is invalid"
            )
        if not isinstance(self.content, bytes):
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact content must be bytes"
            )
        if len(self.content) != self.metadata.byte_size:
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact byte size is inconsistent"
            )
        if sha256(self.content).hexdigest() != self.metadata.sha256:
            raise InvalidIssuedInvoiceArtifactError(
                "Issued artifact SHA-256 is inconsistent"
            )


def freeze_issued_invoice_artifact(
    *,
    artifact_id: UUID,
    workspace_id: UUID,
    issued_invoice_id: UUID,
    representation: IssuedInvoiceRepresentation,
    renderer_version: str,
    media_type: str,
    content: bytes,
    created_at: datetime,
) -> IssuedInvoiceArtifact:
    """Freeze renderer output while deriving authoritative integrity metadata."""
    if not isinstance(content, bytes):
        raise InvalidIssuedInvoiceArtifactError(
            "Issued artifact content must be bytes"
        )
    metadata = IssuedInvoiceArtifactMetadata(
        id=artifact_id,
        workspace_id=workspace_id,
        issued_invoice_id=issued_invoice_id,
        representation=representation,
        renderer_version=renderer_version,
        media_type=media_type,
        sha256=sha256(content).hexdigest(),
        byte_size=len(content),
        created_at=created_at,
    )
    return IssuedInvoiceArtifact(metadata=metadata, content=content)
