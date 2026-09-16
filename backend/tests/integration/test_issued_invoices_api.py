from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
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
from freelanceflow.modules.billing.adapters.issued_invoice_repository import (
    IssuedInvoiceRepository,
)
from freelanceflow.modules.billing.adapters.issued_invoice_transactions import (
    SqlAlchemyInvoiceIssuanceTransaction,
)
from freelanceflow.modules.billing.adapters.models import RateAgreementRow
from freelanceflow.modules.billing.application.invoice_drafts import (
    InvoiceAllocationInput,
    InvoiceDraftAlreadyIssuedError,
    InvoiceDraftService,
    InvoiceLineConstructionInput,
)
from freelanceflow.modules.billing.application.issued_invoices import (
    InvoiceIssuanceConflictError,
    InvoiceIssuanceService,
    IssueInvoiceCommand,
)
from freelanceflow.modules.billing.domain.issued_invoices import (
    InvoiceLineDescription,
    IssuedInvoice,
)
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.time_tracking.adapters.models import TimeEntryRow
from freelanceflow.modules.time_tracking.adapters.repository import TimeEntryRepository

ISSUED_AT = datetime(2026, 9, 15, 22, 30, 0, 123456, tzinfo=UTC)


def _address(line1: str) -> dict[str, object]:
    return {
        "line1": line1,
        "line2": None,
        "postal_code": "75002",
        "city": "Paris",
        "country_code": "FR",
    }


def _workspace_profile(*, legal_name: str = "Seller Legal SAS") -> dict[str, object]:
    return {
        "legal_entity_kind": "company",
        "legal_name": legal_name,
        "trading_name": "Seller display",
        "siren": "552100554",
        "siret": "55210055400013",
        "vat_number": "FR96552100554",
        "legal_address": _address("10 rue de la Paix"),
        "billing_address": None,
        "legal_form": "SAS",
        "share_capital": "1000.00",
        "share_capital_currency": "EUR",
    }


def _client_profile(*, legal_name: str = "Buyer Legal SA") -> dict[str, object]:
    return {
        "legal_name": legal_name,
        "trading_name": "Buyer display",
        "siren": "130025265",
        "vat_number": "FR07130025265",
        "legal_address": _address("30 avenue de France"),
        "billing_address": None,
    }


def _settings(*, vat_rate: str = "20.000", late_rate: str = "8.25") -> dict[str, object]:
    return {
        "fiscal": {
            "vat_regime": "taxable",
            "franchise_legal_basis": None,
            "default_vat_rate_percent": vat_rate,
            "vat_on_debits": True,
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
        "late_payment_penalty_annual_rate_percent": late_rate,
        "recovery_indemnity_policy": "french_b2b_40_eur",
        "operation_category": "services",
        "billing_timezone": "Europe/Paris",
    }


def _configure_workspace(http: TestClient, workspace_id: UUID) -> None:
    profile = http.post(
        f"/workspaces/{workspace_id}/billing-profile", json=_workspace_profile()
    )
    settings = http.post(
        f"/workspaces/{workspace_id}/invoice-settings", json=_settings()
    )
    assert profile.status_code == settings.status_code == 201


def _create_ready_draft(
    http: TestClient,
    workspace_id: UUID,
    *,
    client_name: str,
    start_hour: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    client = http.post(
        f"/workspaces/{workspace_id}/clients", json={"name": client_name}
    )
    assert client.status_code == 201
    client_body = cast(dict[str, Any], client.json())
    client_id = cast(str, client_body["id"])
    profile = http.post(
        f"/workspaces/{workspace_id}/clients/{client_id}/billing-profile",
        json=_client_profile(legal_name=f"{client_name} Legal SA"),
    )
    assert profile.status_code == 201
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client_id}/projects",
        json={"name": f"{client_name} project"},
    )
    assert project.status_code == 201
    project_body = cast(dict[str, Any], project.json())
    rate = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client_id,
            "project_id": None,
            "hourly_amount": "100.123400",
            "currency": "EUR",
            "valid_from": "2026-01-01",
            "valid_until": None,
        },
    )
    assert rate.status_code == 201
    start = f"2026-09-01T{start_hour:02d}:00:00.123456Z"
    end = f"2026-09-01T{start_hour:02d}:20:00.123457Z"
    entry = http.post(
        f"/workspaces/{workspace_id}/time-entries",
        json={
            "start": start,
            "end": end,
            "billable": True,
            "client_id": client_id,
            "project_id": project_body["id"],
            "task_id": None,
        },
    )
    assert entry.status_code == 201
    entry_body = cast(dict[str, Any], entry.json())
    allocation: dict[str, Any] = {
        "time_entry_id": entry_body["id"],
        "start": entry_body["start"],
        "end": entry_body["end"],
        "business_date": "2026-09-01",
    }
    draft = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts",
        json={"client_id": client_id, "lines": [{"allocations": [allocation]}]},
    )
    assert draft.status_code == 201
    return client_body, cast(dict[str, Any], draft.json()), allocation


def _issue_payload(
    draft: dict[str, Any],
    *,
    description: str = "Consulting services",
    purchase_order_number: str | None = "PO-42",
) -> dict[str, object]:
    return {
        "source_revision": draft["revision"],
        "service_completion_date": "2026-09-15",
        "purchase_order_number": purchase_order_number,
        "line_descriptions": [
            {
                "invoice_line_id": draft["lines"][0]["id"],
                "description": description,
            }
        ],
    }


def _service(database: Engine) -> InvoiceIssuanceService:
    return InvoiceIssuanceService(
        SqlAlchemyInvoiceIssuanceTransaction(
            database, ClientRepository, TimeEntryRepository
        ),
        clock=lambda: ISSUED_AT,
    )


def _command(draft: dict[str, Any]) -> IssueInvoiceCommand:
    return IssueInvoiceCommand(
        source_revision=cast(int, draft["revision"]),
        service_completion_date=date(2026, 9, 15),
        purchase_order_number="PO-42",
        line_descriptions=(
            InvoiceLineDescription(
                UUID(cast(str, draft["lines"][0]["id"])), "Consulting services"
            ),
        ),
    )


def _allocation_input(value: dict[str, Any]) -> InvoiceLineConstructionInput:
    return InvoiceLineConstructionInput(
        allocations=(
            InvoiceAllocationInput(
                time_entry_id=UUID(cast(str, value["time_entry_id"])),
                start=datetime.fromisoformat(cast(str, value["start"])),
                end=datetime.fromisoformat(cast(str, value["end"])),
                business_date=date.fromisoformat(cast(str, value["business_date"])),
            ),
        )
    )


def test_issuance_api_snapshots_history_idempotently_and_freezes_revision(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    app = create_app(database, invoice_clock=lambda: ISSUED_AT)
    with TestClient(app) as http:
        _configure_workspace(http, workspace_id)
        client, draft, allocation = _create_ready_draft(
            http, workspace_id, client_name="Acme", start_hour=9
        )
        path = f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue"
        payload = _issue_payload(draft)
        response = http.post(path, json=payload)
        assert response.status_code == 201, response.text
        issued = cast(dict[str, Any], response.json())
        assert issued["source_invoice_id"] == draft["id"]
        assert issued["source_revision"] == 1
        assert issued["invoice_number"] == issued["number_sequence"] == "1"
        assert issued["issued_at"] == "2026-09-15T22:30:00.123456Z"
        assert issued["billing_timezone"] == "Europe/Paris"
        assert issued["issue_date"] == "2026-09-16"
        assert issued["due_date"] == "2026-10-16"
        assert issued["seller"]["legal_name"] == "Seller Legal SAS"
        assert issued["client"]["legal_name"] == "Acme Legal SA"
        assert issued["lines"][0]["description"] == "Consulting services"
        assert issued["lines"][0]["allocations"][0]["source_time_entry_id"] == (
            allocation["time_entry_id"]
        )
        assert int(issued["ht_total_minor_units"]) + int(
            issued["vat_total_minor_units"]
        ) == int(issued["ttc_total_minor_units"])

        get_path = f"/workspaces/{workspace_id}/issued-invoices/{issued['id']}"
        assert http.get(get_path).json() == issued
        assert http.get(f"/workspaces/{workspace_id}/issued-invoices").json() == [issued]
        duplicate = http.post(path, json=payload)
        assert duplicate.status_code == 201
        assert duplicate.json() == issued
        assert http.post(
            path, json={**payload, "purchase_order_number": "PO-conflict"}
        ).status_code == 409

        revision = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/revisions",
            json={"lines": [{"allocations": [allocation]}]},
        )
        assert revision.status_code == 409
        assert http.put(get_path, json={}).status_code == 405
        assert http.delete(get_path).status_code == 405

        assert http.put(
            f"/workspaces/{workspace_id}/billing-profile",
            json=_workspace_profile(legal_name="Changed seller"),
        ).status_code == 200
        assert http.put(
            f"/workspaces/{workspace_id}/clients/{client['id']}/billing-profile",
            json=_client_profile(legal_name="Changed buyer"),
        ).status_code == 200
        assert http.put(
            f"/workspaces/{workspace_id}/invoice-settings",
            json=_settings(vat_rate="10.0", late_rate="9.0"),
        ).status_code == 200
        with Session(database) as session, session.begin():
            session.execute(
                delete(TimeEntryRow).where(
                    TimeEntryRow.id == UUID(cast(str, allocation["time_entry_id"]))
                )
            )
            session.execute(
                delete(RateAgreementRow).where(
                    RateAgreementRow.workspace_id == workspace_id
                )
            )
        assert http.get(get_path).json() == issued

        missing = http.get(f"/workspaces/{workspace_id}/issued-invoices/{uuid4()}")
        hidden = http.get(
            f"/workspaces/{other_workspace_id}/issued-invoices/{issued['id']}"
        )
        assert missing.status_code == hidden.status_code == 404
        assert missing.json() == hidden.json() == {"detail": "Resource not found"}
        assert http.get(
            f"/workspaces/{other_workspace_id}/issued-invoices"
        ).json() == []


def test_issuance_rejects_untrusted_totals_and_validation_does_not_consume_number(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _configure_workspace(http, workspace_id)
        _, draft, _ = _create_ready_draft(
            http, workspace_id, client_name="Validation", start_hour=10
        )
        path = f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue"
        payload = _issue_payload(draft)
        assert http.post(path, json={**payload, "total_minor_units": "1"}).status_code == 422
        invalid = http.post(
            path,
            json={**payload, "line_descriptions": []},
        )
        assert invalid.status_code == 422
        created = http.post(path, json=payload)
        assert created.status_code == 201, created.text
        assert created.json()["number_sequence"] == "1"


def test_number_allocation_rollback_reuses_uncommitted_number(database: Engine) -> None:
    workspace_id = uuid4()
    transaction = SqlAlchemyInvoiceIssuanceTransaction(
        database, ClientRepository, TimeEntryRepository
    )
    with pytest.raises(RuntimeError, match="after allocation"):
        with transaction(workspace_id) as store:
            assert store.allocate_number(date(2026, 9, 16)).sequence == 1
            raise RuntimeError("after allocation")
    with transaction(workspace_id) as store:
        assert store.allocate_number(date(2026, 9, 16)).sequence == 1


def test_nested_snapshot_failure_rolls_back_issuance_and_number(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _configure_workspace(http, workspace_id)
        _, draft, _ = _create_ready_draft(
            http, workspace_id, client_name="Rollback", start_hour=15
        )
    service = _service(database)
    original = IssuedInvoiceRepository.freeze_draft

    def fail_after_nested_snapshot(
        self: IssuedInvoiceRepository, value: IssuedInvoice
    ) -> None:
        raise RuntimeError("after nested issuance persistence")

    monkeypatch.setattr(
        IssuedInvoiceRepository, "freeze_draft", fail_after_nested_snapshot
    )
    with pytest.raises(RuntimeError, match="after nested issuance persistence"):
        service.issue(
            workspace_id=workspace_id,
            invoice_id=UUID(cast(str, draft["id"])),
            command=_command(draft),
        )
    assert service.list(workspace_id) == []
    monkeypatch.setattr(IssuedInvoiceRepository, "freeze_draft", original)
    issued = service.issue(
        workspace_id=workspace_id,
        invoice_id=UUID(cast(str, draft["id"])),
        command=_command(draft),
    )
    assert issued.number.sequence == 1


def test_missing_configuration_timezone_and_stale_revision_fail_before_number(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _, draft, allocation = _create_ready_draft(
            http, workspace_id, client_name="Preconditions", start_hour=16
        )
        path = f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue"
        assert http.post(path, json=_issue_payload(draft)).status_code == 422
        assert http.post(
            f"/workspaces/{workspace_id}/billing-profile",
            json=_workspace_profile(),
        ).status_code == 201
        no_timezone = _settings()
        no_timezone["billing_timezone"] = None
        assert http.post(
            f"/workspaces/{workspace_id}/invoice-settings", json=no_timezone
        ).status_code == 201
        assert http.post(path, json=_issue_payload(draft)).status_code == 422
        assert http.put(
            f"/workspaces/{workspace_id}/invoice-settings", json=_settings()
        ).status_code == 200

        revision = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/revisions",
            json={"lines": [{"allocations": [allocation]}]},
        )
        assert revision.status_code == 201
        assert http.post(path, json=_issue_payload(draft)).status_code == 409
        revised = cast(dict[str, Any], revision.json())
        issued = http.post(path, json=_issue_payload(revised))
        assert issued.status_code == 201, issued.text
        assert issued.json()["number_sequence"] == "1"


def test_concurrent_issuance_serializes_numbers_and_same_invoice_is_idempotent(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _configure_workspace(http, workspace_id)
        _, first, _ = _create_ready_draft(
            http, workspace_id, client_name="Concurrent one", start_hour=11
        )
        _, second, _ = _create_ready_draft(
            http, workspace_id, client_name="Concurrent two", start_hour=12
        )
    service = _service(database)
    barrier = Barrier(2)

    def issue(draft: dict[str, Any]) -> IssuedInvoice:
        barrier.wait()
        return service.issue(
            workspace_id=workspace_id,
            invoice_id=UUID(cast(str, draft["id"])),
            command=_command(draft),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(issue, (first, second)))
    assert {value.number.sequence for value in results} == {1, 2}

    same_workspace = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _configure_workspace(http, same_workspace)
        _, draft, _ = _create_ready_draft(
            http, same_workspace, client_name="Same", start_hour=13
        )
    same_service = _service(database)
    same_barrier = Barrier(2)

    def issue_same() -> IssuedInvoice:
        same_barrier.wait()
        return same_service.issue(
            workspace_id=same_workspace,
            invoice_id=UUID(cast(str, draft["id"])),
            command=_command(draft),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_results = list(executor.map(lambda _: issue_same(), range(2)))
    assert same_results[0].id == same_results[1].id
    assert same_results[0].number.sequence == same_results[1].number.sequence == 1


def test_issuance_racing_revision_has_one_deterministic_winner(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _configure_workspace(http, workspace_id)
        _, draft, allocation = _create_ready_draft(
            http, workspace_id, client_name="Revision race", start_hour=14
        )
    invoice_id = UUID(cast(str, draft["id"]))
    issuance = _service(database)
    revisions = InvoiceDraftService(
        SqlAlchemyInvoiceDraftTransaction(
            database, ClientRepository, TimeEntryRepository
        )
    )
    barrier = Barrier(2)

    def run_issuance() -> str:
        barrier.wait()
        try:
            issuance.issue(
                workspace_id=workspace_id,
                invoice_id=invoice_id,
                command=_command(draft),
            )
        except InvoiceIssuanceConflictError:
            return "issuance_conflict"
        return "issued"

    def run_revision() -> str:
        barrier.wait()
        try:
            revisions.create_revision(
                workspace_id=workspace_id,
                draft_id=invoice_id,
                lines=(_allocation_input(allocation),),
            )
        except InvoiceDraftAlreadyIssuedError:
            return "revision_conflict"
        return "revised"

    with ThreadPoolExecutor(max_workers=2) as executor:
        issue_future = executor.submit(run_issuance)
        revision_future = executor.submit(run_revision)
        outcomes = {issue_future.result(), revision_future.result()}
    assert outcomes in (
        {"issued", "revision_conflict"},
        {"revised", "issuance_conflict"},
    )
    history = revisions.list_revisions(workspace_id, invoice_id)
    assert history[0].revision == 1
    if "revised" in outcomes:
        assert [value.revision for value in history] == [1, 2]
