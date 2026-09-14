from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.delivery.adapters.invoice_delivery_transactions import (
    SqlAlchemyInvoiceDeliveryTransaction,
)
from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliveryService,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    InvalidInvoiceDeliveryTransitionError,
    InvoiceDeliveryState,
    claim_invoice_delivery,
)


def _create_invoice(http: TestClient, workspace_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
    client = http.post(
        f"/workspaces/{workspace_id}/clients", json={"name": "Delivery client"}
    ).json()
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
        json={"name": "Delivery project"},
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
        json={"client_id": client["id"], "lines": [{"allocations": [allocation]}]},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json()), allocation


def _create_artifact(
    http: TestClient,
    workspace_id: UUID,
    invoice: dict[str, Any],
    *,
    revision: int = 1,
    content: bytes = b"frozen delivery artifact",
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


def _delivery_path(
    workspace_id: UUID,
    invoice: dict[str, Any],
    artifact: dict[str, Any],
    *,
    revision: int = 1,
) -> str:
    return (
        f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}"
        f"/revisions/{revision}/artifacts/{artifact['id']}/delivery"
    )


def _prepare_approved_target(
    http: TestClient, workspace_id: UUID
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    invoice, allocation = _create_invoice(http, workspace_id)
    artifact = _create_artifact(http, workspace_id, invoice)
    approval_response = http.post(_approval_path(workspace_id, invoice, artifact))
    assert approval_response.status_code == 200
    return invoice, allocation, artifact, cast(dict[str, Any], approval_response.json())


def test_delivery_requires_exact_approval_and_duplicate_request_is_idempotent(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice, _ = _create_invoice(http, workspace_id)
        artifact = _create_artifact(http, workspace_id, invoice)
        path = _delivery_path(workspace_id, invoice, artifact)

        assert http.post(path).status_code == 404
        approval = http.post(_approval_path(workspace_id, invoice, artifact)).json()
        unapproved_artifact = _create_artifact(
            http, workspace_id, invoice, content=b"not the approved artifact"
        )
        assert (
            http.post(
                _delivery_path(workspace_id, invoice, unapproved_artifact)
            ).status_code
            == 404
        )

        injected = http.post(
            path,
            json={
                "id": str(uuid4()),
                "artifact_sha256": "0" * 64,
                "state": "sent",
                "sent_at": datetime.now(UTC).isoformat(),
            },
        )
        assert injected.status_code == 422

        first_response = http.post(path)
        assert first_response.status_code == 200
        first = first_response.json()
        second = http.post(path).json()

        assert second == first
        assert set(first) == {
            "id",
            "workspace_id",
            "approval_id",
            "invoice_id",
            "invoice_revision",
            "artifact_id",
            "artifact_sha256",
            "state",
            "requested_at",
            "active_attempt_id",
            "sent_at",
            "attempts",
        }
        assert first["approval_id"] == approval["id"]
        assert first["artifact_sha256"] == artifact["sha256"]
        assert first["state"] == "pending"
        assert first["attempts"] == []
        status = http.get(f"/workspaces/{workspace_id}/invoice-deliveries/{first['id']}")
        assert status.status_code == 200
        assert status.json() == first


def test_delivery_workspace_isolation_revision_binding_and_immutable_routes(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        invoice, allocation, artifact, _ = _prepare_approved_target(http, workspace_id)
        delivery = http.post(_delivery_path(workspace_id, invoice, artifact)).json()

        missing = http.get(f"/workspaces/{workspace_id}/invoice-deliveries/{uuid4()}")
        foreign = http.get(f"/workspaces/{other_workspace_id}/invoice-deliveries/{delivery['id']}")
        assert missing.status_code == foreign.status_code == 404
        assert missing.json() == foreign.json() == {"detail": "Resource not found"}
        assert http.post(_delivery_path(other_workspace_id, invoice, artifact)).status_code == 404

        revision_response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions",
            json={"lines": [{"allocations": [allocation]}]},
        )
        assert revision_response.status_code == 201
        revision_two_artifact = _create_artifact(
            http,
            workspace_id,
            invoice,
            revision=2,
            content=b"second revision artifact",
        )
        assert (
            http.post(
                _delivery_path(workspace_id, invoice, revision_two_artifact, revision=2)
            ).status_code
            == 404
        )
        assert (
            http.get(f"/workspaces/{workspace_id}/invoice-deliveries/{delivery['id']}").json()
            == delivery
        )

        status_path = f"/workspaces/{workspace_id}/invoice-deliveries/{delivery['id']}"
        assert http.put(status_path, json={}).status_code == 405
        assert http.patch(status_path, json={}).status_code == 405
        assert http.delete(status_path).status_code == 405
        assert http.post(f"{status_path}/claim").status_code in {404, 405}


def test_concurrent_duplicate_request_and_worker_claim_are_serialized(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice, _, artifact, _ = _prepare_approved_target(http, workspace_id)

    service = InvoiceDeliveryService(SqlAlchemyInvoiceDeliveryTransaction(database))
    request_barrier = Barrier(2)

    def request_delivery() -> UUID:
        request_barrier.wait()
        return service.request(
            workspace_id=workspace_id,
            invoice_id=UUID(invoice["id"]),
            revision=1,
            artifact_id=UUID(artifact["id"]),
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        requested_ids = list(executor.map(lambda _: request_delivery(), range(2)))
    assert requested_ids[0] == requested_ids[1]

    barrier = Barrier(2)

    def claim() -> UUID | None:
        barrier.wait()
        delivery = service.claim_next(workspace_id)
        return delivery.active_attempt_id if delivery is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))

    assert sum(result is not None for result in results) == 1
    persisted = service.get(workspace_id, requested_ids[0])
    assert persisted.state is InvoiceDeliveryState.IN_PROGRESS
    assert persisted.active_attempt_id in results
    assert len(persisted.attempts) == 1


def test_claim_rollback_failure_retry_stale_token_and_terminal_sent(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice, _, artifact, _ = _prepare_approved_target(http, workspace_id)
        requested = http.post(_delivery_path(workspace_id, invoice, artifact)).json()

    delivery_id = UUID(requested["id"])
    transaction = SqlAlchemyInvoiceDeliveryTransaction(database)
    with pytest.raises(RuntimeError, match="after claim flush"):
        with transaction(workspace_id) as deliveries:
            pending = deliveries.lock_next_pending()
            assert pending is not None
            claimed = claim_invoice_delivery(
                pending,
                attempt_id=uuid4(),
                started_at=datetime.now(UTC),
            )
            deliveries.save_claim(claimed)
            raise RuntimeError("after claim flush")

    service = InvoiceDeliveryService(transaction)
    rolled_back = service.get(workspace_id, delivery_id)
    assert rolled_back.state is InvoiceDeliveryState.PENDING
    assert rolled_back.attempts == ()

    first_claim = service.claim_next(workspace_id)
    assert first_claim is not None
    assert first_claim.active_attempt_id is not None
    first_token = first_claim.active_attempt_id
    failed = service.record_failure(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=first_token,
        failure_reason="definitive rejection",
    )
    assert failed.state is InvoiceDeliveryState.PENDING
    assert failed.attempts[0].failure_reason == "definitive rejection"

    second_claim = service.claim_next(workspace_id)
    assert second_claim is not None
    assert second_claim.active_attempt_id is not None
    second_token = second_claim.active_attempt_id
    assert second_token != first_token
    assert tuple(attempt.sequence for attempt in second_claim.attempts) == (1, 2)

    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="stale"):
        service.record_sent(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=first_token,
            provider_message_id="provider-message-stale",
        )

    sent = service.record_sent(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=second_token,
        provider_message_id="provider-message-accepted",
    )
    assert sent.state is InvoiceDeliveryState.SENT
    assert sent.sent_at is not None
    assert sent.attempts[0] == failed.attempts[0]
    assert sent.attempts[1].outcome == "sent"
    assert sent.attempts[1].provider_message_id == "provider-message-accepted"
    assert service.claim_next(workspace_id) is None
    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="stale"):
        service.record_failure(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=second_token,
            failure_reason="cannot reopen sent",
        )
