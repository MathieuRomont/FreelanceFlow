import json
from base64 import b64encode
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from svix.webhooks import Webhook

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.delivery.adapters.invoice_delivery_transactions import (
    SqlAlchemyInvoiceDeliveryTransaction,
)
from freelanceflow.modules.delivery.adapters.models import (
    InvoiceDeliveryProviderEventMatchRow,
    InvoiceDeliveryProviderEventRow,
)
from freelanceflow.modules.delivery.adapters.provider_event_transactions import (
    SqlAlchemyInvoiceDeliveryProviderEventTransaction,
)
from freelanceflow.modules.delivery.adapters.resend_webhooks import (
    ResendWebhookVerifier,
)
from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliveryService,
)
from freelanceflow.modules.delivery.application.provider_events import (
    InvoiceDeliveryProviderEventService,
    InvoiceDeliveryProviderEventStore,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    InvoiceDeliveryState,
)
from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEventKind,
)

from .test_invoice_deliveries_api import (
    _approval_path,
    _create_artifact,
    _create_invoice,
    _delivery_path,
)

WEBHOOK_SECRET = "whsec_" + b64encode(b"integration-resend-webhook-secret").decode()
WEBHOOK_PATH = "/webhooks/resend"


def _payload(
    event_type: str,
    provider_message_id: str | None,
    *,
    occurred_at: str = "2026-09-15T10:11:12.123456Z",
) -> bytes:
    data: dict[str, object] = {
        "from": "Freelancer <invoices@example.com>",
        "to": ["client@example.net"],
        "subject": "Invoice",
    }
    if provider_message_id is not None:
        data["email_id"] = provider_message_id
    return json.dumps(
        {"type": event_type, "created_at": occurred_at, "data": data},
        separators=(",", ":"),
    ).encode()


def _headers(raw_body: bytes, event_id: str) -> dict[str, str]:
    timestamp = datetime.now(UTC)
    signature = Webhook(WEBHOOK_SECRET).sign(
        event_id, timestamp, raw_body.decode("utf-8")
    )
    return {
        "content-type": "application/json",
        "svix-id": event_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
    }


def _request_delivery(
    database: Engine, workspace_id: UUID
) -> tuple[UUID, InvoiceDeliveryService]:
    with TestClient(create_app(database)) as http:
        invoice, _ = _create_invoice(http, workspace_id)
        artifact = _create_artifact(http, workspace_id, invoice)
        assert http.post(_approval_path(workspace_id, invoice, artifact)).status_code == 200
        response = http.post(_delivery_path(workspace_id, invoice, artifact))
        assert response.status_code == 200
    return (
        UUID(cast(dict[str, Any], response.json())["id"]),
        InvoiceDeliveryService(SqlAlchemyInvoiceDeliveryTransaction(database)),
    )


def _claim_delivery(
    database: Engine, workspace_id: UUID
) -> tuple[UUID, UUID, InvoiceDeliveryService]:
    delivery_id, service = _request_delivery(database, workspace_id)
    claimed = service.claim_next(workspace_id)
    assert claimed is not None and claimed.active_attempt_id is not None
    return delivery_id, claimed.active_attempt_id, service


def _sent_delivery(
    database: Engine, workspace_id: UUID, provider_message_id: str
) -> tuple[UUID, InvoiceDeliveryService]:
    delivery_id, attempt_id, service = _claim_delivery(database, workspace_id)
    sent = service.record_sent(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=attempt_id,
        provider_message_id=provider_message_id,
    )
    assert sent.state is InvoiceDeliveryState.SENT
    return delivery_id, service


def _event_count(database: Engine) -> int:
    with Session(database) as session:
        return session.scalar(
            select(func.count()).select_from(InvoiceDeliveryProviderEventRow)
        ) or 0


def _event_by_provider_id(
    database: Engine, provider_event_id: str
) -> InvoiceDeliveryProviderEventRow | None:
    with Session(database) as session:
        return session.scalar(
            select(InvoiceDeliveryProviderEventRow).where(
                InvoiceDeliveryProviderEventRow.provider_event_id
                == provider_event_id
            )
        )


def test_invalid_signatures_and_malformed_headers_create_no_records(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    initial_count = _event_count(database)
    raw_body = _payload("email.delivered", "resend-invalid")
    with TestClient(create_app(database)) as http:
        missing = http.post(WEBHOOK_PATH, content=raw_body)
        invalid = http.post(
            WEBHOOK_PATH,
            content=raw_body,
            headers={
                "svix-id": "msg_invalid",
                "svix-timestamp": "not-a-timestamp",
                "svix-signature": "malformed",
            },
        )

    assert missing.status_code == invalid.status_code == 400
    assert missing.json() == invalid.json() == {"detail": "Invalid webhook"}
    assert _event_count(database) == initial_count


def test_raw_body_verification_and_malformed_json_order(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    initial_count = _event_count(database)
    original = _payload("email.delivered", "resend-raw")
    reformatted = json.dumps(json.loads(original), indent=2).encode()
    malformed = b"not json"
    with TestClient(create_app(database)) as http:
        changed_body = http.post(
            WEBHOOK_PATH,
            content=reformatted,
            headers=_headers(original, "msg_exact_raw"),
        )
        invalid_before_parse = http.post(
            WEBHOOK_PATH,
            content=malformed,
            headers={
                "svix-id": "msg_bad_json_invalid_signature",
                "svix-timestamp": str(int(datetime.now(UTC).timestamp())),
                "svix-signature": "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            },
        )
        valid_then_malformed = http.post(
            WEBHOOK_PATH,
            content=malformed,
            headers=_headers(malformed, "msg_bad_json_valid_signature"),
        )

    assert changed_body.status_code == 400
    assert invalid_before_parse.status_code == 400
    assert valid_then_malformed.status_code == 400
    assert _event_count(database) == initial_count


@pytest.mark.parametrize(
    "event_type,kind",
    [
        ("email.sent", "provider_accepted"),
        ("email.delivered", "recipient_delivered"),
        ("email.delivery_delayed", "delivery_delayed"),
        ("email.bounced", "bounced"),
        ("email.failed", "provider_failed"),
        ("email.complained", "complained"),
    ],
)
def test_supported_event_is_correlated_without_rewriting_acceptance(
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    kind: str,
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    workspace_id = uuid4()
    provider_message_id = f"resend-{kind}-{uuid4()}"
    delivery_id, delivery_service = _sent_delivery(
        database, workspace_id, provider_message_id
    )
    raw_body = _payload(event_type, provider_message_id)
    event_id = f"msg_{kind}_{uuid4()}"

    with TestClient(create_app(database)) as http:
        response = http.post(
            WEBHOOK_PATH, content=raw_body, headers=_headers(raw_body, event_id)
        )
        history = http.get(
            f"/workspaces/{workspace_id}/invoice-deliveries/{delivery_id}/provider-events"
        )

    assert response.status_code == 200
    assert history.status_code == 200
    assert history.json()[0]["provider_event_id"] == event_id
    assert history.json()[0]["provider_message_id"] == provider_message_id
    assert history.json()[0]["raw_event_type"] == event_type
    assert history.json()[0]["kind"] == kind
    persisted = delivery_service.get(workspace_id, delivery_id)
    assert persisted.state is InvoiceDeliveryState.SENT
    assert persisted.attempts[-1].provider_message_id == provider_message_id


def test_duplicate_retry_is_idempotent_and_identity_reuse_conflicts(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    provider_message_id = f"resend-duplicate-{uuid4()}"
    raw_body = _payload("email.delivered", provider_message_id)
    event_id = f"msg_duplicate_{uuid4()}"
    initial_count = _event_count(database)
    with TestClient(create_app(database)) as http:
        first = http.post(
            WEBHOOK_PATH, content=raw_body, headers=_headers(raw_body, event_id)
        )
        replay = http.post(
            WEBHOOK_PATH, content=raw_body, headers=_headers(raw_body, event_id)
        )
        changed = _payload("email.bounced", provider_message_id)
        conflict = http.post(
            WEBHOOK_PATH, content=changed, headers=_headers(changed, event_id)
        )

    assert first.status_code == replay.status_code == 200
    assert conflict.status_code == 409
    assert _event_count(database) == initial_count + 1
    stored = _event_by_provider_id(database, event_id)
    assert stored is not None
    assert stored.raw_event_type == "email.delivered"


def test_concurrent_duplicate_webhook_creates_one_event(
    database: Engine,
) -> None:
    raw_body = _payload("email.delivered", f"resend-concurrent-{uuid4()}")
    event_id = f"msg_concurrent_{uuid4()}"
    headers = _headers(raw_body, event_id)
    verified = ResendWebhookVerifier(WEBHOOK_SECRET).verify(
        raw_body,
        event_id=event_id,
        timestamp=headers["svix-timestamp"],
        signature=headers["svix-signature"],
    )
    service = InvoiceDeliveryProviderEventService(
        SqlAlchemyInvoiceDeliveryProviderEventTransaction(database)
    )
    initial_count = _event_count(database)
    barrier = Barrier(2)

    def ingest() -> UUID:
        barrier.wait()
        return service.ingest(verified).event.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = tuple(executor.map(lambda _: ingest(), range(2)))

    assert ids[0] == ids[1]
    assert _event_count(database) == initial_count + 1


def test_unmatched_event_is_preserved_and_acceptance_reconciles_it(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    workspace_id = uuid4()
    provider_message_id = f"resend-late-acceptance-{uuid4()}"
    delivery_id, attempt_id, delivery_service = _claim_delivery(
        database, workspace_id
    )
    raw_body = _payload("email.delivered", provider_message_id)
    event_id = f"msg_before_acceptance_{uuid4()}"

    with TestClient(create_app(database)) as http:
        response = http.post(
            WEBHOOK_PATH, content=raw_body, headers=_headers(raw_body, event_id)
        )
    assert response.status_code == 200
    with Session(database) as session:
        event = session.scalar(
            select(InvoiceDeliveryProviderEventRow).where(
                InvoiceDeliveryProviderEventRow.provider_event_id == event_id
            )
        )
        assert event is not None
        assert (
            session.get(InvoiceDeliveryProviderEventMatchRow, event.id) is None
        )

    delivery_service.record_sent(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=attempt_id,
        provider_message_id=provider_message_id,
    )

    event_service = InvoiceDeliveryProviderEventService(
        SqlAlchemyInvoiceDeliveryProviderEventTransaction(database)
    )
    history = event_service.list_for_delivery(
        workspace_id=workspace_id, delivery_id=delivery_id
    )
    assert len(history) == 1
    assert history[0].event.provider_event_id == event_id
    assert history[0].match is not None
    assert history[0].match.delivery_id == delivery_id


def test_provider_acceptance_and_webhook_race_always_correlates(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    provider_message_id = f"resend-acceptance-race-{uuid4()}"
    delivery_id, attempt_id, delivery_service = _claim_delivery(
        database, workspace_id
    )
    raw_body = _payload("email.sent", provider_message_id)
    event_id = f"msg_acceptance_race_{uuid4()}"
    headers = _headers(raw_body, event_id)
    verified = ResendWebhookVerifier(WEBHOOK_SECRET).verify(
        raw_body,
        event_id=event_id,
        timestamp=headers["svix-timestamp"],
        signature=headers["svix-signature"],
    )
    event_service = InvoiceDeliveryProviderEventService(
        SqlAlchemyInvoiceDeliveryProviderEventTransaction(database)
    )
    barrier = Barrier(2)

    def accept() -> None:
        barrier.wait()
        delivery_service.record_sent(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=attempt_id,
            provider_message_id=provider_message_id,
        )

    def ingest() -> None:
        barrier.wait()
        event_service.ingest(verified)

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(lambda operation: operation(), (accept, ingest)))

    history = event_service.list_for_delivery(
        workspace_id=workspace_id, delivery_id=delivery_id
    )
    assert len(history) == 1
    assert history[0].event.provider_event_id == event_id
    assert history[0].match is not None
    assert history[0].match.provider_message_id == provider_message_id
    assert (
        delivery_service.get(workspace_id, delivery_id).state
        is InvoiceDeliveryState.SENT
    )


def test_unsupported_and_unmatched_verified_events_remain_auditable(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    raw_body = _payload("email.opened", None)
    event_id = f"msg_unsupported_{uuid4()}"

    with TestClient(create_app(database)) as http:
        response = http.post(
            WEBHOOK_PATH, content=raw_body, headers=_headers(raw_body, event_id)
        )

    assert response.status_code == 200
    with Session(database) as session:
        event = session.scalar(
            select(InvoiceDeliveryProviderEventRow).where(
                InvoiceDeliveryProviderEventRow.provider_event_id == event_id
            )
        )
        assert event is not None
        assert event.provider_event_id == event_id
        assert event.event_kind == InvoiceDeliveryProviderEventKind.UNSUPPORTED.value
        assert event.provider_message_id is None
        assert session.get(InvoiceDeliveryProviderEventMatchRow, event.id) is None


def test_provider_event_history_is_workspace_isolated(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    workspace_id, other_workspace_id = uuid4(), uuid4()
    provider_message_id = f"resend-isolation-{uuid4()}"
    delivery_id, _ = _sent_delivery(database, workspace_id, provider_message_id)
    raw_body = _payload("email.delivered", provider_message_id)
    event_id = f"msg_isolation_{uuid4()}"

    with TestClient(create_app(database)) as http:
        assert (
            http.post(
                WEBHOOK_PATH,
                content=raw_body,
                headers=_headers(raw_body, event_id),
            ).status_code
            == 200
        )
        missing = http.get(
            f"/workspaces/{workspace_id}/invoice-deliveries/{uuid4()}/provider-events"
        )
        foreign = http.get(
            f"/workspaces/{other_workspace_id}/invoice-deliveries/{delivery_id}/provider-events"
        )

    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json() == {"detail": "Resource not found"}


class RollbackProviderEventTransaction:
    def __init__(
        self, base: SqlAlchemyInvoiceDeliveryProviderEventTransaction
    ) -> None:
        self.base = base

    def __call__(
        self,
    ) -> AbstractContextManager[InvoiceDeliveryProviderEventStore]:
        @contextmanager
        def transaction() -> Iterator[InvoiceDeliveryProviderEventStore]:
            with self.base() as store:
                yield store
                raise RuntimeError("rollback verified webhook")

        return transaction()


def test_provider_event_transaction_rollback_and_secret_absence(
    database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    provider_message_id = f"resend-rollback-{uuid4()}"
    raw_body = _payload("email.bounced", provider_message_id)
    event_id = f"msg_rollback_{uuid4()}"
    headers = _headers(raw_body, event_id)
    verified = ResendWebhookVerifier(WEBHOOK_SECRET).verify(
        raw_body,
        event_id=event_id,
        timestamp=headers["svix-timestamp"],
        signature=headers["svix-signature"],
    )
    service = InvoiceDeliveryProviderEventService(
        RollbackProviderEventTransaction(
            SqlAlchemyInvoiceDeliveryProviderEventTransaction(database)
        )
    )
    initial_count = _event_count(database)

    with pytest.raises(RuntimeError, match="rollback verified webhook"):
        service.ingest(verified)

    assert _event_count(database) == initial_count
    assert WEBHOOK_SECRET not in caplog.text
    with Session(database) as session:
        values = tuple(
            str(value)
            for value in session.execute(
                select(
                    InvoiceDeliveryProviderEventRow.provider_event_id,
                    InvoiceDeliveryProviderEventRow.payload_sha256,
                )
            )
        )
    assert all(WEBHOOK_SECRET not in value for value in values)
