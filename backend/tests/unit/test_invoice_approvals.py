from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from freelanceflow.modules.billing.domain.invoice_approvals import (
    InvalidInvoiceApprovalError,
    InvoiceApproval,
    approve_invoice_artifact,
)
from freelanceflow.modules.billing.domain.invoice_artifacts import InvoiceArtifactMetadata


def _artifact() -> InvoiceArtifactMetadata:
    return InvoiceArtifactMetadata(
        id=uuid4(),
        workspace_id=uuid4(),
        invoice_id=uuid4(),
        invoice_revision=3,
        media_type="application/pdf",
        sha256="a" * 64,
        byte_size=100,
        created_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
    )


def test_approval_derives_exact_artifact_target_without_actor() -> None:
    artifact = _artifact()
    approval_id = uuid4()
    approved_at = datetime(2026, 9, 14, 11, tzinfo=UTC)

    approval = approve_invoice_artifact(
        approval_id=approval_id,
        artifact=artifact,
        approved_at=approved_at,
    )

    assert approval == InvoiceApproval(
        id=approval_id,
        workspace_id=artifact.workspace_id,
        invoice_id=artifact.invoice_id,
        invoice_revision=artifact.invoice_revision,
        artifact_id=artifact.id,
        artifact_sha256=artifact.sha256,
        approved_at=approved_at,
    )
    assert not hasattr(approval, "approved_by")


@pytest.mark.parametrize(
    "approval",
    [
        {"invoice_revision": 0},
        {"artifact_sha256": "A" * 64},
        {"artifact_sha256": "a" * 63},
        {"approved_at": datetime(2026, 9, 14, 11)},
        {"approved_at": datetime(2026, 9, 14, 11, tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_approval_rejects_invalid_identity_or_time(
    approval: dict[str, object],
) -> None:
    valid = approve_invoice_artifact(
        approval_id=uuid4(),
        artifact=_artifact(),
        approved_at=datetime.now(UTC),
    )
    with pytest.raises(InvalidInvoiceApprovalError):
        replace(valid, **approval)  # type: ignore[arg-type]
