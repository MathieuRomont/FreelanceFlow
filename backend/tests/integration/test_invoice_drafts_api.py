from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.invoice_draft_transactions import (
    SqlAlchemyInvoiceDraftTransaction,
)
from freelanceflow.modules.billing.adapters.models import RateAgreementRow
from freelanceflow.modules.billing.domain import RateAgreement
from freelanceflow.modules.billing.domain.invoice_drafts import (
    InvoiceDraft,
    InvoiceLineInput,
    build_invoice_draft,
)
from freelanceflow.modules.billing.domain.pricing import (
    PreparedBillingSegment,
    RateAgreementReference,
    price_prepared_segment,
)
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.clients.domain import Client, Project
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.modules.time_tracking.adapters.repository import TimeEntryRepository
from freelanceflow.modules.time_tracking.domain import TimeEntry


def _create_rate(
    http: TestClient,
    workspace_id: UUID,
    client_id: str,
    *,
    project_id: str | None = None,
    amount: str = "80.1200",
    currency: str = "EUR",
) -> dict[str, Any]:
    response = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client_id,
            "project_id": project_id,
            "hourly_amount": amount,
            "currency": currency,
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _create_entry(
    http: TestClient,
    workspace_id: UUID,
    client_id: str,
    project_id: str,
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    response = http.post(
        f"/workspaces/{workspace_id}/time-entries",
        json={
            "start": start,
            "end": end,
            "billable": True,
            "client_id": client_id,
            "project_id": project_id,
            "task_id": None,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _allocation(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_entry_id": entry["id"],
        "start": entry["start"],
        "end": entry["end"],
        "business_date": "2026-01-01",
    }


def test_invoice_draft_api_roundtrip_ordering_isolation_and_source_independence(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Snapshot client"}
        ).json()
        project = http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
            json={"name": "Snapshot project"},
        ).json()
        rate = _create_rate(http, workspace_id, client["id"])
        first = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T09:00:00.123456+01:00",
            end="2026-01-01T09:20:00.123456+01:00",
        )
        second = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T10:00:00Z",
            end="2026-01-01T10:10:00Z",
        )
        third = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T11:00:00Z",
            end="2026-01-01T11:10:00Z",
        )
        allocation_pair = sorted(
            [_allocation(second), _allocation(third)],
            key=lambda value: str(value["time_entry_id"]),
            reverse=True,
        )
        payload = {
            "client_id": client["id"],
            "lines": [
                {"allocations": [_allocation(first)]},
                {"allocations": allocation_pair},
            ],
        }
        response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts", json=payload
        )
        assert response.status_code == 201
        created = response.json()
        assert set(created) == {
            "id",
            "revision",
            "workspace_id",
            "client_id",
            "currency",
            "currency_decimal_places",
            "exact_subtotal",
            "subtotal_minor_units",
            "total_minor_units",
            "lines",
        }
        UUID(created["id"])
        assert created["revision"] == 1
        assert created["workspace_id"] == str(workspace_id)
        assert created["client_id"] == client["id"]
        assert created["currency"] == "EUR"
        assert created["currency_decimal_places"] == 2
        assert created["subtotal_minor_units"] == created["total_minor_units"]
        assert created["lines"][0]["allocations"][0]["source_time_entry_id"] == first["id"]
        ordered_pair = created["lines"][1]["allocations"]
        assert [value["source_time_entry_id"] for value in ordered_pair] == sorted(
            [second["id"], third["id"]]
        )
        assert created["lines"][0]["hourly_amount"] == "80.1200"
        assert created["lines"][0]["allocations"][0]["source_start"] == first["start"]

        path = f"/workspaces/{workspace_id}/invoice-drafts/{created['id']}"
        assert http.get(path).json() == created
        assert http.get(f"/workspaces/{workspace_id}/invoice-drafts").json() == [created]
        assert http.get(
            f"/workspaces/{other_workspace_id}/invoice-drafts"
        ).json() == []
        missing = http.get(f"/workspaces/{workspace_id}/invoice-drafts/{uuid4()}")
        foreign = http.get(
            f"/workspaces/{other_workspace_id}/invoice-drafts/{created['id']}"
        )
        assert missing.status_code == foreign.status_code == 404
        assert missing.json() == foreign.json() == {"detail": "Resource not found"}
        foreign_client = http.post(
            f"/workspaces/{other_workspace_id}/clients", json={"name": "Foreign"}
        ).json()
        foreign_project = http.post(
            f"/workspaces/{other_workspace_id}/clients/{foreign_client['id']}/projects",
            json={"name": "Foreign project"},
        ).json()
        foreign_entry = _create_entry(
            http,
            other_workspace_id,
            foreign_client["id"],
            foreign_project["id"],
            start="2026-01-01T12:00:00Z",
            end="2026-01-01T13:00:00Z",
        )
        hidden_source = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts",
            json={
                "client_id": client["id"],
                "lines": [{"allocations": [_allocation(foreign_entry)]}],
            },
        )
        absent_source = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts",
            json={
                "client_id": client["id"],
                "lines": [
                    {
                        "allocations": [
                            {
                                **_allocation(foreign_entry),
                                "time_entry_id": str(uuid4()),
                            }
                        ]
                    }
                ],
            },
        )
        assert hidden_source.status_code == absent_source.status_code == 404
        assert hidden_source.json() == absent_source.json() == {
            "detail": "Resource not found"
        }

        with Session(database) as session, session.begin():
            session.execute(
                delete(TimeEntryRow).where(
                    TimeEntryRow.id.in_([UUID(first["id"]), UUID(second["id"]), UUID(third["id"])])
                )
            )
            session.execute(delete(RateAgreementRow).where(RateAgreementRow.id == UUID(rate["id"])))
        assert http.get(path).json() == created


def test_invoice_draft_api_rejects_computed_fields_and_currency_policy(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Client"}
        ).json()
        project = http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
            json={"name": "EUR project"},
        ).json()
        usd_project = http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
            json={"name": "USD project"},
        ).json()
        _create_rate(http, workspace_id, client["id"], amount="80", currency="EUR")
        _create_rate(
            http,
            workspace_id,
            client["id"],
            project_id=usd_project["id"],
            amount="90",
            currency="USD",
        )
        eur_entry = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T09:00:00Z",
            end="2026-01-01T10:00:00Z",
        )
        usd_entry = _create_entry(
            http,
            workspace_id,
            client["id"],
            usd_project["id"],
            start="2026-01-01T10:00:00Z",
            end="2026-01-01T11:00:00Z",
        )
        path = f"/workspaces/{workspace_id}/invoice-drafts"
        eur_payload = {
            "client_id": client["id"],
            "lines": [{"allocations": [_allocation(eur_entry)]}],
        }
        for injected in [
            {**eur_payload, "subtotal_minor_units": "1"},
            {**eur_payload, "total_minor_units": "1"},
            {**eur_payload, "revision": 2},
            {**eur_payload, "id": str(uuid4())},
            {
                **eur_payload,
                "lines": [
                    {"allocations": [_allocation(eur_entry)], "rounded_minor_units": "1"}
                ],
            },
            {
                **eur_payload,
                "lines": [
                    {
                        "allocations": [
                            {**_allocation(eur_entry), "exact_amount": {"numerator": "1"}}
                        ]
                    }
                ],
            },
        ]:
            assert http.post(path, json=injected).status_code == 422
        unsupported = {
            "client_id": client["id"],
            "lines": [{"allocations": [_allocation(usd_entry)]}],
        }
        response = http.post(path, json=unsupported)
        assert response.status_code == 422
        assert "USD" in response.json()["detail"]
        mixed = {
            "client_id": client["id"],
            "lines": [
                {"allocations": [_allocation(eur_entry)]},
                {"allocations": [_allocation(usd_entry)]},
            ],
        }
        assert http.post(path, json=mixed).status_code == 422


def _large_exact_draft() -> tuple[UUID, InvoiceDraft]:
    workspace_id = uuid4()
    client = Client(uuid4(), workspace_id, "Client snapshot")
    project = Project(uuid4(), client, "Project snapshot")
    tiny_source = TimeEntry(
        uuid4(),
        workspace_id,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
        True,
        client,
        project,
    )
    tiny_rate = RateAgreementReference(
        uuid4(),
        RateAgreement(
            client,
            Decimal("0." + "0" * 99 + "1"),
            "EUR",
            date(2026, 1, 1),
            project=project,
        ),
    )
    tiny_priced = price_prepared_segment(
        PreparedBillingSegment.for_complete_entry(
            tiny_source, business_date=date(2026, 1, 1)
        ),
        [tiny_rate],
    )
    huge_source = TimeEntry(
        uuid4(),
        workspace_id,
        datetime(2026, 1, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 2, tzinfo=UTC),
        True,
        client,
        project,
    )
    huge_rate = RateAgreementReference(
        uuid4(),
        RateAgreement(
            client,
            Decimal("1" + "0" * 100),
            "EUR",
            date(2026, 1, 1),
            project=project,
        ),
    )
    huge_priced = price_prepared_segment(
        PreparedBillingSegment.for_complete_entry(
            huge_source, business_date=date(2026, 1, 1)
        ),
        [huge_rate],
    )
    draft = build_invoice_draft(
        draft_id=uuid4(),
        revision=1,
        workspace_id=workspace_id,
        client_id=client.id,
        line_inputs=(
            InvoiceLineInput(uuid4(), (tiny_priced,)),
            InvoiceLineInput(uuid4(), (huge_priced,)),
        ),
    )
    return workspace_id, draft


def test_exact_unbounded_numeric_roundtrip_and_nested_transaction_rollback(
    database: Engine,
) -> None:
    workspace_id, value = _large_exact_draft()
    transaction = SqlAlchemyInvoiceDraftTransaction(
        database, ClientRepository, TimeEntryRepository
    )
    with pytest.raises(RuntimeError, match="after nested flushes"):
        with transaction(workspace_id) as drafts:
            drafts.add(value)
            raise RuntimeError("after nested flushes")
    with transaction(workspace_id) as drafts:
        assert drafts.get(value.id) is None
        drafts.add(value)
    with transaction(workspace_id) as drafts:
        restored = drafts.get(value.id)
    assert restored == value
    assert len(str(value.exact_subtotal.numerator)) > 100
    assert len(str(value.exact_subtotal.denominator)) > 100
