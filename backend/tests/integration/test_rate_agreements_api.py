from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.transactions import (
    SqlAlchemyRateAgreementTransaction,
)
from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.clients.adapters.transactions import SqlAlchemyClientTransaction
from freelanceflow.modules.clients.application.clients import ClientService


def test_rate_agreement_api(database: Engine) -> None:
    workspace, other_workspace = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace}/clients", json={"name": "Acme"}
        ).json()
        other_client = http.post(
            f"/workspaces/{workspace}/clients", json={"name": "Other"}
        ).json()
        project = http.post(
            f"/workspaces/{workspace}/clients/{client['id']}/projects",
            json={"name": "Website"},
        ).json()
        other_project = http.post(
            f"/workspaces/{workspace}/clients/{other_client['id']}/projects",
            json={"name": "Other project"},
        ).json()
        foreign_client = http.post(
            f"/workspaces/{other_workspace}/clients", json={"name": "Foreign"}
        ).json()
        foreign_project = http.post(
            f"/workspaces/{other_workspace}/clients/{foreign_client['id']}/projects",
            json={"name": "Foreign project"},
        ).json()
        path = f"/workspaces/{workspace}/rate-agreements"
        client_payload = {
            "client_id": client["id"],
            "project_id": None,
            "hourly_amount": "-0.1200",
            "currency": "EUR",
            "valid_from": "2026-01-01",
            "valid_until": None,
        }
        client_response = http.post(path, json=client_payload)
        assert client_response.status_code == 201
        client_rate = client_response.json()
        assert set(client_rate) == {
            "id",
            "workspace_id",
            "client_id",
            "project_id",
            "hourly_amount",
            "currency",
            "valid_from",
            "valid_until",
        }
        assert client_rate == {
            "id": client_rate["id"],
            "workspace_id": str(workspace),
            **client_payload,
        }
        UUID(client_rate["id"])

        project_payload = {
            "client_id": client["id"],
            "project_id": project["id"],
            "hourly_amount": "80.123456789012345678901234567890123456789",
            "currency": "USD",
            "valid_from": "2026-09-01",
            "valid_until": "2027-01-01",
        }
        project_rate = http.post(path, json=project_payload).json()
        assert project_rate == {
            "id": project_rate["id"],
            "workspace_id": str(workspace),
            **project_payload,
        }
        assert project_rate["id"] != client_rate["id"]
        assert http.get(f"{path}/{project_rate['id']}").json() == project_rate
        assert http.get(path).json() == sorted(
            [client_rate, project_rate], key=lambda item: item["id"]
        )
        assert http.get(f"/workspaces/{other_workspace}/rate-agreements").json() == []

        mismatch = {**project_payload, "project_id": other_project["id"]}
        response = http.post(path, json=mismatch)
        assert response.status_code == 422
        assert response.json() == {
            "detail": "Project must belong to the same client and workspace"
        }
        for missing_payload in [
            {**client_payload, "client_id": str(uuid4())},
            {**client_payload, "client_id": foreign_client["id"]},
            {**client_payload, "project_id": str(uuid4())},
            {**client_payload, "project_id": foreign_project["id"]},
        ]:
            response = http.post(path, json=missing_payload)
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
        for get_path in [
            f"{path}/{uuid4()}",
            f"/workspaces/{other_workspace}/rate-agreements/{client_rate['id']}",
        ]:
            response = http.get(get_path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
        for invalid_payload in [
            {**client_payload, "hourly_amount": 80.1},
            {**client_payload, "hourly_amount": "not-decimal"},
            {**client_payload, "hourly_amount": "NaN"},
            {**client_payload, "currency": " "},
            {**client_payload, "valid_until": "2026-01-01"},
            {**client_payload, "id": str(uuid4())},
        ]:
            assert http.post(path, json=invalid_payload).status_code == 422

        overlapping = http.post(path, json=client_payload)
        assert overlapping.status_code == 201


def test_rate_agreement_transaction_rolls_back(database: Engine) -> None:
    workspace = uuid4()
    client = ClientService(SqlAlchemyClientTransaction(database)).create(workspace, "Rollback")
    transaction = SqlAlchemyRateAgreementTransaction(database, ClientRepository)
    identifier = uuid4()
    agreement = RateAgreement(
        client=client,
        hourly_amount=Decimal("0"),
        currency="EUR",
        valid_from=date(2026, 1, 1),
    )
    with pytest.raises(RuntimeError, match="after flush"):
        with transaction(workspace) as rates:
            rates.add(identifier, agreement)
            raise RuntimeError("after flush")
    with transaction(workspace) as rates:
        assert rates.get(identifier) is None
