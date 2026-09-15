"""HTTP-independent use cases for mutable legal billing profiles."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
    parse_exact_decimal,
)


class BillingProfileResourceNotFound(LookupError):
    """A requested workspace-scoped profile or parent is unavailable."""


class BillingProfileAlreadyExists(ValueError):
    """The one current profile for this owner already exists."""


@dataclass(frozen=True)
class WorkspaceBillingProfileData:
    legal_entity_kind: LegalEntityKind
    legal_name: str
    siren: str
    siret: str
    legal_address: BillingAddress
    trading_name: str | None = None
    billing_address: BillingAddress | None = None
    vat_number: str | None = None
    legal_form: str | None = None
    share_capital: str | None = None
    share_capital_currency: str | None = None


@dataclass(frozen=True)
class ClientBillingProfileData:
    legal_name: str
    legal_address: BillingAddress
    trading_name: str | None = None
    billing_address: BillingAddress | None = None
    siren: str | None = None
    vat_number: str | None = None


class BillingProfileStore(Protocol):
    def client_exists(self, client_id: UUID) -> bool: ...
    def add_workspace_profile(self, value: WorkspaceBillingProfile) -> bool: ...
    def get_workspace_profile(self) -> WorkspaceBillingProfile | None: ...
    def update_workspace_profile(self, value: WorkspaceBillingProfile) -> bool: ...
    def add_client_profile(self, value: ClientBillingProfile) -> bool: ...
    def get_client_profile(self, client_id: UUID) -> ClientBillingProfile | None: ...
    def update_client_profile(self, value: ClientBillingProfile) -> bool: ...


class BillingProfileTransaction(Protocol):
    def __call__(self, workspace_id: UUID) -> AbstractContextManager[BillingProfileStore]: ...


def _workspace_profile(
    workspace_id: UUID, data: WorkspaceBillingProfileData
) -> WorkspaceBillingProfile:
    return WorkspaceBillingProfile(
        workspace_id=workspace_id,
        legal_entity_kind=data.legal_entity_kind,
        legal_name=data.legal_name,
        trading_name=data.trading_name,
        siren=data.siren,
        siret=data.siret,
        vat_number=data.vat_number,
        legal_form=data.legal_form,
        share_capital=parse_exact_decimal(data.share_capital, field="Company share capital"),
        share_capital_currency=data.share_capital_currency,
        legal_address=data.legal_address,
        billing_address=data.billing_address,
    )


def _client_profile(
    workspace_id: UUID, client_id: UUID, data: ClientBillingProfileData
) -> ClientBillingProfile:
    return ClientBillingProfile(
        workspace_id=workspace_id,
        client_id=client_id,
        legal_name=data.legal_name,
        trading_name=data.trading_name,
        siren=data.siren,
        vat_number=data.vat_number,
        legal_address=data.legal_address,
        billing_address=data.billing_address,
    )


class BillingProfileService:
    def __init__(self, transaction: BillingProfileTransaction) -> None:
        self.transaction = transaction

    def create_workspace(
        self, workspace_id: UUID, data: WorkspaceBillingProfileData
    ) -> WorkspaceBillingProfile:
        profile = _workspace_profile(workspace_id, data)
        with self.transaction(workspace_id) as store:
            if not store.add_workspace_profile(profile):
                raise BillingProfileAlreadyExists("Workspace billing profile already exists")
        return profile

    def get_workspace(self, workspace_id: UUID) -> WorkspaceBillingProfile:
        with self.transaction(workspace_id) as store:
            profile = store.get_workspace_profile()
            if profile is None:
                raise BillingProfileResourceNotFound("Billing profile not found")
        return profile

    def update_workspace(
        self, workspace_id: UUID, data: WorkspaceBillingProfileData
    ) -> WorkspaceBillingProfile:
        profile = _workspace_profile(workspace_id, data)
        with self.transaction(workspace_id) as store:
            if not store.update_workspace_profile(profile):
                raise BillingProfileResourceNotFound("Billing profile not found")
        return profile

    def create_client(
        self,
        workspace_id: UUID,
        client_id: UUID,
        data: ClientBillingProfileData,
    ) -> ClientBillingProfile:
        profile = _client_profile(workspace_id, client_id, data)
        with self.transaction(workspace_id) as store:
            if not store.client_exists(client_id):
                raise BillingProfileResourceNotFound("Billing profile resource not found")
            if not store.add_client_profile(profile):
                raise BillingProfileAlreadyExists("Client billing profile already exists")
        return profile

    def get_client(
        self, workspace_id: UUID, client_id: UUID
    ) -> ClientBillingProfile:
        with self.transaction(workspace_id) as store:
            profile = store.get_client_profile(client_id)
            if profile is None:
                raise BillingProfileResourceNotFound("Billing profile not found")
        return profile

    def update_client(
        self,
        workspace_id: UUID,
        client_id: UUID,
        data: ClientBillingProfileData,
    ) -> ClientBillingProfile:
        profile = _client_profile(workspace_id, client_id, data)
        with self.transaction(workspace_id) as store:
            if not store.update_client_profile(profile):
                raise BillingProfileResourceNotFound("Billing profile not found")
        return profile
