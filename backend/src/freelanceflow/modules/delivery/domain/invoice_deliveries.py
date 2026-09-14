"""Durable invoice-delivery intent and deterministic state transitions."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from re import fullmatch
from uuid import UUID


class InvoiceDeliveryError(ValueError):
    """Base error for invalid delivery state or transitions."""


class InvalidInvoiceDeliveryError(InvoiceDeliveryError):
    """A delivery or attempt is structurally inconsistent."""


class InvalidInvoiceDeliveryTransitionError(InvoiceDeliveryError):
    """A requested transition is invalid for the current state or claim."""


class InvoiceDeliveryState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SENT = "sent"


class InvoiceDeliveryAttemptOutcome(StrEnum):
    SENT = "sent"
    FAILED = "failed"


def _require_utc(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise InvalidInvoiceDeliveryError(f"{label} must be UTC")


@dataclass(frozen=True)
class ApprovedInvoiceTarget:
    """Trusted snapshot exposed by Billing for creation of one delivery."""

    approval_id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    artifact_id: UUID
    artifact_sha256: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.approval_id,
                self.workspace_id,
                self.invoice_id,
                self.artifact_id,
            )
        ):
            raise InvalidInvoiceDeliveryError(
                "Approved invoice target identity values must be UUIDs"
            )
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise InvalidInvoiceDeliveryError(
                "Approved invoice target revision must be a positive integer"
            )
        if (
            not isinstance(self.artifact_sha256, str)
            or fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None
        ):
            raise InvalidInvoiceDeliveryError(
                "Approved invoice target SHA-256 must be lowercase hexadecimal"
            )
        _require_utc(self.approved_at, "Invoice approval time")


@dataclass(frozen=True)
class InvoiceDeliveryAttempt:
    """One immutable claim outcome; an open attempt is the active claim token."""

    id: UUID
    delivery_id: UUID
    sequence: int
    started_at: datetime
    completed_at: datetime | None = None
    outcome: InvoiceDeliveryAttemptOutcome | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.delivery_id, UUID):
            raise InvalidInvoiceDeliveryError("Delivery attempt IDs must be UUIDs")
        if type(self.sequence) is not int or self.sequence < 1:
            raise InvalidInvoiceDeliveryError(
                "Delivery attempt sequence must be a positive integer"
            )
        _require_utc(self.started_at, "Delivery attempt start time")
        if self.completed_at is not None:
            _require_utc(self.completed_at, "Delivery attempt completion time")
            if self.completed_at < self.started_at:
                raise InvalidInvoiceDeliveryError(
                    "Delivery attempt cannot complete before it starts"
                )
        if self.outcome is None:
            if self.completed_at is not None or self.failure_reason is not None:
                raise InvalidInvoiceDeliveryError(
                    "Open delivery attempt cannot have completion metadata"
                )
        elif self.outcome is InvoiceDeliveryAttemptOutcome.SENT:
            if self.completed_at is None or self.failure_reason is not None:
                raise InvalidInvoiceDeliveryError(
                    "Sent delivery attempt requires only a completion time"
                )
        elif self.outcome is InvoiceDeliveryAttemptOutcome.FAILED:
            if (
                self.completed_at is None
                or not isinstance(self.failure_reason, str)
                or not self.failure_reason.strip()
            ):
                raise InvalidInvoiceDeliveryError(
                    "Failed delivery attempt requires a nonblank reason"
                )
        else:
            raise InvalidInvoiceDeliveryError("Delivery attempt outcome is invalid")


@dataclass(frozen=True)
class InvoiceDelivery:
    """One logical delivery bound transitively to one immutable approval target."""

    id: UUID
    workspace_id: UUID
    approval_id: UUID
    invoice_id: UUID
    invoice_revision: int
    artifact_id: UUID
    artifact_sha256: str
    state: InvoiceDeliveryState
    requested_at: datetime
    active_attempt_id: UUID | None
    sent_at: datetime | None
    attempts: tuple[InvoiceDeliveryAttempt, ...]

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.id,
                self.workspace_id,
                self.approval_id,
                self.invoice_id,
                self.artifact_id,
            )
        ):
            raise InvalidInvoiceDeliveryError("Delivery identity values must be UUIDs")
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise InvalidInvoiceDeliveryError(
                "Delivery invoice revision must be a positive integer"
            )
        if (
            not isinstance(self.artifact_sha256, str)
            or fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None
        ):
            raise InvalidInvoiceDeliveryError(
                "Delivery artifact SHA-256 must be lowercase hexadecimal"
            )
        if not isinstance(self.state, InvoiceDeliveryState):
            raise InvalidInvoiceDeliveryError("Delivery state is invalid")
        _require_utc(self.requested_at, "Delivery request time")
        if self.active_attempt_id is not None and not isinstance(
            self.active_attempt_id, UUID
        ):
            raise InvalidInvoiceDeliveryError("Active delivery attempt ID must be a UUID")
        if self.sent_at is not None:
            _require_utc(self.sent_at, "Delivery sent time")
        if type(self.attempts) is not tuple:
            raise InvalidInvoiceDeliveryError("Delivery attempts must be a tuple")
        for expected_sequence, attempt in enumerate(self.attempts, start=1):
            if (
                not isinstance(attempt, InvoiceDeliveryAttempt)
                or attempt.delivery_id != self.id
                or attempt.sequence != expected_sequence
            ):
                raise InvalidInvoiceDeliveryError("Delivery attempt history is inconsistent")
        open_attempts = tuple(attempt for attempt in self.attempts if attempt.outcome is None)
        sent_attempts = tuple(
            attempt
            for attempt in self.attempts
            if attempt.outcome is InvoiceDeliveryAttemptOutcome.SENT
        )
        if self.state is InvoiceDeliveryState.PENDING:
            if self.active_attempt_id is not None or self.sent_at is not None:
                raise InvalidInvoiceDeliveryError(
                    "Pending delivery cannot have an active claim or sent time"
                )
            if open_attempts or sent_attempts:
                raise InvalidInvoiceDeliveryError(
                    "Pending delivery may contain only failed attempts"
                )
        elif self.state is InvoiceDeliveryState.IN_PROGRESS:
            if self.sent_at is not None or len(open_attempts) != 1:
                raise InvalidInvoiceDeliveryError(
                    "In-progress delivery requires exactly one active attempt"
                )
            if (
                self.active_attempt_id != open_attempts[0].id
                or self.attempts[-1] != open_attempts[0]
                or sent_attempts
            ):
                raise InvalidInvoiceDeliveryError("In-progress delivery claim is inconsistent")
        elif self.state is InvoiceDeliveryState.SENT:
            if self.active_attempt_id is not None or len(sent_attempts) != 1:
                raise InvalidInvoiceDeliveryError(
                    "Sent delivery requires exactly one successful attempt"
                )
            if (
                open_attempts
                or self.attempts[-1] != sent_attempts[0]
                or self.sent_at != sent_attempts[0].completed_at
            ):
                raise InvalidInvoiceDeliveryError("Sent delivery history is inconsistent")
        else:
            raise InvalidInvoiceDeliveryError("Delivery state is invalid")

    @property
    def provider_operation_key(self) -> str:
        """Stable key a future idempotent provider adapter may use."""
        return str(self.id)


def request_invoice_delivery(
    *, delivery_id: UUID, target: ApprovedInvoiceTarget, requested_at: datetime
) -> InvoiceDelivery:
    if not isinstance(target, ApprovedInvoiceTarget):
        raise InvalidInvoiceDeliveryError("Delivery requires an approved invoice target")
    _require_utc(requested_at, "Delivery request time")
    if requested_at < target.approved_at:
        raise InvalidInvoiceDeliveryError(
            "Delivery request cannot precede its approval"
        )
    return InvoiceDelivery(
        id=delivery_id,
        workspace_id=target.workspace_id,
        approval_id=target.approval_id,
        invoice_id=target.invoice_id,
        invoice_revision=target.invoice_revision,
        artifact_id=target.artifact_id,
        artifact_sha256=target.artifact_sha256,
        state=InvoiceDeliveryState.PENDING,
        requested_at=requested_at,
        active_attempt_id=None,
        sent_at=None,
        attempts=(),
    )


def claim_invoice_delivery(
    delivery: InvoiceDelivery, *, attempt_id: UUID, started_at: datetime
) -> InvoiceDelivery:
    _require_utc(started_at, "Delivery attempt start time")
    if delivery.state is not InvoiceDeliveryState.PENDING:
        raise InvalidInvoiceDeliveryTransitionError("Only a pending delivery can be claimed")
    if started_at < delivery.requested_at:
        raise InvalidInvoiceDeliveryTransitionError("Delivery claim cannot precede its request")
    attempt = InvoiceDeliveryAttempt(
        id=attempt_id,
        delivery_id=delivery.id,
        sequence=len(delivery.attempts) + 1,
        started_at=started_at,
    )
    return replace(
        delivery,
        state=InvoiceDeliveryState.IN_PROGRESS,
        active_attempt_id=attempt.id,
        attempts=(*delivery.attempts, attempt),
    )


def fail_invoice_delivery(
    delivery: InvoiceDelivery,
    *,
    attempt_id: UUID,
    failed_at: datetime,
    failure_reason: str,
) -> InvoiceDelivery:
    attempt = _active_attempt(delivery, attempt_id)
    failed_attempt = replace(
        attempt,
        completed_at=failed_at,
        outcome=InvoiceDeliveryAttemptOutcome.FAILED,
        failure_reason=failure_reason,
    )
    return replace(
        delivery,
        state=InvoiceDeliveryState.PENDING,
        active_attempt_id=None,
        attempts=(*delivery.attempts[:-1], failed_attempt),
    )


def mark_invoice_delivery_sent(
    delivery: InvoiceDelivery, *, attempt_id: UUID, sent_at: datetime
) -> InvoiceDelivery:
    attempt = _active_attempt(delivery, attempt_id)
    sent_attempt = replace(
        attempt,
        completed_at=sent_at,
        outcome=InvoiceDeliveryAttemptOutcome.SENT,
    )
    return replace(
        delivery,
        state=InvoiceDeliveryState.SENT,
        active_attempt_id=None,
        sent_at=sent_at,
        attempts=(*delivery.attempts[:-1], sent_attempt),
    )


def _active_attempt(delivery: InvoiceDelivery, attempt_id: UUID) -> InvoiceDeliveryAttempt:
    if (
        delivery.state is not InvoiceDeliveryState.IN_PROGRESS
        or delivery.active_attempt_id != attempt_id
        or not delivery.attempts
        or delivery.attempts[-1].id != attempt_id
    ):
        raise InvalidInvoiceDeliveryTransitionError("Delivery claim token is stale or invalid")
    return delivery.attempts[-1]
