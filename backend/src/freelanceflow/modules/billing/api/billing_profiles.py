"""Workspace-scoped HTTP boundary for legal billing profiles."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from freelanceflow.modules.billing.application.billing_profiles import (
    BillingProfileAlreadyExists,
    BillingProfileResourceNotFound,
    BillingProfileService,
    ClientBillingProfileData,
    WorkspaceBillingProfileData,
)
from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    InvalidBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
)

router = APIRouter(tags=["billing-profiles"])


class BillingAddressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    line1: str
    line2: str | None = None
    postal_code: str | None = None
    city: str
    country_code: str

    def to_domain(self) -> BillingAddress:
        return BillingAddress(
            line1=self.line1,
            line2=self.line2,
            postal_code=self.postal_code,
            city=self.city,
            country_code=self.country_code,
        )


class WorkspaceBillingProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_entity_kind: LegalEntityKind
    legal_name: str
    trading_name: str | None = None
    siren: str
    siret: str
    vat_number: str | None = None
    legal_address: BillingAddressRequest
    billing_address: BillingAddressRequest | None = None
    legal_form: str | None = None
    share_capital: str | None = None
    share_capital_currency: str | None = None

    def to_application(self) -> WorkspaceBillingProfileData:
        return WorkspaceBillingProfileData(
            legal_entity_kind=self.legal_entity_kind,
            legal_name=self.legal_name,
            trading_name=self.trading_name,
            siren=self.siren,
            siret=self.siret,
            vat_number=self.vat_number,
            legal_address=self.legal_address.to_domain(),
            billing_address=(
                self.billing_address.to_domain() if self.billing_address else None
            ),
            legal_form=self.legal_form,
            share_capital=self.share_capital,
            share_capital_currency=self.share_capital_currency,
        )


class ClientBillingProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str
    trading_name: str | None = None
    siren: str | None = None
    vat_number: str | None = None
    legal_address: BillingAddressRequest
    billing_address: BillingAddressRequest | None = None

    def to_application(self) -> ClientBillingProfileData:
        return ClientBillingProfileData(
            legal_name=self.legal_name,
            trading_name=self.trading_name,
            siren=self.siren,
            vat_number=self.vat_number,
            legal_address=self.legal_address.to_domain(),
            billing_address=(
                self.billing_address.to_domain() if self.billing_address else None
            ),
        )


class BillingAddressResponse(BaseModel):
    line1: str
    line2: str | None
    postal_code: str | None
    city: str
    country_code: str

    @classmethod
    def from_domain(cls, value: BillingAddress) -> "BillingAddressResponse":
        return cls(
            line1=value.line1,
            line2=value.line2,
            postal_code=value.postal_code,
            city=value.city,
            country_code=value.country_code,
        )


class WorkspaceBillingProfileResponse(BaseModel):
    workspace_id: UUID
    legal_entity_kind: LegalEntityKind
    legal_name: str
    trading_name: str | None
    siren: str
    siret: str
    vat_number: str | None
    legal_address: BillingAddressResponse
    billing_address: BillingAddressResponse | None
    legal_form: str | None
    share_capital: str | None
    share_capital_currency: str | None

    @classmethod
    def from_domain(
        cls, value: WorkspaceBillingProfile
    ) -> "WorkspaceBillingProfileResponse":
        return cls(
            workspace_id=value.workspace_id,
            legal_entity_kind=value.legal_entity_kind,
            legal_name=value.legal_name,
            trading_name=value.trading_name,
            siren=value.siren,
            siret=value.siret,
            vat_number=value.vat_number,
            legal_address=BillingAddressResponse.from_domain(value.legal_address),
            billing_address=(
                BillingAddressResponse.from_domain(value.billing_address)
                if value.billing_address
                else None
            ),
            legal_form=value.legal_form,
            share_capital=str(value.share_capital) if value.share_capital is not None else None,
            share_capital_currency=value.share_capital_currency,
        )


class ClientBillingProfileResponse(BaseModel):
    workspace_id: UUID
    client_id: UUID
    legal_name: str
    trading_name: str | None
    siren: str | None
    vat_number: str | None
    legal_address: BillingAddressResponse
    billing_address: BillingAddressResponse | None

    @classmethod
    def from_domain(
        cls, value: ClientBillingProfile
    ) -> "ClientBillingProfileResponse":
        return cls(
            workspace_id=value.workspace_id,
            client_id=value.client_id,
            legal_name=value.legal_name,
            trading_name=value.trading_name,
            siren=value.siren,
            vat_number=value.vat_number,
            legal_address=BillingAddressResponse.from_domain(value.legal_address),
            billing_address=(
                BillingAddressResponse.from_domain(value.billing_address)
                if value.billing_address
                else None
            ),
        )


def get_billing_profile_service() -> BillingProfileService:
    raise RuntimeError("BillingProfile service must be supplied by bootstrap")


Service = Annotated[BillingProfileService, Depends(get_billing_profile_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Resource not found")


def _create_error(error: Exception) -> HTTPException:
    if isinstance(error, BillingProfileAlreadyExists):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, BillingProfileResourceNotFound):
        return _not_found()
    return HTTPException(status_code=422, detail=str(error))


@router.post(
    "/workspaces/{workspace_id}/billing-profile",
    status_code=201,
    response_model=WorkspaceBillingProfileResponse,
)
def create_workspace_billing_profile(
    workspace_id: UUID,
    body: WorkspaceBillingProfileRequest,
    service: Service,
) -> WorkspaceBillingProfileResponse:
    try:
        profile = service.create_workspace(workspace_id, body.to_application())
    except (
        BillingProfileAlreadyExists,
        BillingProfileResourceNotFound,
        InvalidBillingProfile,
    ) as error:
        raise _create_error(error) from error
    return WorkspaceBillingProfileResponse.from_domain(profile)


@router.get(
    "/workspaces/{workspace_id}/billing-profile",
    response_model=WorkspaceBillingProfileResponse,
)
def get_workspace_billing_profile(
    workspace_id: UUID, service: Service
) -> WorkspaceBillingProfileResponse:
    try:
        profile = service.get_workspace(workspace_id)
    except BillingProfileResourceNotFound as error:
        raise _not_found() from error
    return WorkspaceBillingProfileResponse.from_domain(profile)


@router.put(
    "/workspaces/{workspace_id}/billing-profile",
    response_model=WorkspaceBillingProfileResponse,
)
def update_workspace_billing_profile(
    workspace_id: UUID,
    body: WorkspaceBillingProfileRequest,
    service: Service,
) -> WorkspaceBillingProfileResponse:
    try:
        profile = service.update_workspace(workspace_id, body.to_application())
    except (BillingProfileResourceNotFound, InvalidBillingProfile) as error:
        raise _create_error(error) from error
    return WorkspaceBillingProfileResponse.from_domain(profile)


@router.post(
    "/workspaces/{workspace_id}/clients/{client_id}/billing-profile",
    status_code=201,
    response_model=ClientBillingProfileResponse,
)
def create_client_billing_profile(
    workspace_id: UUID,
    client_id: UUID,
    body: ClientBillingProfileRequest,
    service: Service,
) -> ClientBillingProfileResponse:
    try:
        profile = service.create_client(
            workspace_id, client_id, body.to_application()
        )
    except (
        BillingProfileAlreadyExists,
        BillingProfileResourceNotFound,
        InvalidBillingProfile,
    ) as error:
        raise _create_error(error) from error
    return ClientBillingProfileResponse.from_domain(profile)


@router.get(
    "/workspaces/{workspace_id}/clients/{client_id}/billing-profile",
    response_model=ClientBillingProfileResponse,
)
def get_client_billing_profile(
    workspace_id: UUID, client_id: UUID, service: Service
) -> ClientBillingProfileResponse:
    try:
        profile = service.get_client(workspace_id, client_id)
    except BillingProfileResourceNotFound as error:
        raise _not_found() from error
    return ClientBillingProfileResponse.from_domain(profile)


@router.put(
    "/workspaces/{workspace_id}/clients/{client_id}/billing-profile",
    response_model=ClientBillingProfileResponse,
)
def update_client_billing_profile(
    workspace_id: UUID,
    client_id: UUID,
    body: ClientBillingProfileRequest,
    service: Service,
) -> ClientBillingProfileResponse:
    try:
        profile = service.update_client(
            workspace_id, client_id, body.to_application()
        )
    except (BillingProfileResourceNotFound, InvalidBillingProfile) as error:
        raise _create_error(error) from error
    return ClientBillingProfileResponse.from_domain(profile)
