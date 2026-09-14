from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from freelanceflow.modules.delivery.domain.invoice_deliveries import (
    ApprovedInvoiceTarget,
    InvalidInvoiceDeliveryError,
    InvalidInvoiceDeliveryTransitionError,
    InvoiceDelivery,
    InvoiceDeliveryState,
    claim_invoice_delivery,
    fail_invoice_delivery,
    mark_invoice_delivery_sent,
    request_invoice_delivery,
)


def _approval() -> ApprovedInvoiceTarget:
    return ApprovedInvoiceTarget(
        approval_id=uuid4(),
        workspace_id=uuid4(),
        invoice_id=uuid4(),
        invoice_revision=4,
        artifact_id=uuid4(),
        artifact_sha256="a" * 64,
        approved_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
    )


def _pending() -> tuple[InvoiceDelivery, ApprovedInvoiceTarget]:
    approval = _approval()
    delivery = request_invoice_delivery(
        delivery_id=uuid4(),
        target=approval,
        requested_at=datetime(2026, 9, 14, 11, tzinfo=UTC),
    )
    return delivery, approval


def test_delivery_snapshots_exact_approval_target_and_stable_operation_key() -> None:
    delivery, approval = _pending()

    assert delivery.workspace_id == approval.workspace_id
    assert delivery.approval_id == approval.approval_id
    assert delivery.invoice_id == approval.invoice_id
    assert delivery.invoice_revision == approval.invoice_revision
    assert delivery.artifact_id == approval.artifact_id
    assert delivery.artifact_sha256 == approval.artifact_sha256
    assert delivery.state is InvoiceDeliveryState.PENDING
    assert delivery.provider_operation_key == str(delivery.id)


def test_failed_attempt_is_preserved_before_retry_and_success_is_terminal() -> None:
    pending, _ = _pending()
    first_id, second_id = uuid4(), uuid4()
    first_start = pending.requested_at + timedelta(seconds=1)
    claimed = claim_invoice_delivery(pending, attempt_id=first_id, started_at=first_start)
    failed = fail_invoice_delivery(
        claimed,
        attempt_id=first_id,
        failed_at=first_start + timedelta(seconds=1),
        failure_reason="definitive provider rejection",
    )

    assert failed.state is InvoiceDeliveryState.PENDING
    assert failed.attempts[0].failure_reason == "definitive provider rejection"
    assert failed.attempts[0].sequence == 1

    second_start = first_start + timedelta(seconds=2)
    retried = claim_invoice_delivery(failed, attempt_id=second_id, started_at=second_start)
    sent_at = second_start + timedelta(seconds=1)
    sent = mark_invoice_delivery_sent(retried, attempt_id=second_id, sent_at=sent_at)

    assert sent.state is InvoiceDeliveryState.SENT
    assert sent.sent_at == sent_at
    assert tuple(attempt.sequence for attempt in sent.attempts) == (1, 2)
    assert sent.attempts[0] == failed.attempts[0]
    with pytest.raises(InvalidInvoiceDeliveryTransitionError):
        claim_invoice_delivery(sent, attempt_id=uuid4(), started_at=sent_at)
    with pytest.raises(InvalidInvoiceDeliveryTransitionError):
        fail_invoice_delivery(
            sent,
            attempt_id=second_id,
            failed_at=sent_at,
            failure_reason="cannot rewrite success",
        )


def test_only_exact_active_claim_token_can_record_outcome() -> None:
    pending, _ = _pending()
    active = uuid4()
    claimed = claim_invoice_delivery(
        pending,
        attempt_id=active,
        started_at=pending.requested_at,
    )

    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="stale"):
        mark_invoice_delivery_sent(claimed, attempt_id=uuid4(), sent_at=claimed.requested_at)
    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="stale"):
        fail_invoice_delivery(
            claimed,
            attempt_id=uuid4(),
            failed_at=claimed.requested_at,
            failure_reason="wrong worker",
        )


@pytest.mark.parametrize(
    "change",
    [
        {"artifact_sha256": "A" * 64},
        {"artifact_sha256": 1},
        {"invoice_revision": 0},
        {"requested_at": datetime(2026, 9, 14, 11)},
    ],
)
def test_delivery_rejects_invalid_snapshot(change: dict[str, object]) -> None:
    delivery, _ = _pending()
    with pytest.raises(InvalidInvoiceDeliveryError):
        replace(delivery, **change)  # type: ignore[arg-type]


def test_claim_rejects_naive_or_pre_request_start() -> None:
    delivery, _ = _pending()
    with pytest.raises(InvalidInvoiceDeliveryError, match="UTC"):
        claim_invoice_delivery(delivery, attempt_id=uuid4(), started_at=datetime(2026, 9, 14, 11))
    with pytest.raises(InvalidInvoiceDeliveryTransitionError, match="precede"):
        claim_invoice_delivery(
            delivery,
            attempt_id=uuid4(),
            started_at=delivery.requested_at - timedelta(microseconds=1),
        )


def test_request_rejects_time_before_approval() -> None:
    approval = _approval()
    with pytest.raises(InvalidInvoiceDeliveryError, match="precede its approval"):
        request_invoice_delivery(
            delivery_id=uuid4(),
            target=approval,
            requested_at=approval.approved_at - timedelta(microseconds=1),
        )


def test_reconstructed_history_requires_open_or_sent_attempt_to_be_last() -> None:
    pending, _ = _pending()
    first = claim_invoice_delivery(pending, attempt_id=uuid4(), started_at=pending.requested_at)
    assert first.active_attempt_id is not None
    failed = fail_invoice_delivery(
        first,
        attempt_id=first.active_attempt_id,
        failed_at=first.requested_at,
        failure_reason="known failure",
    )
    second = claim_invoice_delivery(failed, attempt_id=uuid4(), started_at=failed.requested_at)

    open_attempt = replace(second.attempts[1], sequence=1)
    later_failed_attempt = replace(second.attempts[0], sequence=2)
    with pytest.raises(InvalidInvoiceDeliveryError, match="claim is inconsistent"):
        replace(
            second,
            attempts=(open_attempt, later_failed_attempt),
            active_attempt_id=open_attempt.id,
        )
