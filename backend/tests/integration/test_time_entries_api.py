from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from freelanceflow.bootstrap.main import create_app
from freelanceflow.modules.clients.adapters.repository import ClientRepository
from freelanceflow.modules.time_tracking.adapters.transactions import (
    SqlAlchemyTimeEntryTransaction,
)
from freelanceflow.modules.time_tracking.domain import TimeEntry


def test_time_entry_api_lifecycle(database: Engine) -> None:
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
        task = http.post(
            f"/workspaces/{workspace}/projects/{project['id']}/tasks",
            json={"name": "Design"},
        ).json()
        foreign_client = http.post(
            f"/workspaces/{other_workspace}/clients", json={"name": "Foreign"}
        ).json()
        foreign_project = http.post(
            f"/workspaces/{other_workspace}/clients/{foreign_client['id']}/projects",
            json={"name": "Foreign project"},
        ).json()
        path = f"/workspaces/{workspace}/time-entries"
        payload = {
            "start": "2026-01-01T12:00:00.123456+05:30",
            "end": "2026-01-01T08:00:00.123457Z",
            "billable": False,
            "client_id": None,
            "project_id": None,
            "task_id": None,
        }
        response = http.post(path, json=payload)
        assert response.status_code == 201
        entry = response.json()
        assert set(entry) == {
            "id",
            "workspace_id",
            "start",
            "end",
            "duration",
            "billable",
            "client_id",
            "project_id",
            "task_id",
        }
        assert entry == {
            "id": entry["id"],
            "workspace_id": str(workspace),
            "duration": "PT1H30M0.000001S",
            **payload,
        }
        UUID(entry["id"])
        assert http.get(f"{path}/{entry['id']}").json() == entry
        assert http.get(path).json() == [entry]
        assert http.get(f"/workspaces/{other_workspace}/time-entries").json() == []

        classification = {
            "client_id": client["id"],
            "project_id": project["id"],
            "task_id": task["id"],
        }
        classify_path = f"{path}/{entry['id']}/classification"
        classified_response = http.put(classify_path, json=classification)
        assert classified_response.status_code == 200
        classified = classified_response.json()
        assert classified == {**entry, **classification}

        without_task = http.put(classify_path, json={**classification, "task_id": None}).json()
        assert without_task == {**entry, **classification, "task_id": None}
        reclassified = http.put(
            classify_path,
            json={
                "client_id": other_client["id"],
                "project_id": other_project["id"],
                "task_id": None,
            },
        ).json()
        assert reclassified["client_id"] == other_client["id"]
        assert reclassified["project_id"] == other_project["id"]
        assert reclassified["task_id"] is None
        for field in ("id", "workspace_id", "start", "end", "duration", "billable"):
            assert reclassified[field] == entry[field]

        cleared_response = http.delete(classify_path)
        assert cleared_response.status_code == 200
        assert cleared_response.json() == entry
        assert http.get(f"{path}/{entry['id']}").json() == entry

        classified_payload = {**payload, **classification, "billable": True}
        classified_entry = http.post(path, json=classified_payload)
        assert classified_entry.status_code == 201
        assert classified_entry.json()["task_id"] == task["id"]

        mismatch = {**payload, "client_id": client["id"], "project_id": other_project["id"]}
        mismatch_response = http.post(path, json=mismatch)
        assert mismatch_response.status_code == 422
        mismatch_classification = http.put(
            classify_path,
            json={
                "client_id": client["id"],
                "project_id": other_project["id"],
                "task_id": None,
            },
        )
        assert mismatch_classification.status_code == 422
        for partial in [
            {**payload, "client_id": client["id"]},
            {**payload, "project_id": project["id"]},
            {**payload, "task_id": task["id"]},
        ]:
            partial_response = http.post(path, json=partial)
            assert partial_response.status_code == 422
        for missing_reference in [
            {**payload, "client_id": str(uuid4()), "project_id": project["id"]},
            {**payload, "client_id": client["id"], "project_id": str(uuid4())},
            {
                **payload,
                "client_id": client["id"],
                "project_id": project["id"],
                "task_id": str(uuid4()),
            },
            {
                **payload,
                "client_id": foreign_client["id"],
                "project_id": foreign_project["id"],
            },
        ]:
            missing_response = http.post(path, json=missing_reference)
            assert missing_response.status_code == 404
            assert missing_response.json() == {"detail": "Resource not found"}
        for missing_classification in [
            {**classification, "client_id": str(uuid4())},
            {**classification, "project_id": str(uuid4())},
            {**classification, "task_id": str(uuid4())},
            {
                "client_id": foreign_client["id"],
                "project_id": foreign_project["id"],
                "task_id": None,
            },
        ]:
            missing_response = http.put(classify_path, json=missing_classification)
            assert missing_response.status_code == 404
            assert missing_response.json() == {"detail": "Resource not found"}

        for invalid in [
            {**payload, "start": "2026-01-01T12:00:00"},
            {**payload, "end": "2026-01-01T12:00:00"},
            {**payload, "end": payload["start"]},
            {**payload, "end": "2026-01-01T06:29:59Z"},
            {**payload, "start": 1767261600},
            {**payload, "billable": 1},
            {**payload, "duration": "PT1H"},
            {**payload, "id": str(uuid4())},
        ]:
            assert http.post(path, json=invalid).status_code == 422

        missing_id = uuid4()
        missing_get = http.get(f"{path}/{missing_id}")
        foreign_get = http.get(
            f"/workspaces/{other_workspace}/time-entries/{entry['id']}"
        )
        assert missing_get.status_code == foreign_get.status_code == 404
        assert missing_get.json() == foreign_get.json() == {"detail": "Resource not found"}
        for operation, target in [
            (http.put, f"{path}/{missing_id}/classification"),
            (
                http.put,
                f"/workspaces/{other_workspace}/time-entries/{entry['id']}/classification",
            ),
        ]:
            missing_update = operation(target, json=classification)
            assert missing_update.status_code == 404
            assert missing_update.json() == {"detail": "Resource not found"}
        for target in [
            f"{path}/{missing_id}/classification",
            f"/workspaces/{other_workspace}/time-entries/{entry['id']}/classification",
        ]:
            missing_clear = http.delete(target)
            assert missing_clear.status_code == 404
            assert missing_clear.json() == {"detail": "Resource not found"}


def test_time_entry_transaction_rolls_back(database: Engine) -> None:
    workspace = uuid4()
    transaction = SqlAlchemyTimeEntryTransaction(database, ClientRepository)
    identifier = uuid4()
    entry = TimeEntry(
        id=identifier,
        workspace_id=workspace,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
        billable=True,
    )
    with pytest.raises(RuntimeError, match="after flush"):
        with transaction(workspace) as entries:
            entries.add(entry)
            raise RuntimeError("after flush")
    with transaction(workspace) as entries:
        assert entries.get(identifier) is None
