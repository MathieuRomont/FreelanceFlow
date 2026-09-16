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
from freelanceflow.modules.billing.adapters.issued_invoice_approval_models import (
    IssuedInvoiceApprovalRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_approval_transactions import (
    SqlAlchemyIssuedInvoiceApprovalTransaction,
)
from freelanceflow.modules.billing.adapters.issued_invoice_artifact_models import (
    IssuedInvoiceArtifactRow,
)
from freelanceflow.modules.billing.application.issued_invoice_approvals import (
    IssuedInvoiceApprovalConflictError,
    IssuedInvoiceApprovalService,
)
from freelanceflow.modules.billing.domain.issued_invoice_approvals import (
    approve_issued_invoice_artifact,
)

from .test_issued_invoice_artifacts_api import (
    ARTIFACT_CREATED_AT,
    _collection,
    _issue,
)
from .test_issued_invoices_api import (
    _configure_workspace,
    _create_ready_draft,
    _issue_payload,
)

APPROVED_AT = datetime(2026, 9, 16, 12, 0, 0, 987654, tzinfo=UTC)


def _approval_path(
    workspace_id: UUID, issued_invoice_id: str | UUID, artifact_id: str | UUID
) -> str:
    return (
        f"/workspaces/{workspace_id}/issued-invoices/{issued_invoice_id}"
        f"/artifacts/{artifact_id}/approval"
    )


def _approval_get_path(workspace_id: UUID, issued_invoice_id: str | UUID) -> str:
    return f"/workspaces/{workspace_id}/issued-invoices/{issued_invoice_id}/approval"


def _second_artifact(
    database: Engine,
    *,
    workspace_id: UUID,
    issued_invoice_id: UUID,
    renderer_version: str = "issued-invoice-pdf/v2",
) -> UUID:
    artifact_id = uuid4()
    content = b"future immutable renderer output"
    with Session(database) as session, session.begin():
        session.add(
            IssuedInvoiceArtifactRow(
                id=artifact_id,
                workspace_id=workspace_id,
                issued_invoice_id=issued_invoice_id,
                representation="pdf",
                renderer_version=renderer_version,
                media_type="application/pdf",
                sha256=sha256(content).hexdigest(),
                byte_size=len(content),
                content=content,
                created_at=ARTIFACT_CREATED_AT,
            )
        )
    return artifact_id


def _issue_additional(
    http: TestClient, workspace_id: UUID, *, start_hour: int
) -> dict[str, Any]:
    _client, draft, _allocation = _create_ready_draft(
        http,
        workspace_id,
        client_name=f"Additional client {start_hour}",
        start_hour=start_hour,
    )
    response = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue",
        json=_issue_payload(draft),
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_issued_approval_exact_binding_reconstruction_and_immutability(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: APPROVED_AT)) as http:
        _client, issued = _issue(http, workspace_id)
        artifact = http.post(_collection(workspace_id, issued["id"])).json()
        path = _approval_path(workspace_id, issued["id"], artifact["id"])

        injected = http.post(path, json={"sha256": "0" * 64, "approved_at": "now"})
        assert injected.status_code == 422
        response = http.post(path)
        assert response.status_code == 200
        approval = cast(dict[str, Any], response.json())
        assert approval == {
            "id": approval["id"],
            "workspace_id": str(workspace_id),
            "issued_invoice_id": issued["id"],
            "issued_invoice_artifact_id": artifact["id"],
            "artifact_sha256": artifact["sha256"],
            "representation": artifact["representation"],
            "renderer_version": artifact["renderer_version"],
            "approved_at": "2026-09-16T12:00:00.987654Z",
        }
        UUID(cast(str, approval["id"]))
        assert http.post(path).json() == approval
        assert http.get(_approval_get_path(workspace_id, issued["id"])).json() == approval

        for mutation in (
            http.put(_approval_get_path(workspace_id, issued["id"]), json={}),
            http.patch(_approval_get_path(workspace_id, issued["id"]), json={}),
            http.delete(_approval_get_path(workspace_id, issued["id"])),
        ):
            assert mutation.status_code == 405


def test_draft_approval_is_not_inherited_by_issued_invoice(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: APPROVED_AT)) as http:
        _configure_workspace(http, workspace_id)
        _client, draft, _allocation = _create_ready_draft(
            http,
            workspace_id,
            client_name="Legacy approval client",
            start_hour=9,
        )
        draft_artifact = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}"
            "/revisions/1/artifacts",
            content=b"legacy draft artifact",
            headers={"content-type": "application/pdf"},
        ).json()
        draft_approval = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}"
            f"/revisions/1/artifacts/{draft_artifact['id']}/approval"
        )
        assert draft_approval.status_code == 200

        issued_response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue",
            json=_issue_payload(draft),
        )
        assert issued_response.status_code == 201
        issued = issued_response.json()
        assert http.get(_approval_get_path(workspace_id, issued["id"])).status_code == 404

        issued_artifact = http.post(
            _collection(workspace_id, issued["id"])
        ).json()
        final_approval = http.post(
            _approval_path(workspace_id, issued["id"], issued_artifact["id"])
        )
        assert final_approval.status_code == 200
        assert final_approval.json()["id"] != draft_approval.json()["id"]


def test_issued_approval_conflict_history_workspace_and_invoice_boundaries(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: APPROVED_AT)) as http:
        _client, issued = _issue(http, workspace_id)
        first = http.post(_collection(workspace_id, issued["id"])).json()
        other_issued = _issue_additional(http, workspace_id, start_hour=10)
        other_artifact = http.post(_collection(workspace_id, other_issued["id"])).json()
        approval = http.post(_approval_path(workspace_id, issued["id"], first["id"])).json()

        mismatch = http.post(_approval_path(workspace_id, issued["id"], other_artifact["id"]))
        missing = http.post(_approval_path(workspace_id, issued["id"], uuid4()))
        foreign = http.post(_approval_path(other_workspace_id, issued["id"], first["id"]))
        assert mismatch.status_code == missing.status_code == foreign.status_code == 404
        assert (
            mismatch.json() == missing.json() == foreign.json() == {"detail": "Resource not found"}
        )
        assert http.get(_approval_get_path(other_workspace_id, issued["id"])).status_code == 404

        second_id = _second_artifact(
            database,
            workspace_id=workspace_id,
            issued_invoice_id=UUID(cast(str, issued["id"])),
        )
        conflict = http.post(_approval_path(workspace_id, issued["id"], second_id))
        assert conflict.status_code == 409
        assert http.get(_approval_get_path(workspace_id, issued["id"])).json() == approval


def test_concurrent_same_and_conflicting_issued_approvals_are_serialized(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: APPROVED_AT)) as http:
        _client, same_issued = _issue(http, workspace_id)
        same_artifact = http.post(_collection(workspace_id, same_issued["id"])).json()
        conflict_issued = _issue_additional(http, workspace_id, start_hour=10)
        first = http.post(_collection(workspace_id, conflict_issued["id"])).json()
    second_id = _second_artifact(
        database,
        workspace_id=workspace_id,
        issued_invoice_id=UUID(cast(str, conflict_issued["id"])),
    )
    service = IssuedInvoiceApprovalService(
        SqlAlchemyIssuedInvoiceApprovalTransaction(database),
        clock=lambda: APPROVED_AT,
    )
    same_barrier = Barrier(2)

    def approve_same() -> UUID:
        same_barrier.wait()
        return service.approve(
            workspace_id=workspace_id,
            issued_invoice_id=UUID(cast(str, same_issued["id"])),
            artifact_id=UUID(cast(str, same_artifact["id"])),
        ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        same_ids = tuple(pool.map(lambda _value: approve_same(), range(2)))
    assert same_ids[0] == same_ids[1]

    conflict_barrier = Barrier(2)

    def approve_conflicting(artifact_id: UUID) -> str:
        conflict_barrier.wait()
        try:
            service.approve(
                workspace_id=workspace_id,
                issued_invoice_id=UUID(cast(str, conflict_issued["id"])),
                artifact_id=artifact_id,
            )
        except IssuedInvoiceApprovalConflictError:
            return "conflict"
        return "approved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(
            pool.map(
                approve_conflicting,
                (UUID(cast(str, first["id"])), second_id),
            )
        )
    assert sorted(outcomes) == ["approved", "conflict"]


def test_issued_approval_rollback_and_full_artifact_fk(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: APPROVED_AT)) as http:
        _client, issued = _issue(http, workspace_id)
        artifact = http.post(_collection(workspace_id, issued["id"])).json()
    issued_invoice_id = UUID(cast(str, issued["id"]))
    artifact_id = UUID(cast(str, artifact["id"]))
    transaction = SqlAlchemyIssuedInvoiceApprovalTransaction(database)

    with pytest.raises(RuntimeError, match="after approval flush"):
        with transaction(workspace_id) as store:
            assert store.lock_issued_invoice(issued_invoice_id)
            metadata = store.get_artifact(issued_invoice_id, artifact_id)
            assert metadata is not None
            store.add(
                approve_issued_invoice_artifact(
                    approval_id=uuid4(),
                    artifact=metadata,
                    approved_at=APPROVED_AT,
                )
            )
            raise RuntimeError("after approval flush")
    with transaction(workspace_id) as store:
        assert store.get(issued_invoice_id) is None

    invalid_targets = (
        (sha256(b"wrong bytes").hexdigest(), cast(str, artifact["renderer_version"])),
        (cast(str, artifact["sha256"]), "wrong-renderer"),
    )
    for artifact_sha256, renderer_version in invalid_targets:
        with Session(database) as session:
            session.add(
                IssuedInvoiceApprovalRow(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    issued_invoice_id=issued_invoice_id,
                    issued_invoice_artifact_id=artifact_id,
                    artifact_sha256=artifact_sha256,
                    representation="pdf",
                    renderer_version=renderer_version,
                    approved_at=APPROVED_AT,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
