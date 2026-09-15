"""Authenticated Resend webhook ingress and workspace-scoped event history."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from freelanceflow.modules.delivery.application.provider_events import (
    EmailProviderWebhookVerifier,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    InvoiceDeliveryProviderEventResourceNotFound,
    InvoiceDeliveryProviderEventService,
    ProviderEventIdentityConflict,
)
from freelanceflow.modules.delivery.domain.provider_events import (
    InvoiceDeliveryProviderEventKind,
    InvoiceDeliveryProviderEventRecord,
)

router = APIRouter(tags=["invoice-delivery-provider-events"])


def get_email_provider_webhook_verifier() -> EmailProviderWebhookVerifier:
    raise RuntimeError("Email provider webhook verifier must be supplied by bootstrap")


def get_invoice_delivery_provider_event_service() -> InvoiceDeliveryProviderEventService:
    raise RuntimeError("Invoice delivery provider event service must be supplied by bootstrap")


Verifier = Annotated[
    EmailProviderWebhookVerifier, Depends(get_email_provider_webhook_verifier)
]
Service = Annotated[
    InvoiceDeliveryProviderEventService,
    Depends(get_invoice_delivery_provider_event_service),
]


class InvoiceDeliveryProviderEventResponse(BaseModel):
    id: UUID
    provider_event_id: str
    provider_message_id: str | None
    raw_event_type: str
    kind: InvoiceDeliveryProviderEventKind
    occurred_at: datetime
    received_at: datetime
    payload_sha256: str
    correlated_at: datetime

    @classmethod
    def from_record(
        cls, value: InvoiceDeliveryProviderEventRecord
    ) -> "InvoiceDeliveryProviderEventResponse":
        if value.match is None:
            raise ValueError("Workspace delivery history requires a correlated event")
        return cls(
            id=value.event.id,
            provider_event_id=value.event.provider_event_id,
            provider_message_id=value.event.provider_message_id,
            raw_event_type=value.event.raw_event_type,
            kind=value.event.kind,
            occurred_at=value.event.occurred_at,
            received_at=value.event.received_at,
            payload_sha256=value.event.payload_sha256,
            correlated_at=value.match.correlated_at,
        )


def _invalid_webhook(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail="Invalid webhook")


@router.post("/webhooks/resend", status_code=status.HTTP_200_OK)
async def ingest_resend_webhook(
    request: Request,
    verifier: Verifier,
    service: Service,
) -> Response:
    raw_body = await request.body()
    event_id = request.headers.get("svix-id")
    timestamp = request.headers.get("svix-timestamp")
    signature = request.headers.get("svix-signature")
    if event_id is None or timestamp is None or signature is None:
        raise _invalid_webhook(InvalidWebhookSignature("Missing signature headers"))
    try:
        verified = verifier.verify(
            raw_body,
            event_id=event_id,
            timestamp=timestamp,
            signature=signature,
        )
    except (InvalidWebhookSignature, InvalidWebhookPayload) as error:
        raise _invalid_webhook(error) from error
    try:
        service.ingest(verified)
    except ProviderEventIdentityConflict as error:
        raise HTTPException(
            status_code=409, detail="Webhook event identity conflict"
        ) from error
    return Response(status_code=status.HTTP_200_OK)


@router.get(
    "/workspaces/{workspace_id}/invoice-deliveries/{delivery_id}/provider-events",
    response_model=list[InvoiceDeliveryProviderEventResponse],
)
def list_invoice_delivery_provider_events(
    workspace_id: UUID,
    delivery_id: UUID,
    service: Service,
) -> list[InvoiceDeliveryProviderEventResponse]:
    try:
        records = service.list_for_delivery(
            workspace_id=workspace_id, delivery_id=delivery_id
        )
    except InvoiceDeliveryProviderEventResourceNotFound as error:
        raise HTTPException(status_code=404, detail="Resource not found") from error
    return [
        InvoiceDeliveryProviderEventResponse.from_record(record) for record in records
    ]
