from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.delivery.adapters.invoice_delivery_transactions import (
    SqlAlchemyInvoiceDeliveryTransaction,
)
from freelanceflow.modules.delivery.application.email_provider import (
    AmbiguousEmailDeliveryError,
    DefinitiveEmailDeliveryError,
    EmailAccepted,
    EmailDeliveryMessage,
    EmailDeliveryProviderError,
    RetryableEmailDeliveryError,
)
from freelanceflow.modules.delivery.application.invoice_deliveries import (
    InvoiceDeliverySender,
    InvoiceDeliveryService,
    InvoiceDeliveryStore,
    InvoiceEmailContent,
)
from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    InvalidInvoiceDeliveryTransitionError,
    InvoiceDeliveryState,
)

from .test_invoice_deliveries_api import (
    _approval_path,
    _create_artifact,
    _create_invoice,
    _delivery_path,
)


class FakeEmailProvider:
    def __init__(self, *outcomes: EmailAccepted | EmailDeliveryProviderError) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[EmailDeliveryMessage, str]] = []

    def send(
        self, message: EmailDeliveryMessage, *, idempotency_key: str
    ) -> EmailAccepted:
        self.calls.append((message, idempotency_key))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, EmailDeliveryProviderError):
            raise outcome
        return outcome


def _requested_delivery(
    database: Engine, workspace_id: UUID
) -> tuple[dict[str, object], bytes]:
    artifact_bytes = b"%PDF\x00\xff\x80exact frozen artifact"
    with TestClient(create_app(database)) as http:
        invoice, _ = _create_invoice(http, workspace_id)
        artifact = _create_artifact(
            http,
            workspace_id,
            invoice,
            content=artifact_bytes,
        )
        approval = http.post(_approval_path(workspace_id, invoice, artifact))
        assert approval.status_code == 200
        delivery_response = http.post(_delivery_path(workspace_id, invoice, artifact))
        assert delivery_response.status_code == 200
    return cast(dict[str, object], delivery_response.json()), artifact_bytes


def _content(*, subject: str = "Invoice September") -> InvoiceEmailContent:
    return InvoiceEmailContent(
        recipient="client@example.net",
        subject=subject,
        body="Please find your invoice attached.",
        attachment_filename="invoice-september.pdf",
    )


def test_provider_acceptance_persists_message_id_and_exact_artifact(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    requested, artifact_bytes = _requested_delivery(database, workspace_id)
    transaction = SqlAlchemyInvoiceDeliveryTransaction(database)
    service = InvoiceDeliveryService(transaction)
    claimed = service.claim_next(workspace_id)
    assert claimed is not None and claimed.active_attempt_id is not None
    provider = FakeEmailProvider(EmailAccepted("resend-message-accepted"))

    sent = InvoiceDeliverySender(
        transaction,
        provider,
        sender_identity="Freelancer <invoices@example.com>",
    ).send_claimed(
        workspace_id=workspace_id,
        delivery_id=UUID(str(requested["id"])),
        attempt_id=claimed.active_attempt_id,
        content=_content(),
    )

    assert sent.state is InvoiceDeliveryState.SENT
    assert sent.attempts[-1].provider_message_id == "resend-message-accepted"
    assert sent.message is not None
    assert sent.message.recipient == "client@example.net"
    message, key = provider.calls[0]
    assert key == f"invoice-delivery/{sent.id}"
    assert message.sender == "Freelancer <invoices@example.com>"
    assert message.attachment.content == artifact_bytes
    assert message.attachment.media_type == "application/pdf"
    assert message.attachment.filename == "invoice-september.pdf"
    assert service.get(workspace_id, sent.id) == sent


def test_retry_reuses_key_and_payload_and_rejects_message_change(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    requested, _ = _requested_delivery(database, workspace_id)
    delivery_id = UUID(str(requested["id"]))
    transaction = SqlAlchemyInvoiceDeliveryTransaction(database)
    service = InvoiceDeliveryService(transaction)
    provider = FakeEmailProvider(
        RetryableEmailDeliveryError("rate_limit_exceeded"),
        EmailAccepted("resend-message-after-retry"),
    )
    sender = InvoiceDeliverySender(
        transaction,
        provider,
        sender_identity="Freelancer <invoices@example.com>",
    )

    first = service.claim_next(workspace_id)
    assert first is not None and first.active_attempt_id is not None
    pending = sender.send_claimed(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=first.active_attempt_id,
        content=_content(),
    )
    assert pending.state is InvoiceDeliveryState.PENDING
    assert pending.attempts[-1].outcome == "failed"

    second = service.claim_next(workspace_id)
    assert second is not None and second.active_attempt_id is not None
    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="cannot change"):
        sender.send_claimed(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=second.active_attempt_id,
            content=_content(subject="Changed subject"),
        )
    assert len(provider.calls) == 1

    sent = sender.send_claimed(
        workspace_id=workspace_id,
        delivery_id=delivery_id,
        attempt_id=second.active_attempt_id,
        content=_content(),
    )
    assert sent.state is InvoiceDeliveryState.SENT
    assert len(provider.calls) == 2
    assert provider.calls[0] == provider.calls[1]


@pytest.mark.parametrize(
    "provider_error,expected_state,expected_outcome",
    [
        (
            DefinitiveEmailDeliveryError("invalid_from_address"),
            InvoiceDeliveryState.FAILED,
            "rejected",
        ),
        (
            AmbiguousEmailDeliveryError("transport_outcome_unknown"),
            InvoiceDeliveryState.IN_PROGRESS,
            "ambiguous",
        ),
    ],
)
def test_definitive_and_ambiguous_outcomes_are_not_reclaimed(
    database: Engine,
    provider_error: EmailDeliveryProviderError,
    expected_state: InvoiceDeliveryState,
    expected_outcome: str,
) -> None:
    workspace_id = uuid4()
    requested, _ = _requested_delivery(database, workspace_id)
    transaction = SqlAlchemyInvoiceDeliveryTransaction(database)
    service = InvoiceDeliveryService(transaction)
    claimed = service.claim_next(workspace_id)
    assert claimed is not None and claimed.active_attempt_id is not None

    result = InvoiceDeliverySender(
        transaction,
        FakeEmailProvider(provider_error),
        sender_identity="Freelancer <invoices@example.com>",
    ).send_claimed(
        workspace_id=workspace_id,
        delivery_id=UUID(str(requested["id"])),
        attempt_id=claimed.active_attempt_id,
        content=_content(),
    )

    assert result.state is expected_state
    assert result.attempts[-1].outcome == expected_outcome
    assert result.attempts[-1].failure_reason == provider_error.reason_code
    assert result.attempts[-1].provider_message_id is None
    assert service.claim_next(workspace_id) is None


class RollbackSecondTransaction:
    def __init__(self, base: SqlAlchemyInvoiceDeliveryTransaction) -> None:
        self.base = base
        self.calls = 0

    def __call__(
        self, workspace_id: UUID
    ) -> AbstractContextManager[InvoiceDeliveryStore]:
        @contextmanager
        def transaction() -> Iterator[InvoiceDeliveryStore]:
            self.calls += 1
            current_call = self.calls
            with self.base(workspace_id) as store:
                yield store
                if current_call == 2:
                    raise RuntimeError("rollback provider acceptance")

        return transaction()


def test_provider_acceptance_result_rolls_back_without_false_sent_state(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    requested, _ = _requested_delivery(database, workspace_id)
    delivery_id = UUID(str(requested["id"]))
    base = SqlAlchemyInvoiceDeliveryTransaction(database)
    service = InvoiceDeliveryService(base)
    claimed = service.claim_next(workspace_id)
    assert claimed is not None and claimed.active_attempt_id is not None
    provider = FakeEmailProvider(EmailAccepted("accepted-before-rollback"))

    with pytest.raises(RuntimeError, match="rollback provider acceptance"):
        InvoiceDeliverySender(
            RollbackSecondTransaction(base),
            provider,
            sender_identity="Freelancer <invoices@example.com>",
        ).send_claimed(
            workspace_id=workspace_id,
            delivery_id=delivery_id,
            attempt_id=claimed.active_attempt_id,
            content=_content(),
        )

    persisted = service.get(workspace_id, delivery_id)
    assert len(provider.calls) == 1
    assert persisted.state is InvoiceDeliveryState.IN_PROGRESS
    assert persisted.attempts[-1].outcome is None
    assert persisted.attempts[-1].provider_message_id is None
    assert persisted.message is not None


def test_database_rejects_partial_delivery_message_snapshot(database: Engine) -> None:
    workspace_id = uuid4()
    requested, _ = _requested_delivery(database, workspace_id)

    with Session(database) as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                UPDATE invoice_deliveries
                SET sender = 'invoices@example.com'
                WHERE id = :delivery_id
                """
            ),
            {"delivery_id": UUID(str(requested["id"]))},
        )
        session.commit()
