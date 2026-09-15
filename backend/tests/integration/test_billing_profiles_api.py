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
from freelanceflow.modules.billing.adapters.billing_profile_repository import (
    BillingProfileRepository,
)
from freelanceflow.modules.billing.adapters.billing_profile_transactions import (
    SqlAlchemyBillingProfileTransaction,
)
from freelanceflow.modules.billing.application.billing_profiles import (
    BillingProfileService,
)
from freelanceflow.modules.clients.adapters.repository import ClientRepository


def _address(*, line1: str = "10 rue de la Paix") -> dict[str, str]:
    return {
        "line1": line1,
        "postal_code": "75002",
        "city": "Paris",
        "country_code": "FR",
    }


def _workspace_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "legal_entity_kind": "company",
        "legal_name": "Seller Legal SAS",
        "trading_name": "Seller Display",
        "siren": "552100554",
        "siret": "55210055400013",
        "vat_number": "FR96552100554",
        "legal_address": _address(),
        "billing_address": _address(line1="20 rue de Facturation"),
        "legal_form": "SAS",
        "share_capital": "1000.00100",
        "share_capital_currency": "EUR",
    }
    payload.update(changes)
    return payload


def _client_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "legal_name": "Buyer Legal SA",
        "trading_name": "Buyer Trading",
        "siren": "130025265",
        "vat_number": "FR07130025265",
        "legal_address": _address(line1="30 avenue de France"),
        "billing_address": None,
    }
    payload.update(changes)
    return payload


def _create_invoice_snapshot(
    http: TestClient, workspace_id: UUID, client_id: str
) -> tuple[str, dict[str, Any]]:
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client_id}/projects",
        json={"name": "Snapshot project"},
    ).json()
    rate = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client_id,
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
            "client_id": client_id,
            "project_id": project["id"],
            "task_id": None,
        },
    )
    assert entry.status_code == 201
    source = entry.json()
    created = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts",
        json={
            "client_id": client_id,
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


def test_profile_api_create_read_update_isolation_and_invoice_independence(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    workspace_path = f"/workspaces/{workspace_id}/billing-profile"
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Display-only name"}
        ).json()
        client_path = (
            f"/workspaces/{workspace_id}/clients/{client['id']}/billing-profile"
        )

        workspace_created = http.post(workspace_path, json=_workspace_payload())
        assert workspace_created.status_code == 201
        workspace_body = workspace_created.json()
        assert workspace_body["workspace_id"] == str(workspace_id)
        assert workspace_body["share_capital"] == "1000.00100"
        assert workspace_body["billing_address"]["line1"] == "20 rue de Facturation"
        assert http.get(workspace_path).json() == workspace_body

        client_created = http.post(client_path, json=_client_payload())
        assert client_created.status_code == 201
        client_body = client_created.json()
        assert client_body["client_id"] == client["id"]
        assert client_body["legal_name"] == "Buyer Legal SA"
        assert client["name"] == "Display-only name"
        assert http.get(client_path).json() == client_body

        invoice_id, invoice_before = _create_invoice_snapshot(
            http, workspace_id, client["id"]
        )
        workspace_updated = http.put(
            workspace_path,
            json=_workspace_payload(
                legal_name="Seller Legal SAS Updated", share_capital="2000.00"
            ),
        )
        assert workspace_updated.status_code == 200
        assert workspace_updated.json()["legal_name"] == "Seller Legal SAS Updated"
        client_updated = http.put(
            client_path,
            json=_client_payload(legal_name="Buyer Legal SA Updated"),
        )
        assert client_updated.status_code == 200
        assert client_updated.json()["legal_name"] == "Buyer Legal SA Updated"
        assert http.get(f"/workspaces/{workspace_id}/clients/{client['id']}").json()[
            "name"
        ] == "Display-only name"
        assert http.get(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice_id}"
        ).json() == invoice_before

        for local_path, foreign_path in [
            (
                f"/workspaces/{workspace_id}/clients/{uuid4()}/billing-profile",
                f"/workspaces/{other_workspace_id}/clients/{client['id']}/billing-profile",
            ),
            (
                f"/workspaces/{uuid4()}/billing-profile",
                f"/workspaces/{other_workspace_id}/billing-profile",
            ),
        ]:
            missing = http.get(local_path)
            foreign = http.get(foreign_path)
            assert missing.status_code == foreign.status_code == 404
            assert missing.json() == foreign.json() == {"detail": "Resource not found"}

        cross_workspace_create = http.post(
            f"/workspaces/{other_workspace_id}/clients/{client['id']}/billing-profile",
            json=_client_payload(),
        )
        missing_client_create = http.post(
            f"/workspaces/{other_workspace_id}/clients/{uuid4()}/billing-profile",
            json=_client_payload(),
        )
        assert cross_workspace_create.status_code == missing_client_create.status_code == 404
        assert cross_workspace_create.json() == missing_client_create.json()

        assert http.post(workspace_path, json=_workspace_payload()).status_code == 409
        assert http.post(client_path, json=_client_payload()).status_code == 409
        assert http.put(
            f"/workspaces/{workspace_id}/clients/{uuid4()}/billing-profile",
            json=_client_payload(),
        ).status_code == 404


@pytest.mark.parametrize(
    "path_kind,payload",
    [
        ("workspace", {}),
        ("workspace", _workspace_payload(siren="552100555")),
        ("workspace", _workspace_payload(siret="55210055400014")),
        ("workspace", _workspace_payload(vat_number="FR95552100554")),
        ("workspace", _workspace_payload(share_capital=1000.0)),
        ("workspace", _workspace_payload(workspace_id=str(uuid4()))),
        ("client", _client_payload(legal_name="\t\u00a0")),
        ("client", _client_payload(siren=None, vat_number=None)),
        ("client", _client_payload(client_id=str(uuid4()))),
        ("client", _client_payload(workspace_id=str(uuid4()))),
    ],
)
def test_profile_api_rejects_invalid_or_authoritative_transport_fields(
    database: Engine, path_kind: str, payload: dict[str, object]
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        if path_kind == "workspace":
            path = f"/workspaces/{workspace_id}/billing-profile"
        else:
            client = http.post(
                f"/workspaces/{workspace_id}/clients", json={"name": "Display"}
            ).json()
            path = (
                f"/workspaces/{workspace_id}/clients/{client['id']}/billing-profile"
            )
        assert http.post(path, json=payload).status_code == 422


def test_profile_repository_roundtrip_database_constraints_and_rollback(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Display"}
        ).json()
        assert http.post(
            f"/workspaces/{workspace_id}/billing-profile",
            json=_workspace_payload(),
        ).status_code == 201
        assert http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/billing-profile",
            json=_client_payload(),
        ).status_code == 201

    transaction = SqlAlchemyBillingProfileTransaction(database, ClientRepository)
    service = BillingProfileService(transaction)
    original = service.get_workspace(workspace_id)
    with pytest.raises(RuntimeError, match="rollback"):
        with transaction(workspace_id) as profiles:
            assert profiles.update_workspace_profile(
                replace(original, legal_name="Must roll back")
            )
            raise RuntimeError("rollback")
    assert service.get_workspace(workspace_id) == original

    with Session(database) as session:
        clients = ClientRepository(session, workspace_id=workspace_id)
        profiles = BillingProfileRepository(
            session, workspace_id=workspace_id, clients=clients
        )
        restored = profiles.get_client_profile(UUID(client["id"]))
        assert restored is not None
        assert restored.legal_name == "Buyer Legal SA"
        assert restored.legal_address.line1 == "30 avenue de France"

    with pytest.raises(IntegrityError, match="siren_shape"):
        with Session(database) as session, session.begin():
            session.execute(
                text(
                    "UPDATE workspace_billing_profiles SET siren = 'ABC' "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
