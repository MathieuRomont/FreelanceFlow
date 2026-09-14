from datetime import date
from decimal import Decimal, DecimalException
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from freelanceflow.modules.billing.application.rate_agreements import (
    IdentifiedRateAgreement,
    RateAgreementResourceNotFound,
    RateAgreementService,
)
from freelanceflow.modules.billing.domain import InvalidRateAgreementError, RateOwnershipError

router = APIRouter(
    prefix="/workspaces/{workspace_id}/rate-agreements", tags=["rate-agreements"]
)


class CreateRateAgreementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    project_id: UUID | None = None
    hourly_amount: str
    currency: str
    valid_from: date
    valid_until: date | None = None


class RateAgreementResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    client_id: UUID
    project_id: UUID | None
    hourly_amount: str
    currency: str
    valid_from: date
    valid_until: date | None

    @classmethod
    def from_identified(cls, identified: IdentifiedRateAgreement) -> "RateAgreementResponse":
        agreement = identified.agreement
        return cls(
            id=identified.id,
            workspace_id=agreement.client.workspace_id,
            client_id=agreement.client.id,
            project_id=agreement.project.id if agreement.project else None,
            hourly_amount=str(agreement.hourly_amount),
            currency=agreement.currency,
            valid_from=agreement.valid_from,
            valid_until=agreement.valid_until,
        )


def get_rate_agreement_service() -> RateAgreementService:
    raise RuntimeError("RateAgreement service must be supplied by bootstrap")


Service = Annotated[RateAgreementService, Depends(get_rate_agreement_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


@router.post("", status_code=201, response_model=RateAgreementResponse)
def create_rate_agreement(
    workspace_id: UUID, body: CreateRateAgreementRequest, service: Service
) -> RateAgreementResponse:
    try:
        hourly_amount = Decimal(body.hourly_amount)
        identified = service.create(
            workspace_id=workspace_id,
            client_id=body.client_id,
            project_id=body.project_id,
            hourly_amount=hourly_amount,
            currency=body.currency,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
        )
    except DecimalException as error:
        raise HTTPException(status_code=422, detail="Hourly amount must be a Decimal") from error
    except (InvalidRateAgreementError, RateOwnershipError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RateAgreementResourceNotFound as error:
        raise _not_found() from error
    return RateAgreementResponse.from_identified(identified)


@router.get("", response_model=list[RateAgreementResponse])
def list_rate_agreements(
    workspace_id: UUID, service: Service
) -> list[RateAgreementResponse]:
    return [
        RateAgreementResponse.from_identified(identified)
        for identified in service.list(workspace_id)
    ]


@router.get("/{rate_agreement_id}", response_model=RateAgreementResponse)
def get_rate_agreement(
    workspace_id: UUID, rate_agreement_id: UUID, service: Service
) -> RateAgreementResponse:
    try:
        identified = service.get(workspace_id, rate_agreement_id)
    except RateAgreementResourceNotFound as error:
        raise _not_found() from error
    return RateAgreementResponse.from_identified(identified)
