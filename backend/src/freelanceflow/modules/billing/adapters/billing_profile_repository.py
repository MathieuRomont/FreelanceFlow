"""Explicit persistence mapping for current legal billing profiles."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from freelanceflow.modules.billing.adapters.billing_profile_models import (
    ClientBillingProfileRow,
    WorkspaceBillingProfileRow,
)
from freelanceflow.modules.billing.domain.billing_profiles import (
    BillingAddress,
    ClientBillingProfile,
    LegalEntityKind,
    WorkspaceBillingProfile,
)
from freelanceflow.modules.clients.application.catalog import ClientCatalog


def _address_from_row(row: object, prefix: str) -> BillingAddress | None:
    line1 = getattr(row, f"{prefix}_line1")
    if line1 is None:
        return None
    return BillingAddress(
        line1=line1,
        line2=getattr(row, f"{prefix}_line2"),
        postal_code=getattr(row, f"{prefix}_postal_code"),
        city=getattr(row, f"{prefix}_city"),
        country_code=getattr(row, f"{prefix}_country_code"),
    )


def _address_values(prefix: str, value: BillingAddress | None) -> dict[str, str | None]:
    return {
        f"{prefix}_line1": value.line1 if value else None,
        f"{prefix}_line2": value.line2 if value else None,
        f"{prefix}_postal_code": value.postal_code if value else None,
        f"{prefix}_city": value.city if value else None,
        f"{prefix}_country_code": value.country_code if value else None,
    }


def _workspace_values(value: WorkspaceBillingProfile) -> dict[str, object]:
    return {
        "workspace_id": value.workspace_id,
        "legal_entity_kind": value.legal_entity_kind.value,
        "legal_name": value.legal_name,
        "trading_name": value.trading_name,
        "siren": value.siren,
        "siret": value.siret,
        "vat_number": value.vat_number,
        "legal_form": value.legal_form,
        "share_capital": value.share_capital,
        "share_capital_currency": value.share_capital_currency,
        **_address_values("legal", value.legal_address),
        **_address_values("billing", value.billing_address),
    }


def _client_values(value: ClientBillingProfile) -> dict[str, object]:
    return {
        "client_id": value.client_id,
        "workspace_id": value.workspace_id,
        "legal_name": value.legal_name,
        "trading_name": value.trading_name,
        "siren": value.siren,
        "vat_number": value.vat_number,
        **_address_values("legal", value.legal_address),
        **_address_values("billing", value.billing_address),
    }


class BillingProfileRepository:
    def __init__(
        self,
        session: Session,
        *,
        workspace_id: UUID,
        clients: ClientCatalog,
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.clients = clients

    def client_exists(self, client_id: UUID) -> bool:
        return self.clients.get_client(client_id) is not None

    def add_workspace_profile(self, value: WorkspaceBillingProfile) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        created = self.session.scalar(
            insert(WorkspaceBillingProfileRow)
            .values(**_workspace_values(value))
            .on_conflict_do_nothing(index_elements=["workspace_id"])
            .returning(WorkspaceBillingProfileRow.workspace_id)
        )
        self.session.flush()
        return created is not None

    def get_workspace_profile(self) -> WorkspaceBillingProfile | None:
        row = self.session.get(WorkspaceBillingProfileRow, self.workspace_id)
        if row is None:
            return None
        legal_address = _address_from_row(row, "legal")
        assert legal_address is not None
        return WorkspaceBillingProfile(
            workspace_id=row.workspace_id,
            legal_entity_kind=LegalEntityKind(row.legal_entity_kind),
            legal_name=row.legal_name,
            trading_name=row.trading_name,
            siren=row.siren,
            siret=row.siret,
            vat_number=row.vat_number,
            legal_form=row.legal_form,
            share_capital=row.share_capital,
            share_capital_currency=row.share_capital_currency,
            legal_address=legal_address,
            billing_address=_address_from_row(row, "billing"),
        )

    def update_workspace_profile(self, value: WorkspaceBillingProfile) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        row = self.session.get(WorkspaceBillingProfileRow, self.workspace_id)
        if row is None:
            return False
        for field, field_value in _workspace_values(value).items():
            setattr(row, field, field_value)
        self.session.flush()
        return True

    def add_client_profile(self, value: ClientBillingProfile) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        created = self.session.scalar(
            insert(ClientBillingProfileRow)
            .values(**_client_values(value))
            .on_conflict_do_nothing(index_elements=["client_id"])
            .returning(ClientBillingProfileRow.client_id)
        )
        self.session.flush()
        return created is not None

    def get_client_profile(self, client_id: UUID) -> ClientBillingProfile | None:
        row = self.session.scalar(
            select(ClientBillingProfileRow).where(
                ClientBillingProfileRow.client_id == client_id,
                ClientBillingProfileRow.workspace_id == self.workspace_id,
            )
        )
        if row is None:
            return None
        legal_address = _address_from_row(row, "legal")
        assert legal_address is not None
        return ClientBillingProfile(
            workspace_id=row.workspace_id,
            client_id=row.client_id,
            legal_name=row.legal_name,
            trading_name=row.trading_name,
            siren=row.siren,
            vat_number=row.vat_number,
            legal_address=legal_address,
            billing_address=_address_from_row(row, "billing"),
        )

    def update_client_profile(self, value: ClientBillingProfile) -> bool:
        if value.workspace_id != self.workspace_id:
            raise ValueError("Workspace mismatch")
        row = self.session.scalar(
            select(ClientBillingProfileRow).where(
                ClientBillingProfileRow.client_id == value.client_id,
                ClientBillingProfileRow.workspace_id == self.workspace_id,
            )
        )
        if row is None:
            return False
        for field, field_value in _client_values(value).items():
            setattr(row, field, field_value)
        self.session.flush()
        return True
