from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.invoice_draft_transactions import (
    SqlAlchemyInvoiceDraftTransaction,
)
from freelanceflow.modules.billing.adapters.models import RateAgreementRow
from freelanceflow.modules.billing.application.invoice_drafts import (
    InvoiceAllocationInput,
    InvoiceDraftService,
    InvoiceLineConstructionInput,
)
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


def test_revision_api_preserves_history_identity_and_workspace_isolation(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Client"}
        ).json()
        project = http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
            json={"name": "Project"},
        ).json()
        _create_rate(http, workspace_id, client["id"], amount="80")
        first_entry = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T09:00:00Z",
            end="2026-01-01T09:20:00Z",
        )
        second_entry = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T10:00:00Z",
            end="2026-01-01T11:00:00Z",
        )
        collection = f"/workspaces/{workspace_id}/invoice-drafts"
        original = http.post(
            collection,
            json={
                "client_id": client["id"],
                "lines": [{"allocations": [_allocation(first_entry)]}],
            },
        ).json()
        revisions_path = f"{collection}/{original['id']}/revisions"
        revised_response = http.post(
            revisions_path,
            json={"lines": [{"allocations": [_allocation(second_entry)]}]},
        )
        assert revised_response.status_code == 201
        revised = revised_response.json()
        assert revised["id"] == original["id"]
        assert revised["revision"] == 2
        assert revised["workspace_id"] == original["workspace_id"]
        assert revised["client_id"] == original["client_id"]
        assert revised["currency"] == original["currency"]
        assert revised["lines"] != original["lines"]
        assert http.get(f"{collection}/{original['id']}").json() == revised
        assert http.get(revisions_path).json() == [original, revised]
        assert http.get(f"{revisions_path}/1").json() == original
        assert http.get(f"{revisions_path}/2").json() == revised

        for forbidden in [
            {"lines": [], "revision": 1},
            {"lines": [], "client_id": client["id"]},
            {"lines": [], "subtotal_minor_units": "0"},
            {"lines": [], "total_minor_units": "0"},
        ]:
            assert http.post(revisions_path, json=forbidden).status_code == 422
        assert http.put(
            f"{revisions_path}/1",
            json={"lines": [{"allocations": [_allocation(second_entry)]}]},
        ).status_code == 405
        assert http.get(f"{revisions_path}/1").json() == original

        for path in [
            f"/workspaces/{other_workspace_id}/invoice-drafts/{original['id']}/revisions",
            f"/workspaces/{other_workspace_id}/invoice-drafts/{original['id']}/revisions/1",
            f"/workspaces/{workspace_id}/invoice-drafts/{uuid4()}/revisions",
            f"/workspaces/{workspace_id}/invoice-drafts/{uuid4()}/revisions/1",
        ]:
            response = http.get(path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
        hidden_create = http.post(
            f"/workspaces/{other_workspace_id}/invoice-drafts/{original['id']}/revisions",
            json={"lines": [{"allocations": [_allocation(second_entry)]}]},
        )
        assert hidden_create.status_code == 404
        assert hidden_create.json() == {"detail": "Resource not found"}


def test_revision_rollback_preserves_head_and_nested_history(database: Engine) -> None:
    workspace_id, original = _large_exact_draft()
    transaction = SqlAlchemyInvoiceDraftTransaction(
        database, ClientRepository, TimeEntryRepository
    )
    with transaction(workspace_id) as drafts:
        drafts.add(original)
    revision = replace(
        original,
        revision=2,
        lines=tuple(replace(line, id=uuid4()) for line in original.lines),
    )
    with pytest.raises(RuntimeError, match="after revision flush"):
        with transaction(workspace_id) as drafts:
            assert drafts.get_for_revision(original.id) == original
            drafts.add_revision(revision)
            raise RuntimeError("after revision flush")
    with transaction(workspace_id) as drafts:
        assert drafts.get(original.id) == original
        assert drafts.get_revision(original.id, 2) is None
        assert drafts.list_revisions(original.id) == [original]


def test_database_enforces_unique_invoice_revision(database: Engine) -> None:
    workspace_id, original = _large_exact_draft()
    transaction = SqlAlchemyInvoiceDraftTransaction(
        database, ClientRepository, TimeEntryRepository
    )
    with transaction(workspace_id) as drafts:
        drafts.add(original)
    with Session(database) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    """
                    INSERT INTO invoice_drafts
                    SELECT * FROM invoice_drafts
                    WHERE id = :invoice_id AND revision = 1
                    """
                ),
                {"invoice_id": original.id},
            )
            session.flush()
        session.rollback()


def test_concurrent_revision_creation_is_serialized_by_postgresql(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        client = http.post(
            f"/workspaces/{workspace_id}/clients", json={"name": "Client"}
        ).json()
        project = http.post(
            f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
            json={"name": "Project"},
        ).json()
        _create_rate(http, workspace_id, client["id"], amount="80")
        entry = _create_entry(
            http,
            workspace_id,
            client["id"],
            project["id"],
            start="2026-01-01T09:00:00Z",
            end="2026-01-01T10:00:00Z",
        )
        original = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts",
            json={
                "client_id": client["id"],
                "lines": [{"allocations": [_allocation(entry)]}],
            },
        ).json()

    service = InvoiceDraftService(
        SqlAlchemyInvoiceDraftTransaction(
            database, ClientRepository, TimeEntryRepository
        )
    )
    source = InvoiceAllocationInput(
        time_entry_id=UUID(entry["id"]),
        start=datetime.fromisoformat(entry["start"]),
        end=datetime.fromisoformat(entry["end"]),
        business_date=date(2026, 1, 1),
    )
    lines = (InvoiceLineConstructionInput((source,)),)
    start_together = Barrier(2)

    def revise() -> int:
        start_together.wait()
        return service.create_revision(
            workspace_id=workspace_id,
            draft_id=UUID(original["id"]),
            lines=lines,
        ).revision

    with ThreadPoolExecutor(max_workers=2) as executor:
        revisions = list(executor.map(lambda _: revise(), range(2)))
    assert sorted(revisions) == [2, 3]
    assert [
        value.revision
        for value in service.list_revisions(workspace_id, UUID(original["id"]))
    ] == [1, 2, 3]
