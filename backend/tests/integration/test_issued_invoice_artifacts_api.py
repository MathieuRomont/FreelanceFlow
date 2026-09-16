from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.billing_profile_models import (
    ClientBillingProfileRow,
    WorkspaceBillingProfileRow,
)
from freelanceflow.modules.billing.adapters.invoice_settings_models import (
    WorkspaceInvoiceSettingsRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_artifact_models import (
    IssuedInvoiceArtifactRow,
)
from freelanceflow.modules.billing.adapters.issued_invoice_artifact_transactions import (
    SqlAlchemyIssuedInvoiceArtifactTransaction,
)
from freelanceflow.modules.billing.adapters.issued_invoice_pdf_renderer import (
    ISSUED_INVOICE_PDF_MEDIA_TYPE,
    ISSUED_INVOICE_PDF_RENDERER_VERSION,
    ReportLabIssuedInvoicePdfRenderer,
)
from freelanceflow.modules.billing.application.issued_invoice_artifacts import (
    IssuedInvoiceArtifactService,
)
from freelanceflow.modules.clients.adapters.models import ClientRow

from .test_issued_invoices_api import (
    ISSUED_AT,
    _client_profile,
    _configure_workspace,
    _create_ready_draft,
    _issue_payload,
    _settings,
    _workspace_profile,
)

ARTIFACT_CREATED_AT = datetime(2026, 9, 16, 8, 0, 0, 654321, tzinfo=UTC)


def _issue(
    http: TestClient,
    workspace_id: UUID,
    *,
    description: str = "Mission de conseil & stratégie",
) -> tuple[dict[str, Any], dict[str, Any]]:
    _configure_workspace(http, workspace_id)
    client, draft, _allocation = _create_ready_draft(
        http, workspace_id, client_name="Acme Élégance", start_hour=9
    )
    response = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts/{draft['id']}/issue",
        json=_issue_payload(draft, description=description),
    )
    assert response.status_code == 201
    return client, cast(dict[str, Any], response.json())


def _collection(workspace_id: UUID, issued_invoice_id: str | UUID) -> str:
    return f"/workspaces/{workspace_id}/issued-invoices/{issued_invoice_id}/artifacts"


def _artifact_path(workspace_id: UUID, artifact_id: str | UUID) -> str:
    return f"/workspaces/{workspace_id}/issued-invoice-artifacts/{artifact_id}"


def test_generated_pdf_uses_only_issued_snapshot_and_round_trips_exactly(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(
        create_app(database, invoice_clock=lambda: ARTIFACT_CREATED_AT)
    ) as http:
        client, issued = _issue(http, workspace_id)
        client_id = UUID(cast(str, client["id"]))

        changed_workspace = _workspace_profile(legal_name="MUTATED SELLER")
        changed_client = _client_profile(legal_name="MUTATED BUYER")
        changed_settings = _settings(vat_rate="10.000")
        assert http.put(
            f"/workspaces/{workspace_id}/billing-profile", json=changed_workspace
        ).status_code == 200
        assert http.put(
            f"/workspaces/{workspace_id}/clients/{client_id}/billing-profile",
            json=changed_client,
        ).status_code == 200
        assert http.put(
            f"/workspaces/{workspace_id}/invoice-settings", json=changed_settings
        ).status_code == 200
        with Session(database) as session, session.begin():
            session.execute(
                update(ClientRow)
                .where(ClientRow.id == client_id)
                .values(name="MUTATED DISPLAY NAME")
            )

        response = http.post(
            _collection(workspace_id, issued["id"]),
            json={
                "content": "caller bytes",
                "sha256": "0" * 64,
                "byte_size": 1,
                "financial_total": "0.00",
            },
        )
        assert response.status_code == 201
        metadata = cast(dict[str, Any], response.json())
        assert set(metadata) == {
            "id",
            "workspace_id",
            "issued_invoice_id",
            "representation",
            "renderer_version",
            "media_type",
            "sha256",
            "byte_size",
            "created_at",
        }
        assert metadata["representation"] == "pdf"
        assert metadata["renderer_version"] == ISSUED_INVOICE_PDF_RENDERER_VERSION
        assert metadata["media_type"] == ISSUED_INVOICE_PDF_MEDIA_TYPE
        assert metadata["created_at"] == "2026-09-16T08:00:00.654321Z"

        metadata_path = _artifact_path(workspace_id, metadata["id"])
        content_response = http.get(f"{metadata_path}/content")
        content = content_response.content
        assert content_response.status_code == 200
        assert content_response.headers["content-type"] == "application/pdf"
        assert content.startswith(b"%PDF-")
        assert metadata["sha256"] == sha256(content).hexdigest()
        assert metadata["byte_size"] == len(content)
        assert http.get(metadata_path).json() == metadata
        assert http.get(_collection(workspace_id, issued["id"])).json() == [metadata]

        extracted = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(content)).pages
        )
        assert "Seller Legal SAS" in extracted
        assert "Acme Élégance Legal SA" in extracted
        assert "Mission de conseil & stratégie" in extracted
        assert "20.000 %" in extracted
        assert "MUTATED SELLER" not in extracted
        assert "MUTATED BUYER" not in extracted
        assert "MUTATED DISPLAY NAME" not in extracted
        assert "10.000 %" not in extracted

        duplicate = http.post(_collection(workspace_id, issued["id"]))
        assert duplicate.status_code == 201
        assert duplicate.json() == metadata
        assert http.get(f"{metadata_path}/content").content == content

        for mutation in (
            http.put(metadata_path, content=b"replacement"),
            http.patch(metadata_path, content=b"replacement"),
            http.delete(metadata_path),
        ):
            assert mutation.status_code == 405


def test_issued_artifact_workspace_and_missing_boundaries(database: Engine) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(
        create_app(database, invoice_clock=lambda: ARTIFACT_CREATED_AT)
    ) as http:
        _client, issued = _issue(http, workspace_id)
        artifact = http.post(_collection(workspace_id, issued["id"])).json()

        missing_collection = _collection(workspace_id, uuid4())
        foreign_collection = _collection(other_workspace_id, issued["id"])
        for method in (http.get, http.post):
            missing = method(missing_collection)
            foreign = method(foreign_collection)
            assert missing.status_code == foreign.status_code == 404
            assert missing.json() == foreign.json() == {"detail": "Resource not found"}

        missing_path = _artifact_path(workspace_id, uuid4())
        foreign_path = _artifact_path(other_workspace_id, artifact["id"])
        for suffix in ("", "/content"):
            missing = http.get(missing_path + suffix)
            foreign = http.get(foreign_path + suffix)
            assert missing.status_code == foreign.status_code == 404
            assert missing.json() == foreign.json() == {"detail": "Resource not found"}


def test_concurrent_duplicate_generation_returns_one_canonical_artifact(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _client, issued = _issue(http, workspace_id)
    issued_invoice_id = UUID(cast(str, issued["id"]))

    def generate() -> UUID:
        service = IssuedInvoiceArtifactService(
            SqlAlchemyIssuedInvoiceArtifactTransaction(database),
            ReportLabIssuedInvoicePdfRenderer(),
            clock=lambda: ARTIFACT_CREATED_AT,
        )
        return service.generate_pdf(
            workspace_id=workspace_id, issued_invoice_id=issued_invoice_id
        ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        artifact_ids = tuple(pool.map(lambda _value: generate(), range(2)))

    assert artifact_ids[0] == artifact_ids[1]
    with Session(database) as session:
        count = session.scalar(
            select(func.count())
            .select_from(IssuedInvoiceArtifactRow)
            .where(IssuedInvoiceArtifactRow.issued_invoice_id == issued_invoice_id)
        )
    assert count == 1


def test_issued_artifact_transaction_rolls_back_nested_snapshot(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database, invoice_clock=lambda: ISSUED_AT)) as http:
        _client, issued = _issue(http, workspace_id)
    issued_invoice_id = UUID(cast(str, issued["id"]))
    transaction = SqlAlchemyIssuedInvoiceArtifactTransaction(database)

    with pytest.raises(RuntimeError, match="after artifact flush"):
        with transaction(workspace_id) as store:
            invoice = store.lock_issued_invoice(issued_invoice_id)
            assert invoice is not None
            renderer = ReportLabIssuedInvoicePdfRenderer()
            from freelanceflow.modules.billing.domain.issued_invoice_artifacts import (
                IssuedInvoiceRepresentation,
                freeze_issued_invoice_artifact,
            )

            artifact = freeze_issued_invoice_artifact(
                artifact_id=uuid4(),
                workspace_id=workspace_id,
                issued_invoice_id=issued_invoice_id,
                representation=IssuedInvoiceRepresentation.PDF,
                renderer_version=renderer.renderer_version,
                media_type=renderer.media_type,
                content=renderer.render(invoice),
                created_at=ARTIFACT_CREATED_AT,
            )
            store.add(artifact)
            raise RuntimeError("after artifact flush")

    with transaction(workspace_id) as store:
        assert store.list_metadata(issued_invoice_id) == []


def test_issued_artifact_snapshot_foreign_keys_survive_live_configuration_changes(
    database: Engine,
) -> None:
    """Artifact rows bind IssuedInvoice only, not mutable profiles/settings."""
    workspace_id = uuid4()
    with TestClient(
        create_app(database, invoice_clock=lambda: ARTIFACT_CREATED_AT)
    ) as http:
        client, issued = _issue(http, workspace_id)
        artifact = http.post(_collection(workspace_id, issued["id"])).json()

    with Session(database) as session, session.begin():
        session.delete(session.get(WorkspaceBillingProfileRow, workspace_id))
        session.delete(session.get(WorkspaceInvoiceSettingsRow, workspace_id))
        client_profile = session.get(ClientBillingProfileRow, UUID(cast(str, client["id"])))
        session.delete(client_profile)

    with TestClient(create_app(database)) as http:
        assert http.get(
            _artifact_path(workspace_id, artifact["id"])
        ).status_code == 200
        assert http.get(
            f"{_artifact_path(workspace_id, artifact['id'])}/content"
        ).content.startswith(b"%PDF-")
