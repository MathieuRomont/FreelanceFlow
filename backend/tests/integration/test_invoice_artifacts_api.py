from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.billing.adapters.invoice_artifact_transactions import (
    SqlAlchemyInvoiceArtifactTransaction,
)
from freelanceflow.modules.billing.adapters.models import InvoiceArtifactRow
from freelanceflow.modules.billing.domain.invoice_artifacts import freeze_invoice_artifact


def _create_invoice(http: TestClient, workspace_id: UUID) -> dict[str, Any]:
    client = http.post(
        f"/workspaces/{workspace_id}/clients", json={"name": "Artifact client"}
    ).json()
    project = http.post(
        f"/workspaces/{workspace_id}/clients/{client['id']}/projects",
        json={"name": "Artifact project"},
    ).json()
    rate = http.post(
        f"/workspaces/{workspace_id}/rate-agreements",
        json={
            "client_id": client["id"],
            "project_id": None,
            "hourly_amount": "80",
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
    ).json()
    response = http.post(
        f"/workspaces/{workspace_id}/invoice-drafts",
        json={
            "client_id": client["id"],
            "lines": [
                {
                    "allocations": [
                        {
                            "time_entry_id": entry["id"],
                            "start": entry["start"],
                            "end": entry["end"],
                            "business_date": "2026-01-01",
                        }
                    ]
                }
            ],
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _collection(workspace_id: UUID, invoice: dict[str, Any], revision: int = 1) -> str:
    return (
        f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions/{revision}/artifacts"
    )


def test_artifact_api_exact_binary_integrity_duplicates_and_immutability(
    database: Engine,
) -> None:
    workspace_id = uuid4()
    payload = b"\x00\xffnot-a-pdf\x80"
    changed_payload = payload[:-1] + b"!"
    with TestClient(create_app(database)) as http:
        invoice = _create_invoice(http, workspace_id)
        collection = _collection(workspace_id, invoice)

        first_response = http.post(
            collection,
            content=payload,
            headers={
                "content-type": "application/pdf",
                "x-artifact-sha256": "0" * 64,
                "x-artifact-byte-size": "1",
            },
        )
        assert first_response.status_code == 201
        first = first_response.json()
        assert set(first) == {
            "id",
            "workspace_id",
            "invoice_id",
            "invoice_revision",
            "media_type",
            "sha256",
            "byte_size",
            "created_at",
        }
        assert first["workspace_id"] == str(workspace_id)
        assert first["invoice_id"] == invoice["id"]
        assert first["invoice_revision"] == 1
        assert first["media_type"] == "application/pdf"
        assert first["sha256"] == sha256(payload).hexdigest()
        assert first["byte_size"] == len(payload)
        assert datetime.fromisoformat(first["created_at"]).utcoffset() is not None

        duplicate = http.post(
            collection, content=payload, headers={"content-type": "application/pdf"}
        ).json()
        changed = http.post(
            collection,
            content=changed_payload,
            headers={"content-type": "application/pdf"},
        ).json()
        assert duplicate["id"] != first["id"]
        assert duplicate["sha256"] == first["sha256"]
        assert changed["sha256"] != first["sha256"]

        metadata_path = f"/workspaces/{workspace_id}/invoice-artifacts/{first['id']}"
        assert http.get(metadata_path).json() == first
        content_response = http.get(f"{metadata_path}/content")
        assert content_response.status_code == 200
        assert content_response.content == payload
        assert content_response.headers["content-type"] == "application/pdf"
        listed = http.get(collection).json()
        assert [value["id"] for value in listed] == [
            first["id"],
            duplicate["id"],
            changed["id"],
        ]

        mutation_responses = (
            http.put(metadata_path, content=b"replacement"),
            http.patch(metadata_path, content=b"replacement"),
            http.delete(metadata_path),
        )
        for response in mutation_responses:
            assert response.status_code == 405
        assert http.get(f"{metadata_path}/content").content == payload


def test_artifact_api_empty_media_revision_and_workspace_boundaries(
    database: Engine,
) -> None:
    workspace_id, other_workspace_id = uuid4(), uuid4()
    with TestClient(create_app(database)) as http:
        invoice = _create_invoice(http, workspace_id)
        collection = _collection(workspace_id, invoice)

        empty = http.post(collection, content=b"", headers={"content-type": "application/pdf"})
        missing_type = http.post(collection, content=b"bytes")
        assert empty.status_code == missing_type.status_code == 422

        created = http.post(
            collection,
            content=b"private bytes",
            headers={"content-type": "application/octet-stream"},
        ).json()
        paths = [
            _collection(other_workspace_id, invoice),
            _collection(workspace_id, invoice, revision=2),
            f"/workspaces/{workspace_id}/invoice-drafts/{uuid4()}/revisions/1/artifacts",
        ]
        for path in paths:
            missing = http.get(path)
            foreign = http.get(path.replace(str(workspace_id), str(other_workspace_id)))
            assert missing.status_code == foreign.status_code == 404
            assert missing.json() == foreign.json() == {"detail": "Resource not found"}
            assert (
                http.post(
                    path,
                    content=b"bytes",
                    headers={"content-type": "application/pdf"},
                ).status_code
                == 404
            )

        metadata_path = f"/workspaces/{workspace_id}/invoice-artifacts/{created['id']}"
        absent_path = f"/workspaces/{workspace_id}/invoice-artifacts/{uuid4()}"
        foreign_path = f"/workspaces/{other_workspace_id}/invoice-artifacts/{created['id']}"
        for suffix in ("", "/content"):
            absent = http.get(absent_path + suffix)
            foreign = http.get(foreign_path + suffix)
            assert absent.status_code == foreign.status_code == 404
            assert absent.json() == foreign.json() == {"detail": "Resource not found"}
        assert http.get(metadata_path).status_code == 200


def test_artifact_stays_bound_to_historical_revision(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice = _create_invoice(http, workspace_id)
        original = http.post(
            _collection(workspace_id, invoice),
            content=b"revision one",
            headers={"content-type": "application/pdf"},
        ).json()
        original_draft = http.get(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions/1"
        ).json()
        revision_response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions",
            json={"lines": original_draft["lines"]},
        )
        # Persisted draft response lines are not accepted construction inputs.
        assert revision_response.status_code == 422

        # Build revision 2 using the original source allocation transport fields.
        allocation = original_draft["lines"][0]["allocations"][0]
        revision_response = http.post(
            f"/workspaces/{workspace_id}/invoice-drafts/{invoice['id']}/revisions",
            json={
                "lines": [
                    {
                        "allocations": [
                            {
                                "time_entry_id": allocation["source_time_entry_id"],
                                "start": allocation["start"],
                                "end": allocation["end"],
                                "business_date": allocation["business_date"],
                            }
                        ]
                    }
                ]
            },
        )
        assert revision_response.status_code == 201
        later = http.post(
            _collection(workspace_id, invoice, revision=2),
            content=b"revision two",
            headers={"content-type": "application/pdf"},
        ).json()

        assert http.get(_collection(workspace_id, invoice)).json() == [original]
        assert http.get(_collection(workspace_id, invoice, revision=2)).json() == [later]
        original_path = f"/workspaces/{workspace_id}/invoice-artifacts/{original['id']}/content"
        assert http.get(original_path).content == b"revision one"


def test_artifact_transaction_rollback(database: Engine) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice = _create_invoice(http, workspace_id)

    artifact = freeze_invoice_artifact(
        artifact_id=uuid4(),
        workspace_id=workspace_id,
        invoice_id=UUID(invoice["id"]),
        invoice_revision=1,
        media_type="application/pdf",
        content=b"rolled back",
        created_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    transaction = SqlAlchemyInvoiceArtifactTransaction(database)
    with pytest.raises(RuntimeError, match="after artifact flush"):
        with transaction(workspace_id) as artifacts:
            artifacts.add(artifact)
            raise RuntimeError("after artifact flush")
    with transaction(workspace_id) as artifacts:
        assert artifacts.get(artifact.metadata.id) is None


@pytest.mark.parametrize(
    "case",
    [
        "missing_revision",
        "foreign_workspace",
        "blank_media_type",
        "empty_payload",
        "wrong_size",
        "noncanonical_digest",
    ],
)
def test_artifact_database_integrity_constraints(database: Engine, case: str) -> None:
    workspace_id = uuid4()
    with TestClient(create_app(database)) as http:
        invoice = _create_invoice(http, workspace_id)

    values: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "invoice_draft_id": UUID(invoice["id"]),
        "invoice_revision": 1,
        "media_type": "application/pdf",
        "sha256": sha256(b"payload").hexdigest(),
        "byte_size": 7,
        "content": b"payload",
        "created_at": datetime.now(UTC),
    }
    if case == "missing_revision":
        values["invoice_revision"] = 2
    elif case == "foreign_workspace":
        values["workspace_id"] = uuid4()
    elif case == "blank_media_type":
        values["media_type"] = "\u2003"
    elif case == "empty_payload":
        values["byte_size"] = 0
        values["content"] = b""
        values["sha256"] = sha256(b"").hexdigest()
    elif case == "wrong_size":
        values["byte_size"] = 1
    else:
        values["sha256"] = str(values["sha256"]).upper()

    with Session(database) as session:
        session.add(InvoiceArtifactRow(**cast(Any, values)))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
