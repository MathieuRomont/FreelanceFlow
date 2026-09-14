from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest

from freelanceflow.modules.billing.domain.invoice_artifacts import (
    InvalidInvoiceArtifactError,
    InvoiceArtifact,
    InvoiceArtifactMetadata,
    freeze_invoice_artifact,
)


def _artifact(content: bytes = b"frozen\x00invoice\xff") -> InvoiceArtifact:
    return freeze_invoice_artifact(
        artifact_id=uuid4(),
        workspace_id=uuid4(),
        invoice_id=uuid4(),
        invoice_revision=2,
        media_type="application/pdf",
        content=content,
        created_at=datetime(2026, 9, 14, 12, 30, tzinfo=UTC),
    )


def test_freezing_derives_canonical_digest_and_exact_size() -> None:
    content = b"\x00\xffnot-text\x80"
    artifact = _artifact(content)

    assert artifact.content == content
    assert artifact.metadata.byte_size == len(content)
    assert artifact.metadata.sha256 == sha256(content).hexdigest()
    assert artifact.metadata.sha256 == artifact.metadata.sha256.lower()
    assert len(artifact.metadata.sha256) == 64


def test_one_byte_mutation_changes_digest() -> None:
    assert _artifact(b"payload-a").metadata.sha256 != _artifact(b"payload-b").metadata.sha256


@pytest.mark.parametrize("media_type", ["", " ", "\t\n", "\u2003"])
def test_media_type_must_be_nonblank(media_type: str) -> None:
    with pytest.raises(InvalidInvoiceArtifactError, match="media type"):
        freeze_invoice_artifact(
            artifact_id=uuid4(),
            workspace_id=uuid4(),
            invoice_id=uuid4(),
            invoice_revision=1,
            media_type=media_type,
            content=b"payload",
            created_at=datetime.now(UTC),
        )


def test_empty_payload_is_rejected() -> None:
    with pytest.raises(InvalidInvoiceArtifactError, match="must not be empty"):
        _artifact(b"")


@pytest.mark.parametrize(
    "change,match",
    [
        ({"byte_size": 1}, "byte size"),
        ({"sha256": "0" * 64}, "SHA-256"),
    ],
)
def test_artifact_rejects_inconsistent_persisted_integrity_metadata(
    change: dict[str, object], match: str
) -> None:
    artifact = _artifact()
    metadata = replace(artifact.metadata, **cast(Any, change))
    with pytest.raises(InvalidInvoiceArtifactError, match=match):
        InvoiceArtifact(metadata=metadata, content=artifact.content)


@pytest.mark.parametrize(
    "metadata",
    [
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"invoice_revision": 0},
        {"byte_size": 0},
        {"created_at": datetime(2026, 1, 1)},
    ],
)
def test_metadata_rejects_noncanonical_or_invalid_values(
    metadata: dict[str, object],
) -> None:
    valid: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "invoice_id": uuid4(),
        "invoice_revision": 1,
        "media_type": "application/pdf",
        "sha256": "a" * 64,
        "byte_size": 1,
        "created_at": datetime.now(UTC),
    }
    with pytest.raises(InvalidInvoiceArtifactError):
        InvoiceArtifactMetadata(**(valid | metadata))  # type: ignore[arg-type]
