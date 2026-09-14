"""Provider-neutral email-delivery boundary."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID


class InvalidEmailDeliveryMessage(ValueError):
    """A provider-neutral email or attachment is structurally invalid."""


@dataclass(frozen=True)
class FrozenInvoiceAttachment:
    """Exact frozen artifact content loaded for a claimed delivery."""

    id: UUID
    workspace_id: UUID
    invoice_id: UUID
    invoice_revision: int
    sha256: str
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.id, self.workspace_id, self.invoice_id)
        ):
            raise InvalidEmailDeliveryMessage("Attachment identity values must be UUIDs")
        if type(self.invoice_revision) is not int or self.invoice_revision < 1:
            raise InvalidEmailDeliveryMessage(
                "Attachment invoice revision must be a positive integer"
            )
        if not isinstance(self.content, bytes) or not self.content:
            raise InvalidEmailDeliveryMessage("Attachment content must be nonempty bytes")
        if sha256(self.content).hexdigest() != self.sha256:
            raise InvalidEmailDeliveryMessage("Attachment SHA-256 is inconsistent")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise InvalidEmailDeliveryMessage("Attachment media type must be nonblank")


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not self.filename.strip():
            raise InvalidEmailDeliveryMessage("Attachment filename must be nonblank")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise InvalidEmailDeliveryMessage("Attachment media type must be nonblank")
        if not isinstance(self.content, bytes) or not self.content:
            raise InvalidEmailDeliveryMessage("Attachment content must be nonempty bytes")


@dataclass(frozen=True)
class EmailDeliveryMessage:
    sender: str
    recipient: str
    subject: str
    body: str
    attachment: EmailAttachment

    def __post_init__(self) -> None:
        for value, label in ((self.sender, "sender"), (self.recipient, "recipient")):
            if not isinstance(value, str) or not value.strip():
                raise InvalidEmailDeliveryMessage(f"Email {label} must be nonblank")
        if not isinstance(self.subject, str) or not isinstance(self.body, str):
            raise InvalidEmailDeliveryMessage("Email subject and body must be strings")
        if not isinstance(self.attachment, EmailAttachment):
            raise InvalidEmailDeliveryMessage("Email attachment is invalid")


@dataclass(frozen=True)
class EmailAccepted:
    provider_message_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_message_id, str)
            or not self.provider_message_id.strip()
        ):
            raise InvalidEmailDeliveryMessage("Provider message ID must be nonblank")


class EmailDeliveryProviderError(RuntimeError):
    """Base provider-neutral send failure with a safe persisted reason code."""

    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValueError("Email delivery reason code must be nonblank")
        self.reason_code = reason_code
        super().__init__(reason_code)


class DefinitiveEmailDeliveryError(EmailDeliveryProviderError):
    """The provider definitively rejected the request; retry is unsafe/useless."""


class RetryableEmailDeliveryError(EmailDeliveryProviderError):
    """The provider definitively did not accept this attempt; retry is allowed."""


class AmbiguousEmailDeliveryError(EmailDeliveryProviderError):
    """Acceptance is unknown; automatic retry is unsafe."""


class EmailDeliveryProvider(Protocol):
    def send(
        self, message: EmailDeliveryMessage, *, idempotency_key: str
    ) -> EmailAccepted: ...
