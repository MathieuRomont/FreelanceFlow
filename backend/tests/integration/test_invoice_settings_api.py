from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.invoice_settings_repository import (
    InvoiceSettingsRepository,
)
from freelanceflow.modules.billing.adapters.invoice_settings_transactions import (
    SqlAlchemyInvoiceSettingsTransaction,
)
from freelanceflow.modules.billing.application.invoice_settings import (
    InvoiceSettingsService,
)


def _franchise_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fiscal": {
            "vat_regime": "franchise_en_base",
            "franchise_legal_basis": "cgi_293_b",
            "default_vat_rate_percent": None,
            "vat_on_debits": False,
        },
        "payment_terms": {
            "due_rule": "net_days_after_issue",
            "net_days": 30,
        },
        "early_payment_discount": {
            "kind": "none",
            "rate_percent": None,
            "days_after_issue": None,
        },
        "late_payment_penalty_annual_rate_percent": "12.5000",
        "recovery_indemnity_policy": "french_b2b_40_eur",
        "operation_category": "services",
    }
    payload.update(changes)
    return payload


def _taxable_payload(**changes: object) -> dict[str, object]:
    payload = _franchise_payload(
        fiscal={
            "vat_regime": "taxable",
            "franchise_legal_basis": None,
            "default_vat_rate_percent": "20.000100",
            "vat_on_debits": True,
        },
        early_payment_discount={
            "kind": "percentage_within_days",
            "rate_percent": "2.5000",
            "days_after_issue": 10,
        },
        payment_terms={
            "due_rule": "invoice_month_end_plus_45_days",
            "net_days": None,
        },
    )
    payload.update(changes)
    return payload


def _workspace_profile_payload(*, vat_number: str | None) -> dict[str, object]:
    return {
        "legal_entity_kind": "company",
        "legal_name": "Seller SAS",
        "trading_name": None,
        "siren": "552100554",
        "siret": "55210055400013",
        "vat_number": vat_number,
        "legal_address": {
            "line1": "10 rue de la Paix",
            "line2": None,
            "postal_code": "75002",
            "city": "Paris",
            "country_code": "FR",
        },
        "billing_address": None,
        "legal_form": "SAS",
        "share_capital": "1000.00",
        "share_capital_currency": "EUR",
    }


def _create_invoice_snapshot(http: TestClient, workspace_id: UUID) -> tuple[str, dict[str, Any]]:
    client = http.post(
        f"/workspaces/{workspace_id}/clients", json={"name": "Invoice client"}
    ).json()
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
        json={"name": "Invoice project"},
    ).json()
    rate = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client["id"],
            "project_id": None,
            "hourly_amount": "100",
            "currency": "EUR",
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    )
    assert rate.status_code == 201
    entry = http.post(
        f"/workspaces/{workspace_id}/time-entries",
        json={
            "start": "2026-01-01T09:00:00Z",
            "end": "2026-01-01T10:00:00Z",
            "billable": True,
            "client_id": client["id"],
            "project_id": project["id"],
            "task_id": None,
        },
    )
    assert entry.status_code == 201
    source = entry.json()
    created = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts",
        json={
            "client_id": client["id"],
            "lines": [
                {
                    "allocations": [
                        {
                            "time_entry_id": source["id"],
                            "start": source["start"],
                            "end": source["end"],
                            "business_date": "2026-01-01",
                        }
                    ]
                }
            ],
        },
    )
    assert created.status_code == 201
    draft = cast(dict[str, Any], created.json())
    return cast(str, draft["id"]), draft


def test_settings_api_create_read_update_isolation_and_invoice_independence(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    path = f"/workspaces/{workspace_id}/invoice-settings"
    with TestClient(create_app(database)) as http:
        created = http.post(path, json=_franchise_payload())
        assert created.status_code == 201
        body = created.json()
        assert body["workspace_id"] == str(workspace_id)
        assert body["fiscal"] == {
            "vat_regime": "franchise_en_base",
            "franchise_legal_basis": "cgi_293_b",
            "franchise_invoice_mention": ("TVA non applicable, article 293 B du CGI"),
            "default_vat_rate_percent": None,
            "vat_on_debits": False,
        }
        assert body["late_payment_penalty_annual_rate_percent"] == "12.5000"
        assert body["recovery_indemnity_currency"] == "EUR"
        assert body["recovery_indemnity_minor_units"] == 4_000
        assert http.get(path).json() == body

        invoice_id, invoice_before = _create_invoice_snapshot(http, workspace_id)
        updated = http.put(path, json=_taxable_payload())
        assert updated.status_code == 200
        updated_body = updated.json()
        assert updated_body["fiscal"]["default_vat_rate_percent"] == "20.000100"
        assert updated_body["fiscal"]["vat_on_debits"] is True
        assert updated_body["fiscal"]["franchise_invoice_mention"] is None
        assert updated_body["early_payment_discount"]["rate_percent"] == "2.5000"
        assert (
            http.get(f"/workspaces/{workspace_id}/invoice-drafts/{invoice_id}").json()
            == invoice_before
        )

        missing = http.get(f"/workspaces/{uuid4()}/invoice-settings")
        cross_workspace = http.get(f"/workspaces/{other_workspace_id}/invoice-settings")
        assert missing.status_code == cross_workspace.status_code == 404
        assert missing.json() == cross_workspace.json() == {"detail": "Resource not found"}
        assert http.post(path, json=_franchise_payload()).status_code == 409
        assert (
            http.put(
                f"/workspaces/{other_workspace_id}/invoice-settings",
                json=_franchise_payload(),
            ).status_code
            == 404
        )


def test_vat_identity_does_not_imply_vat_regime(database: Engine) -> None:
    franchise_workspace, taxable_workspace = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        profile = http.post(
            f"/workspaces/{franchise_workspace}/billing-profile",
            json=_workspace_profile_payload(vat_number="FR96552100554"),
        )
        assert profile.status_code == 201
        franchise = http.post(
            f"/workspaces/{franchise_workspace}/invoice-settings",
            json=_franchise_payload(),
        )
        assert franchise.status_code == 201
        assert franchise.json()["fiscal"]["vat_regime"] == "franchise_en_base"

        taxable_without_profile = http.post(
            f"/workspaces/{taxable_workspace}/invoice-settings",
            json=_taxable_payload(),
        )
        assert taxable_without_profile.status_code == 201
        assert taxable_without_profile.json()["fiscal"]["vat_regime"] == "taxable"


@pytest.mark.parametrize(
    "payload",
    [
        _franchise_payload(workspace_id="forbidden"),
        _taxable_payload(
            fiscal={
                "vat_regime": "taxable",
                "franchise_legal_basis": None,
                "default_vat_rate_percent": 20.0,
                "vat_on_debits": False,
            }
        ),
        _taxable_payload(
            fiscal={
                "vat_regime": "taxable",
                "franchise_legal_basis": None,
                "default_vat_rate_percent": "NaN",
                "vat_on_debits": False,
            }
        ),
        _taxable_payload(
            fiscal={
                "vat_regime": "taxable",
                "franchise_legal_basis": None,
                "default_vat_rate_percent": "100.01",
                "vat_on_debits": False,
            }
        ),
        _franchise_payload(
            fiscal={
                "vat_regime": "franchise_en_base",
                "franchise_legal_basis": None,
                "default_vat_rate_percent": None,
                "vat_on_debits": False,
            }
        ),
        _franchise_payload(
            payment_terms={
                "due_rule": "net_days_after_issue",
                "net_days": 61,
            }
        ),
        _franchise_payload(
            early_payment_discount={
                "kind": "none",
                "rate_percent": "1",
                "days_after_issue": None,
            }
        ),
        _franchise_payload(late_payment_penalty_annual_rate_percent="0"),
    ],
)
def test_settings_api_rejects_invalid_and_nonexact_input(
    database: Engine, payload: dict[str, object]
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        response = http.post(f"/workspaces/{workspace_id}/invoice-settings", json=payload)
    assert response.status_code == 422


def test_settings_repository_roundtrip_constraints_and_rollback(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    path = f"/workspaces/{workspace_id}/invoice-settings"
    with TestClient(create_app(database)) as http:
        created = http.post(path, json=_taxable_payload())
        assert created.status_code == 201

    transaction = SqlAlchemyInvoiceSettingsTransaction(database)
    service = InvoiceSettingsService(transaction)
    original = service.get(workspace_id)
    assert str(original.fiscal.default_vat_rate_percent) == "20.000100"
    with pytest.raises(RuntimeError, match="rollback"):
        with transaction(workspace_id) as settings:
            assert settings.update(
                replace(
                    original,
                    late_payment_penalty_annual_rate_percent=(
                        original.late_payment_penalty_annual_rate_percent + 1
                    ),
                )
            )
            raise RuntimeError("rollback")
    assert service.get(workspace_id) == original

    with Session(database) as session:
        restored = InvoiceSettingsRepository(session, workspace_id=workspace_id).get()
        assert restored == original

    with pytest.raises(IntegrityError, match="valid_payment_terms"):
        with Session(database) as session, session.begin():
            session.execute(
                text(
                    "UPDATE workspace_invoice_settings "
                    "SET payment_net_days = 61 "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
