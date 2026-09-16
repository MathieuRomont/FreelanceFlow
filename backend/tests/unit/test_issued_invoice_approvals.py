from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from freelanceflow.modules.billing.domain.issued_invoice_approvals import (
    InvalidIssuedInvoiceApprovalError,
    IssuedInvoiceApproval,
    approve_issued_invoice_artifact,
)
from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
    IssuedInvoiceArtifactMetadata,
    IssuedInvoiceRepresentation,
)


def _artifact() -> IssuedInvoiceArtifactMetadata:
    return IssuedInvoiceArtifactMetadata(
        id=uuid4(),
        workspace_id=uuid4(),
        issued_invoice_id=uuid4(),
        representation=IssuedInvoiceRepresentation.PDF,
        renderer_version="issued-invoice-pdf/v1",
        media_type="application/pdf",
        sha256="a" * 64,
        byte_size=100,
        created_at=datetime(2026, 9, 16, 10, tzinfo=UTC),
    )


def test_issued_approval_derives_complete_final_artifact_target() -> None:
    artifact = _artifact()
    approval_id = uuid4()
    approved_at = datetime(2026, 9, 16, 11, tzinfo=UTC)

    approval = approve_issued_invoice_artifact(
        approval_id=approval_id,
        artifact=artifact,
        approved_at=approved_at,
    )

    assert approval == IssuedInvoiceApproval(
        id=approval_id,
        workspace_id=artifact.workspace_id,
        issued_invoice_id=artifact.issued_invoice_id,
        issued_invoice_artifact_id=artifact.id,
        artifact_sha256=artifact.sha256,
        representation=artifact.representation,
        renderer_version=artifact.renderer_version,
        approved_at=approved_at,
    )
    assert not hasattr(approval, "approved_by")


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_sha256": "A" * 64},
        {"artifact_sha256": "a" * 63},
        {"representation": "pdf"},
        {"renderer_version": " \t"},
        {"approved_at": datetime(2026, 9, 16, 11)},
        {"approved_at": datetime(2026, 9, 16, 11, tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_issued_approval_rejects_invalid_identity_or_time(
    change: dict[str, object],
) -> None:
    valid = approve_issued_invoice_artifact(
        approval_id=uuid4(),
        artifact=_artifact(),
        approved_at=datetime.now(UTC),
    )
    with pytest.raises(InvalidIssuedInvoiceApprovalError):
        replace(valid, **change)  # type: ignore[arg-type]
