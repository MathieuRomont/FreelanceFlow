from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.invoice_approval_transactions import (
    SqlAlchemyInvoiceApprovalTransaction,
)
from freelanceflow.modules.billing.adapters.models import InvoiceApprovalRow
from freelanceflow.modules.billing.application.invoice_approvals import (
    InvoiceApprovalConflictError,
    InvoiceApprovalService,
)
from freelanceflow.modules.billing.domain.invoice_approvals import approve_invoice_artifact


def _create_invoice(http: TestClient, workspace_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
    client = http.post(
        f"/workspaces/{workspace_id}/clients", json={"name": "Approval client"}
    ).json()
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
        json={"name": "Approval project"},
    ).json()
    rate = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client["id"],
            "project_id": None,
            "hourly_amount": "80",
            "currency": "EUR",
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    )
    assert rate.status_code == 201
    entry = http.post(
        f"/workspaces/{workspace_id}/time-entries",
        json={
            "start": "2026-01-01T09:00:00Z",
            "end": "2026-01-01T10:00:00Z",
            "billable": True,
            "client_id": client["id"],
            "project_id": project["id"],
            "task_id": None,
        },
    ).json()
    allocation = {
        "time_entry_id": entry["id"],
        "start": entry["start"],
        "end": entry["end"],
        "business_date": "2026-01-01",
    }
    response = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts",
        json={
            "client_id": client["id"],
            "lines": [{"allocations": [allocation]}],
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json()), allocation


def _create_artifact(
    http: TestClient,
    workspace_id: UUID,
    invoice: dict[str, Any],
    *,
    revision: int = 1,
    content: bytes = b"frozen invoice",
) -> dict[str, Any]:
    response = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions/{revision}/artifacts",
        content=content,
        headers={"content-type": "application/pdf"},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _approval_path(
    workspace_id: UUID,
    invoice: dict[str, Any],
    artifact: dict[str, Any],
    *,
    revision: int = 1,
) -> str:
    return (
        f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}"
        f"/revisions/{revision}/artifacts/{artifact['id']}/approval"
    )


def _approval_get_path(workspace_id: UUID, invoice: dict[str, Any], *, revision: int = 1) -> str:
    return (
        f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions/{revision}/approval"
    )


def test_approval_api_exact_binding_reconstruction_and_same_target_idempotency(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice, _ = _create_invoice(http, workspace_id)
        artifact = _create_artifact(http, workspace_id, invoice)
        path = _approval_path(workspace_id, invoice, artifact)

        injected = http.post(
            path,
            json={
                "id": str(uuid4()),
                "artifact_sha256": "0" * 64,
                "approved_at": "2026-01-01T00:00:00Z",
                "total_minor_units": "1",
            },
        )
        assert injected.status_code == 422

        response = http.post(path)
        assert response.status_code == 200
        approval = response.json()
        assert set(approval) == {
            "id",
            "workspace_id",
            "invoice_id",
            "invoice_revision",
            "artifact_id",
            "artifact_sha256",
            "approved_at",
        }
        UUID(approval["id"])
        assert approval["workspace_id"] == str(workspace_id)
        assert approval["invoice_id"] == invoice["id"]
        assert approval["invoice_revision"] == 1
        assert approval["artifact_id"] == artifact["id"]
        assert approval["artifact_sha256"] == artifact["sha256"]
        assert datetime.fromisoformat(approval["approved_at"]).utcoffset() is not None

        assert http.get(_approval_get_path(workspace_id, invoice)).json() == approval
        assert http.post(path).json() == approval

        mutation_responses = (
            http.put(_approval_get_path(workspace_id, invoice), json={}),
            http.patch(_approval_get_path(workspace_id, invoice), json={}),
            http.delete(_approval_get_path(workspace_id, invoice)),
        )
        assert all(response.status_code == 405 for response in mutation_responses)
        assert http.post(f"{_approval_get_path(workspace_id, invoice)}/revoke").status_code in {
            404,
            405,
        }
        assert http.get(_approval_get_path(workspace_id, invoice)).json() == approval


def test_approval_conflict_revision_history_and_workspace_isolation(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        invoice, allocation = _create_invoice(http, workspace_id)
        first_artifact = _create_artifact(http, workspace_id, invoice, content=b"first artifact")
        other_artifact = _create_artifact(http, workspace_id, invoice, content=b"other artifact")
        first_path = _approval_path(workspace_id, invoice, first_artifact)
        original = http.post(first_path).json()

        conflict = http.post(_approval_path(workspace_id, invoice, other_artifact))
        assert conflict.status_code == 409
        assert "different artifact" in conflict.json()["detail"]
        assert http.get(_approval_get_path(workspace_id, invoice)).json() == original

        revision_response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions",
            json={"lines": [{"allocations": [allocation]}]},
        )
        assert revision_response.status_code == 201
        revision_two = revision_response.json()
        second_artifact = _create_artifact(
            http, workspace_id, invoice, revision=2, content=b"revision two"
        )

        assert http.get(_approval_get_path(workspace_id, invoice, revision=2)).status_code == 404
        mismatch = http.post(
            _approval_path(
                workspace_id,
                invoice,
                second_artifact,
                revision=1,
            )
        )
        assert mismatch.status_code == 404
        assert mismatch.json() == {"detail": "Resource not found"}
        assert http.get(_approval_get_path(workspace_id, invoice)).json() == original
        assert revision_two["revision"] == 2

        missing_artifact = {"id": str(uuid4())}
        missing = http.post(_approval_path(workspace_id, invoice, missing_artifact))
        foreign = http.post(_approval_path(other_workspace_id, invoice, first_artifact))
        assert missing.status_code == foreign.status_code == 404
        assert missing.json() == foreign.json() == {"detail": "Resource not found"}
        absent_get = http.get(
            f"/workspaces/{workspace_id}/invoice-drafts/{uuid4()}/revisions/1/approval"
        )
        foreign_get = http.get(_approval_get_path(other_workspace_id, invoice))
        assert absent_get.status_code == foreign_get.status_code == 404
        assert absent_get.json() == foreign_get.json() == {"detail": "Resource not found"}


def test_concurrent_same_and_conflicting_approval_are_serialized(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        same_invoice, _ = _create_invoice(http, workspace_id)
        same_artifact = _create_artifact(http, workspace_id, same_invoice)
        conflict_invoice, _ = _create_invoice(http, workspace_id)
        conflict_artifacts = (
            _create_artifact(http, workspace_id, conflict_invoice, content=b"artifact one"),
            _create_artifact(http, workspace_id, conflict_invoice, content=b"artifact two"),
        )

    service = InvoiceApprovalService(SqlAlchemyInvoiceApprovalTransaction(database))
    same_barrier = Barrier(2)

    def approve_same() -> UUID:
        same_barrier.wait()
        return service.approve(
            workspace_id=workspace_id,
            invoice_id=UUID(same_invoice["id"]),
            revision=1,
            artifact_id=UUID(same_artifact["id"]),
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_ids = list(executor.map(lambda _: approve_same(), range(2)))
    assert same_ids[0] == same_ids[1]

    conflict_barrier = Barrier(2)

    def approve_conflicting(artifact_id: str) -> str:
        conflict_barrier.wait()
        try:
            service.approve(
                workspace_id=workspace_id,
                invoice_id=UUID(conflict_invoice["id"]),
                revision=1,
                artifact_id=UUID(artifact_id),
            )
        except InvoiceApprovalConflictError:
            return "conflict"
        return "approved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                approve_conflicting,
                [artifact["id"] for artifact in conflict_artifacts],
            )
        )
    assert sorted(outcomes) == ["approved", "conflict"]


def test_approval_transaction_rollback_and_digest_fk(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice, _ = _create_invoice(http, workspace_id)
        artifact = _create_artifact(http, workspace_id, invoice)

    transaction = SqlAlchemyInvoiceApprovalTransaction(database)
    with pytest.raises(RuntimeError, match="after approval flush"):
        with transaction(workspace_id) as approvals:
            assert approvals.lock_revision(UUID(invoice["id"]), 1)
            metadata = approvals.get_artifact_for_revision(
                UUID(invoice["id"]), 1, UUID(artifact["id"])
            )
            assert metadata is not None
            approval = approve_invoice_artifact(
                approval_id=uuid4(),
                artifact=metadata,
                approved_at=datetime(2026, 9, 14, tzinfo=UTC),
            )
            approvals.add(approval)
            raise RuntimeError("after approval flush")
    with transaction(workspace_id) as approvals:
        assert approvals.get(UUID(invoice["id"]), 1) is None

    with Session(database) as session:
        session.add(
            InvoiceApprovalRow(
                id=uuid4(),
                workspace_id=workspace_id,
                invoice_draft_id=UUID(invoice["id"]),
                invoice_revision=1,
                artifact_id=UUID(artifact["id"]),
                artifact_sha256=sha256(b"not the artifact").hexdigest(),
                approved_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    existing = InvoiceApprovalService(transaction).approve(
        workspace_id=workspace_id,
        invoice_id=UUID(invoice["id"]),
        revision=1,
        artifact_id=UUID(artifact["id"]),
    )
    with Session(database) as session:
        session.add(
            InvoiceApprovalRow(
                id=uuid4(),
                workspace_id=existing.workspace_id,
                invoice_draft_id=existing.invoice_id,
                invoice_revision=existing.invoice_revision,
                artifact_id=existing.artifact_id,
                artifact_sha256=existing.artifact_sha256,
                approved_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
